"""Bilingual Excel + Markdown report."""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .extract import Field
from .rules import CONFIG, SEVERITY

FILL = dict(ERROR="F8D7DA", WARNING="FFE5B4", MINOR="FFF3CD", INFO="DCEBFA")
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
    wb.save(path)


def markdown(res) -> str:
    counts = {s: sum(f.severity == s for f in res.findings) for s in SEVERITY}
    out = [f"# Shipment check / Kiểm tra bộ chứng từ — {res.name}", "",
           "## Documents / Chứng từ", ""]
    for d in res.docs:
        k = CONFIG["doc_kinds"][d.kind]
        out.append(f"- **{k['en']} / {k['vi']}**: {d.name}{'' if d.is_draft or d.kind in ('CI', 'SC') else ' (not DRAFT)'}")
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
