"""Bilingual Excel + Markdown report."""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .extract import Field
from .rules import CONFIG, SEVERITY

FILL = dict(ERROR="F8D7DA", WARNING="FFE5B4", MINOR="FFF3CD", INFO="DCEBFA")
CHECK_FILL = dict(FAIL="F8D7DA", REVIEW_REQUIRED="FFE5B4", NOT_RUN="FFF3CD", NOT_APPLICABLE="EEEEEE", PASS="E6F4EA")
VERDICT_TXT = dict(
    RED=("RED — DOCUMENT ERROR: open error(s) in the documents", "ĐỎ — LỖI CHỨNG TỪ: còn lỗi trên chứng từ"),
    AMBER=("AMBER — INCOMPLETE / REVIEW: core check(s) could not run or need review",
           "VÀNG — CHƯA ĐỦ / CẦN XEM LẠI: có bước kiểm tra chính chưa chạy được hoặc cần xem lại"),
    GREEN=("GREEN — VERIFIED: all applicable core checks passed", "XANH — ĐÃ KIỂM CHỨNG: mọi bước kiểm tra chính áp dụng đều đạt"))
CHECK_ST = dict(PASS=("Pass", "Đạt"), FAIL=("Fail", "Không đạt"), REVIEW_REQUIRED=("Review", "Cần xem lại"),
                NOT_RUN=("Not run", "Chưa chạy"), NOT_APPLICABLE=("Not applicable", "Không áp dụng"))


def check_rows(checks: list[dict]) -> list[dict]:
    """Check records in display order: core first, then FAIL, REVIEW, NOT_RUN, NOT_APPLICABLE, PASS."""
    from .checks import CheckStatus
    order = {s: i for i, s in enumerate(CheckStatus.ALL)}
    return sorted(checks, key=lambda r: (not r.get("core"), order.get(r["status"], 9), r["id"], r["group"], r.get("doc", "")))
ICON = dict(ERROR="🔴", WARNING="🟠", MINOR="🟡", INFO="🔵")


def sev(s, lang):
    return CONFIG["severity"][s][lang]


def plain(v):
    if isinstance(v, Field):
        v = v.value
    if isinstance(v, (list, tuple)):
        return ", ".join(str(plain(x)) for x in v)
    return "" if v is None else str(v)


def per_file(res) -> list[dict]:
    """Findings counted per file (the file holding the value to fix), in document order
    Invoice/PL -> Sales Contract -> B/L -> Form D; files with no findings included."""
    rows = []
    for d in res.docs:
        own = [f for f in res.findings if f.docs and f.docs[0] is d]
        c = {s: sum(f.severity == s for f in own) for s in SEVERITY}
        rows.append(dict(file=d.name, kind=d.kind, total=len(own), **c))
    order = {"CI": 0, "SC": 1, "BL": 2, "CO": 3}
    rows.sort(key=lambda r: (order.get(r["kind"], 9), r["file"]))
    return rows


def _sheet(ws, header, widths):
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="34495E")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = w
    ws.freeze_panes = "A2"


def excel(res, path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Findings - Ket qua"
    _sheet(ws, ["#", "Severity / Mức độ", "Rule", "Message (EN)", "Nội dung (VI)", "Document / Chứng từ",
                "Page / Trang", "Current / Hiện tại", "Suggested / Đề xuất",
                "Note (EN)", "Ghi chú (VI)", "Screenshot / Ảnh"],
           [4, 14, 18, 46, 46, 40, 7, 30, 30, 36, 36, 26])
    for i, f in enumerate(res.findings, 1):
        ws.append([i, f"{f.severity} / {sev(f.severity, 'vi')}", f.key, f.text("en"), f.text("vi"),
                   "\n".join(f.doc_names), f.page or "", f.current, f.suggested,
                   f.note("en"), f.note("vi"),
                   "\n".join(p.name for p in f.evidence)])
        row = ws[ws.max_row]
        for c in row:
            c.fill = PatternFill("solid", fgColor=FILL[f.severity])
            c.alignment = Alignment(wrap_text=True, vertical="top")
        if f.evidence:
            row[11].hyperlink = f"evidence/{f.evidence[0].name}"
            row[11].font = Font(color="0563C1", underline="single")

    ws0 = wb.create_sheet("By file - Theo file", 0)
    _sheet(ws0, ["Document / Chứng từ", "Type / Loại"] + [f"{s} / {sev(s, 'vi')}" for s in SEVERITY]
           + ["Total / Tổng"], [50, 30, 12, 14, 12, 14, 12])
    for r in per_file(res):
        k = CONFIG["doc_kinds"][r["kind"]]
        ws0.append([r["file"], f"{k['en']} / {k['vi']}"] + [r[s] for s in SEVERITY] + [r["total"]])
        row = ws0[ws0.max_row]
        worst = next((s for s in SEVERITY if r[s]), None)
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
            if worst in ("ERROR", "WARNING"):
                c.fill = PatternFill("solid", fgColor=FILL[worst])
    ws0.append(["TOTAL / TỔNG", ""] + [sum(f.severity == s for f in res.findings) for s in SEVERITY]
               + [len(res.findings)])
    for c in ws0[ws0.max_row]:
        c.font = Font(bold=True)
    wb.active = 0

    ws2 = wb.create_sheet("Extracted data - Du lieu")
    _sheet(ws2, ["Document / Chứng từ", "Type / Loại", "Field / Trường", "Value / Giá trị", "Page / Trang"],
           [45, 26, 20, 90, 7])
    for d in res.docs:
        kind = CONFIG["doc_kinds"][d.kind]["en"]
        for k, v in d.f.items():
            pg = v.page + 1 if isinstance(v, Field) and v.end > v.start else ""
            ws2.append([d.name, kind, k, plain(v), pg])
        for n, it in enumerate(d.items, 1):
            ws2.append([d.name, kind, f"item {n}", "; ".join(f"{k}={plain(v)}" for k, v in it.items()),
                        it["qty"].page + 1])
        for n, it in enumerate(d.pl_items, 1):
            ws2.append([d.name, kind, f"PL item {n}", "; ".join(f"{k}={plain(v)}" for k, v in it.items()),
                        it["qty"].page + 1])

    ws3 = wb.create_sheet("Not recognised - Khong doc duoc")
    _sheet(ws3, ["Document / Chứng từ", "Issue (EN)", "Vấn đề (VI)"], [45, 60, 60])
    for u in res.unrecognised:
        ws3.append([u["doc"], u["what"], u["vi"]])
    if not res.unrecognised:
        ws3.append(["—", "Everything recognised", "Đã đọc được toàn bộ"])
    _checks_sheet(wb, res)                       # added last: the existing sheets keep their order and layout
    wb.save(path)


def _checks_sheet(wb, res):
    """Every check and its execution status (new in LDV 2.3; the other sheets are unchanged)."""
    from .checks import check_name, reason_text
    ws = wb.create_sheet("Checks - Kiem tra")
    v = res.verdict or {}
    en, vi = VERDICT_TXT.get(v.get("state"), ("—", "—"))
    ws.append([f"{en} / {vi}"])
    ws.append([f"Open errors / Lỗi còn mở: {v.get('open_errors', 0)} · Core checks not run / Chưa chạy: "
               f"{v.get('core_not_run', 0)} · Core checks to review / Cần xem lại: {v.get('core_review', 0)} · "
               f"Other checks not run / Kiểm tra khác chưa chạy: {v.get('noncore_not_run', 0)}"])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([])
    header = ["Check / Mã", "Check (EN)", "Kiểm tra (VI)", "Core / Chính", "Group / Nhóm", "Document / Chứng từ",
              "Status / Trạng thái", "Reason (EN)", "Lý do (VI)", "Findings / Kết quả #"]
    ws.append(header)
    for c in ws[4]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="34495E")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, w in enumerate([22, 44, 44, 8, 20, 36, 16, 50, 50, 12]):
        ws.column_dimensions[chr(65 + i)].width = w
    ws.freeze_panes = "A5"
    fills = {k: PatternFill("solid", fgColor=v) for k, v in CHECK_FILL.items()}
    wrap = Alignment(wrap_text=True, vertical="top")
    for r in check_rows([c.to_dict() for c in res.checks]):
        st_en, st_vi = CHECK_ST[r["status"]]
        ws.append([r["id"], check_name(r["id"], "en"), check_name(r["id"], "vi"), "✔" if r["core"] else "",
                   f"{r['group']} ({r['group_label']})", r.get("doc") or "", f"{st_en} / {st_vi}",
                   reason_text(r, "en"), reason_text(r, "vi"), ", ".join(map(str, r["findings"]))])
        row = ws[ws.max_row]                       # styles are slow in openpyxl: colour the status, wrap the texts
        row[6].fill = fills[r["status"]]
        row[7].alignment = row[8].alignment = wrap      # the reasons can be long


def markdown(res) -> str:
    counts = {s: sum(f.severity == s for f in res.findings) for s in SEVERITY}
    out = [f"# Shipment check / Kiểm tra bộ chứng từ — {res.name}", "",
           "## Documents / Chứng từ", ""]
    for d in res.docs:
        k = CONFIG["doc_kinds"][d.kind]
        out.append(f"- **{k['en']} / {k['vi']}**: {d.name}{'' if d.is_draft or d.kind in ('CI', 'SC') else ' (not DRAFT)'}")
    v = res.verdict or {}
    if v:
        from .checks import check_name, reason_text
        en, vi = VERDICT_TXT.get(v.get("state"), ("—", "—"))
        out += ["", "## Verification / Kiểm chứng", "", f"**{en}** / _{vi}_", "",
                f"Open errors: {v.get('open_errors', 0)} · core checks not run: {v.get('core_not_run', 0)} · "
                f"core checks to review: {v.get('core_review', 0)} · other checks not run: {v.get('noncore_not_run', 0)}", ""]
        gaps = [r for r in check_rows([c.to_dict() for c in res.checks]) if r["status"] == "NOT_RUN"]
        if gaps:
            out += ["| Check | Core | Group | Reason / Lý do |", "|---|---|---|---|"]
            out += [f"| {check_name(r['id'], 'en')} | {'✔' if r['core'] else ''} | {r['group_label']} | "
                    f"{reason_text(r, 'en')}<br>_{reason_text(r, 'vi')}_ |" for r in gaps]
    out += ["", "## Findings / Kết quả  " + "  ".join(f"{ICON[s]} {sev(s, 'en')}/{sev(s, 'vi')}: {n}"
                                                        for s, n in counts.items()), ""]
    out += ["### By file / Theo file", "",
            "| Document / Chứng từ | " + " | ".join(f"{ICON[s]} {sev(s, 'en')}" for s in SEVERITY) + " | Total |",
            "|---|" + "---:|" * (len(SEVERITY) + 1)]
    out += [f"| {r['file']} | " + " | ".join(str(r[s]) for s in SEVERITY) + f" | {r['total']} |"
            for r in per_file(res)]
    out += ["", "### Details / Chi tiết", ""]
    out += ["| # | | Message / Nội dung | Document | Page | Current → Suggested |",
            "|---|---|---|---|---|---|"]
    for i, f in enumerate(res.findings, 1):
        ce = f"`{f.current}` → `{f.suggested}`" if f.current or f.suggested else ""
        out.append(f"| {i} | {ICON[f.severity]} | {f.text('en')}<br>_{f.text('vi')}_ | {f.doc_names[0]} | "
                   f"{f.page or ''} | {ce} |")
    out += ["", "## Not recognised / Không đọc được", ""]
    out += [f"- {u['doc']}: {u['what']} / {u['vi']}" for u in res.unrecognised] or ["- Everything recognised / Đã đọc được toàn bộ"]
    return "\n".join(out) + "\n"
