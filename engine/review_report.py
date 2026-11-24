"""Review report: executive summary, document inventory, findings, cross-check, conclusion — as HTML, PDF and Excel.

Input is a stored review session (session.py) plus the reviewer's decisions from history.db. The report keeps the
two apart: "Automated result (LDV)" is what the checks found; "Reviewer conclusion" is what a person decided.
Generated files go to <report folder>/reports/; the checked documents are never touched.
"""
import base64
import html
import io
from datetime import datetime
from pathlib import Path

from .rules import CONFIG, SEVERITY
from .session import ref_docs, wrong_docs

OPEN = ("open", "in_review", "waiting")
DONE = ("fixed", "accepted", "not_error")
COLOR = dict(ERROR="#d93025", WARNING="#e8710a", MINOR="#8a6700", INFO="#1a73e8")
TINT = dict(ERROR="#fce8e6", WARNING="#feefe3", MINOR="#fef7e0", INFO="#e8f0fe", OK="#e6f4ea", GREY="#f1f3f4")

TXT = {
    "title": ("Shipment document review report", "Báo cáo kiểm tra bộ chứng từ"),
    "s1": ("1. Executive summary", "1. Tóm tắt"), "s2": ("2. Document inventory", "2. Danh mục chứng từ"),
    "s3": ("3. Findings summary", "3. Tổng hợp lỗi"), "s4": ("4. Detailed findings", "4. Chi tiết lỗi"),
    "s5": ("5. Cross-document comparison", "5. Đối chiếu giữa các chứng từ"),
    "s6": ("6. Final review conclusion", "6. Kết luận"),
    "review_id": ("Review ID", "Mã lần kiểm tra"), "shipment": ("Shipment / invoice no.", "Lô hàng / số hóa đơn"),
    "package": ("Document package", "Bộ chứng từ"), "checked": ("Checked", "Ngày kiểm tra"),
    "generated": ("Report generated", "Ngày lập báo cáo"), "version": ("LDV version", "Phiên bản LDV"),
    "n_docs": ("Documents", "Số chứng từ"), "auto": ("Automated result (LDV)", "Kết quả kiểm tra tự động (LDV)"),
    "human": ("Reviewer conclusion", "Kết luận của người kiểm tra"),
    "auto_err": ("Not ready: {n} open error(s)", "Chưa đạt: còn {n} lỗi"),
    "auto_warn": ("Needs verification: {n} open warning(s)", "Cần kiểm tra lại: còn {n} cảnh báo"),
    "auto_gaps": ("No open errors or warnings; {n} item(s) could not be read and need a manual check",
                  "Không còn lỗi hay cảnh báo; {n} mục không đọc được cần kiểm tra thủ công"),
    "auto_ok": ("No open errors or warnings", "Không còn lỗi hay cảnh báo"),
    "v_red": ("RED: document error. {n} open error(s)", "ĐỎ: lỗi chứng từ. Còn {n} lỗi"),
    "v_amber": ("AMBER: not verified. {n} core check(s) could not run or need review",
                "VÀNG: chưa kiểm chứng. {n} bước kiểm tra chính chưa chạy được hoặc cần xem lại"),
    "v_green": ("GREEN: verified. Every applicable core check passed", "XANH: đã kiểm chứng. Mọi bước kiểm tra chính áp dụng đều đạt"),
    "so_none": ("Not signed off", "Chưa xác nhận"),
    "so_approved": ("Approved", "Đạt"),
    "so_approved_exception": ("Approved with exception", "Đạt có ngoại lệ"),
    "so_returned": ("Returned for correction", "Trả lại để sửa"),
    "so_by": ("by {who} on {ts}", "bởi {who} lúc {ts}"), "reason": ("Reason / note", "Lý do / ghi chú"),
    "so_open": ("At sign-off: {e} open error(s), {w} open warning(s)", "Khi xác nhận: còn {e} lỗi, {w} cảnh báo"),
    "file": ("File", "Tên file"), "type": ("Type", "Loại"), "pages": ("Pages", "Số trang"),
    "status": ("Status", "Trạng thái"), "findings": ("Findings", "Số lỗi"),
    "analyzed": ("Analyzed", "Đã phân tích"), "type_user": ("type set by reviewer", "loại do người kiểm tra chọn"),
    "not_draft": ("not marked DRAFT", "không có chữ DRAFT"), "not_checked": ("Not checked", "Chưa kiểm tra"),
    "severity": ("Severity", "Mức độ"), "total": ("Total", "Tổng"), "open": ("Open", "Còn mở"),
    "resolved": ("Resolved", "Đã xử lý"),
    "id": ("Finding", "Mã lỗi"), "doc": ("Document", "Chứng từ"), "page": ("page", "trang"),
    "found": ("Found", "Trên chứng từ"), "expected": ("Expected", "Đúng ra là"),
    "ref_doc": ("Reference document", "Chứng từ tham chiếu"), "evidence": ("Evidence", "Bằng chứng"),
    "wrong": ("value to check", "giá trị cần kiểm tra"), "refv": ("reference value", "giá trị tham chiếu"),
    "action": ("Suggested action", "Đề xuất xử lý"), "rule": ("Rule", "Quy tắc"),
    "rev_status": ("Reviewer status", "Trạng thái xử lý"), "rev_note": ("Reviewer comment", "Ghi chú người kiểm tra"),
    "trail": ("Decision trail", "Lịch sử xử lý"),
    "no_loc": ("No position in the document (e.g. information missing)", "Không có vị trí trên chứng từ (vd thiếu thông tin)"),
    "none": ("No findings.", "Không có lỗi."), "field": ("Field", "Thông tin"), "result": ("Result", "Kết quả"),
    "cmp_match": ("Match", "Khớp"), "cmp_mismatch": ("Mismatch", "Không khớp"),
    "cmp_incomplete": ("Not read everywhere", "Thiếu giá trị"), "cmp_single": ("Only one document", "Chỉ một chứng từ"),
    "cmp_none": ("Not read", "Không đọc được"), "not_read": ("not read", "không đọc được"), "blank": ("(empty)", "(để trống)"),
    "nodoc": ("no document", "không có chứng từ"), "cmp_not_read": ("Not compared (not read by LDV): {f}",
                                                                    "Chưa đối chiếu (LDV chưa đọc): {f}"),
    "cmp_only_diff": ("Fields that agree on every document are left out ({n}).",
                      "Các thông tin khớp trên mọi chứng từ được lược bỏ ({n})."),
    "lines": ("Goods lines by model", "Dòng hàng theo model"), "model": ("Model", "Model"),
    "qty": ("Qty", "SL"), "price": ("Price", "Đơn giá"),
    "outstanding": ("Outstanding issues", "Vấn đề còn tồn tại"), "resolved_n": ("Resolved findings", "Lỗi đã xử lý"),
    "none_open": ("None", "Không có"), "filter_info": ("Info findings are not included.", "Không bao gồm mục Thông tin."),
    "filter_open": ("Only findings that are not resolved are included.", "Chỉ bao gồm các lỗi chưa xử lý."),
    "legacy": ("Saved by an older LDV version: evidence positions and extracted values are not available.",
               "Lưu bởi phiên bản LDV cũ: không có vị trí bằng chứng và giá trị trích xuất."),
    "disclaimer": ("Automated findings are produced by LDV from the documents' text; statuses, comments and the "
                   "conclusion are decisions recorded by the reviewer. The documents themselves were not changed.",
                   "Lỗi tự động do LDV phát hiện từ nội dung chứng từ; trạng thái, ghi chú và kết luận là quyết định "
                   "của người kiểm tra. Chứng từ gốc không bị thay đổi."),
    "unrec": ("Not checked / not read", "Chưa kiểm tra / không đọc được"),
}
STATUS = dict(open=("Open", "Chưa xử lý"), in_review=("In review", "Đang xem xét"),
              waiting=("Waiting for supplier", "Chờ NCC sửa"), fixed=("Fixed", "Đã sửa"),
              accepted=("Accepted – no action", "Chấp nhận – không cần sửa"), not_error=("Not an error", "Không phải lỗi"))
COLS = {"CI": "Invoice", "PL": "Packing list", "SC": "Sales contract", "BL": "B/L", "CO": "Form D"}


def finding_id(shipment: str, revision, no: int) -> str:
    return f"{shipment}-R{revision or 1}-{int(no):02d}"


class _L:
    """Text in the report language(s): en, vi or both ("English / Tiếng Việt")."""

    def __init__(self, lang: str):
        self.langs = ["en", "vi"] if lang == "both" else [lang]

    def __call__(self, key, **kw):
        pair = TXT[key]
        parts = [pair[0 if l == "en" else 1].format(**kw) for l in self.langs]
        return parts[0] if len(parts) == 1 or parts[0] == parts[1] else " / ".join(parts)

    def pick(self, en, vi, sep=" / "):
        parts = [en if l == "en" else vi for l in self.langs]
        return parts[0] if len(parts) == 1 or parts[0] == parts[1] else sep.join(p for p in parts if p)

    def sev(self, s):
        return self.pick(CONFIG["severity"][s]["en"], CONFIG["severity"][s]["vi"])

    def kind(self, k, form=""):
        from .checks import kind_name
        return self.pick(kind_name(k, "en", form), kind_name(k, "vi", form)) if k in CONFIG["doc_kinds"] else "—"

    def status(self, k):
        return self.pick(*STATUS.get(k, (k, k)))

    def msg(self, f):
        return self.pick(f.get("msg_en", ""), f.get("msg_vi", ""), "<br>")

    def note(self, f):
        return self.pick(f.get("note_en", ""), f.get("note_vi", ""), "<br>")


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _ts(s: str) -> str:
    return (s or "").replace("T", " ")


def outcome(s: dict, marks: dict) -> tuple[str, str, int, int]:
    """(automated result key, colour, open errors, open warnings / core checks open) — same logic as the dashboard.
    Reviews with check records (LDV >= 2.3): the three-state verdict; older reviews: the legacy finding count."""
    from .checks import effective
    v = effective(s, marks)
    if v is not None:
        n_open = v["core_not_run"] + v["core_review"]
        return dict(RED=("v_red", "ERROR"), AMBER=("v_amber", "WARNING"), GREEN=("v_green", "OK"))[v["state"]] + (
            v["open_errors"], n_open)
    st = lambda f: marks.get(f["sig"], {}).get("status", "open")
    e = sum(f["severity"] == "ERROR" and st(f) in OPEN for f in s["findings"])
    w = sum(f["severity"] == "WARNING" and st(f) in OPEN for f in s["findings"])
    gaps = len(s.get("unrecognised", []))
    if e:
        return "auto_err", "ERROR", e, w
    if w:
        return "auto_warn", "WARNING", e, w
    if gaps:
        return "auto_gaps", "WARNING", e, w
    return "auto_ok", "OK", e, w


def build_html(s: dict, marks: dict, trails: dict, cmp: dict | None, signoff: dict | None, opts: dict,
               images: str = "base64") -> str:
    """opts: lang (en|vi|both), info (bool), only_open (bool), snapshots (bool), crosscheck (bool).
    images: base64 (self-contained HTML) or relative (paths inside the report folder, for the PDF)."""
    L = _L(opts.get("lang", "en"))
    out_dir = Path(s.get("out_dir") or ".")
    st = lambda f: marks.get(f["sig"], {}).get("status", "open")
    fs = [f for f in s["findings"] if (opts.get("info") or f["severity"] != "INFO")
          and (not opts.get("only_open") or st(f) in OPEN)]
    rev = s.get("revision") or 1
    key, col, n_err, n_warn = outcome(s, marks)
    now = datetime.now().isoformat(timespec="seconds")
    H = []
    a = H.append
    a(f"<h1>{_e(L('title'))}</h1>")
    a(f"<p class='sub'>{_e(s['shipment'])} · {_e(L('review_id'))}: {_e(s['shipment'])}-R{rev}"
      f" · {_e(L('generated'))}: {_e(_ts(now))}</p>")

    # ---- 1. executive summary
    a(f"<h2>{_e(L('s1'))}</h2><table class='kv'>")
    for k, v in [("review_id", f"{s['shipment']}-R{rev}"), ("shipment", s["shipment"]), ("package", s.get("name", "")),
                 ("checked", _ts(s.get("check_ts") or s.get("created"))), ("n_docs", len(s["docs"])),
                 ("version", s.get("version", ""))]:
        a(f"<tr><th width='28%'>{_e(L(k))}</th><td>{_e(v)}</td></tr>")
    a(f"<tr><th width='28%'>{_e(L('auto'))}</th><td style='background:{TINT[col]};font-weight:bold'>"
      f"{_e(L(key, n=n_err or n_warn or len(s.get('unrecognised', []))))}</td></tr>")
    a(f"<tr><th width='28%'>{_e(L('human'))}</th><td>{_signoff_html(L, signoff)}</td></tr></table>")
    counts = {x: sum(f["severity"] == x for f in s["findings"]) for x in SEVERITY}
    a("<p>" + " · ".join(f"<span style='color:{COLOR[x]};font-weight:bold'>{_e(L.sev(x))}: {counts[x]}</span>"
                         for x in SEVERITY) + "</p>")
    if s.get("legacy"):
        a(f"<p class='note'>{_e(L('legacy'))}</p>")

    # ---- 2. document inventory
    a(f"<h2>{_e(L('s2'))}</h2><table><tr><th>{_e(L('file'))}</th><th>{_e(L('type'))}</th><th>{_e(L('pages'))}</th>"
      f"<th>{_e(L('status'))}</th><th>{_e(L('findings'))}</th></tr>")
    for d in s["docs"]:
        flags = [L("analyzed")]
        if d.get("kind_set_by_user"):
            flags.append(L("type_user"))
        if d.get("is_draft") is False and d["kind"] not in ("CI", "SC"):
            flags.append(L("not_draft"))
        n = sum(d["name"] in wrong_docs(f) for f in s["findings"])
        a(f"<tr><td>{_e(d['name'])}</td><td>{_e(L.kind(d['kind'], d.get('form', '')))}</td><td>{_e(d.get('pages') or '')}</td>"
          f"<td>{_e(', '.join(flags))}</td><td>{n}</td></tr>")
    for name in s.get("skipped", []):
        a(f"<tr><td>{_e(name)}</td><td>—</td><td></td><td>{_e(L('not_checked'))}</td><td></td></tr>")
    a("</table>")
    if s.get("unrecognised"):
        a(f"<p><b>{_e(L('unrec'))}</b></p><ul>")
        for u in s["unrecognised"]:
            a(f"<li>{_e(u['doc'])}: {_e(L.pick(u['what'], u['vi']))}</li>")
        a("</ul>")

    # ---- 3. findings summary
    a(f"<h2>{_e(L('s3'))}</h2><table><tr><th>{_e(L('severity'))}</th><th>{_e(L('total'))}</th>"
      f"<th>{_e(L('open'))}</th><th>{_e(L('resolved'))}</th></tr>")
    for x in SEVERITY:
        allx = [f for f in s["findings"] if f["severity"] == x]
        o = sum(st(f) in OPEN for f in allx)
        a(f"<tr><td style='color:{COLOR[x]};font-weight:bold'>{_e(L.sev(x))}</td><td>{len(allx)}</td><td>{o}</td>"
          f"<td>{len(allx) - o}</td></tr>")
    a("</table>")
    notes = [L("filter_info")] if not opts.get("info") else []
    if opts.get("only_open"):
        notes.append(L("filter_open"))
    if notes:
        a(f"<p class='note'>{_e(' '.join(notes))}</p>")

    # ---- 4. detailed findings
    a(f"<h2>{_e(L('s4'))}</h2>")
    if not fs:
        a(f"<p>{_e(L('none'))}</p>")
    for f in fs:
        m = marks.get(f["sig"], {})
        x = f["severity"]
        a(f"<table class='finding'><tr><td colspan='2' style='background:{TINT[x]}'>"
          f"<b style='color:{COLOR[x]}'>{_e(L.sev(x).upper())}</b> &#160; <b>{_e(finding_id(s['shipment'], rev, f['no']))}</b>"
          f" &#160; {L.msg(f)}</td></tr>")
        pg = f" · {L('page')} {f['page']}" if f.get("page") else ""
        rows = [("doc", "<br>".join(_e(n) + (pg if n == f["doc"] else "") for n in wrong_docs(f)))]
        if f.get("current") or f.get("suggested"):
            rows += [("found", f"<b>{_e(f.get('current') or '—')}</b>"), ("expected", f"<b>{_e(f.get('suggested') or '—')}</b>")]
        if ref_docs(f):
            rows.append(("ref_doc", _e(", ".join(ref_docs(f)))))
        locs = f.get("locs")
        if locs:
            seen = list(dict.fromkeys((l["doc"], l["page"] + 1, l["role"]) for l in locs))
            rows.append(("evidence", "<br>".join(f"{_e(d)} · {L('page')} {p} ({_e(L('wrong' if r == 'wrong' else 'refv'))})"
                                                 for d, p, r in seen)))
        elif locs is not None:
            rows.append(("evidence", _e(L("no_loc"))))
        if L.note(f):
            rows.append(("action", L.note(f)))
        rows.append(("rule", f"<code>{_e(f['key'])}</code>"))
        rows.append(("rev_status", f"<b>{_e(L.status(m.get('status', 'open')))}</b>"))
        if m.get("note"):
            rows.append(("rev_note", _e(m["note"])))
        tr = trails.get(f["sig"]) or []
        if tr:
            rows.append(("trail", "<br>".join(
                f"{_e(_ts(e['ts']))}{' · ' + _e(e['who']) if e.get('who') else ''}: "
                f"{_e(L.status(e['old_status']))} → {_e(L.status(e['status']))}"
                + (f" — “{_e(e['note'])}”" if e.get("note") else "") for e in tr)))
        for k, v in rows:
            a(f"<tr><th width='22%'>{_e(L(k))}</th><td>{v}</td></tr>")
        if opts.get("snapshots"):
            for p in f.get("evidence", [])[:3]:
                src = _img(out_dir, p, images)
                if src:
                    a(f"<tr><td colspan='2'><img src='{src}' width='480'></td></tr>")
        a("</table>")

    # ---- 5. cross-check
    if opts.get("crosscheck") and cmp and any(r["result"] != "none" for r in cmp["rows"]):
        a(f"<h2>{_e(L('s5'))}</h2>")
        cols = cmp["columns"]
        keep = [r for r in cmp["rows"] if r["result"] in ("mismatch", "incomplete")] if opts.get("cmp_diff") else \
            [r for r in cmp["rows"] if r["result"] != "none"]
        a(f"<table><tr><th>{_e(L('field'))}</th>" + "".join(f"<th>{_e(L.pick(c['en'], c['vi']))}</th>" for c in cols)
          + f"<th>{_e(L('result'))}</th></tr>")
        for r in keep:
            a(f"<tr><td>{_e(L.pick(r['en'], r['vi']))}{' (' + r['unit'] + ')' if r['unit'] else ''}</td>")
            for c in cols:
                cell = r["cells"][c["id"]]
                txt = (f'{cell.get("label", "")}: {L("blank")}' if cell["state"] == "blank" else
                       {"value": cell.get("show", ""), "missing": L("not_read"), "na": "·", "nodoc": L("nodoc")}[cell["state"]])
                bg = TINT["ERROR"] if cell.get("odd") else TINT["MINOR"] if cell["state"] == "missing" else ""
                fg = f"color:{COLOR['WARNING']};font-weight:bold;" if cell["state"] == "blank" else ""   # blank on the document
                a(f"<td style='{fg}{'background:' + bg if bg else ''}'>{_e(txt)}</td>")
            rc = "#b3261e" if r["result"] == "mismatch" else "#202124"
            a(f"<td style='color:{rc};font-weight:bold'>{_e(L('cmp_' + r['result']))}</td></tr>")
        a("</table>")
        if opts.get("cmp_diff"):
            a(f"<p class='note'>{_e(L('cmp_only_diff', n=len(cmp['rows']) - len(keep)))}</p>")
        if cmp.get("lines"):
            a(f"<p><b>{_e(L('lines'))}</b></p><table><tr><th>{_e(L('model'))}</th>"
              + "".join(f"<th>{_e(L('qty'))} {COLS[k]}</th>" for k in ("CI", "PL", "SC", "CO"))
              + f"<th>{_e(L('price'))} {COLS['CI']}</th><th>{_e(L('price'))} {COLS['SC']}</th><th>{_e(L('result'))}</th></tr>")
            for r in cmp["lines"]:
                q = "".join(f"<td>{r['qty'][k]:,.0f}</td>" if k in r["qty"] else
                            f"<td>{_e(L('not_read')) if k in r['missing'] else '·'}</td>" for k in ("CI", "PL", "SC", "CO"))
                p = "".join(f"<td>{r['price'][k]:,.2f}</td>" if r["price"].get(k) is not None else "<td>·</td>"
                            for k in ("CI", "SC"))
                a(f"<tr><td>{_e(r['model'])}</td>{q}{p}<td>{_e(L('cmp_' + r['result']))}</td></tr>")
            a("</table>")
        if cmp.get("not_read"):
            a(f"<p class='note'>{_e(L('cmp_not_read', f=', '.join(L.pick(x['en'], x['vi']) for x in cmp['not_read'])))}</p>")

    # ---- 6. conclusion
    a(f"<h2>{_e(L('s6'))}</h2><table class='kv'>")
    a(f"<tr><th width='28%'>{_e(L('auto'))}</th><td style='background:{TINT[col]};font-weight:bold'>"
      f"{_e(L(key, n=n_err or n_warn or len(s.get('unrecognised', []))))}</td></tr>")
    a(f"<tr><th width='28%'>{_e(L('human'))}</th><td>{_signoff_html(L, signoff)}</td></tr>")
    outstanding = [f for f in s["findings"] if f["severity"] != "INFO" and st(f) in OPEN]
    a(f"<tr><th width='28%'>{_e(L('outstanding'))} ({len(outstanding)})</th><td>"
      + ("<br>".join(f"<span style='color:{COLOR[f['severity']]}'>■</span> {_e(finding_id(s['shipment'], rev, f['no']))}"
                     f" — {_e(f.get('msg_en') if L.langs[0] == 'en' else f.get('msg_vi'))} ({_e(L.status(st(f)))})"
                     for f in outstanding) or _e(L("none_open"))) + "</td></tr>")
    resolved = [f for f in s["findings"] if st(f) in DONE]
    a(f"<tr><th width='28%'>{_e(L('resolved_n'))}</th><td>{len(resolved)}</td></tr></table>")
    a(f"<p class='note'>{_e(L('disclaimer'))}</p>")
    return _page(L("title") + " — " + s["shipment"], "".join(H))


def _signoff_html(L, so: dict | None) -> str:
    if not so:
        return f"<i>{_e(L('so_none'))}</i>"
    color = {"approved": "#188038", "approved_exception": "#e8710a", "returned": "#d93025"}[so["result"]]
    out = (f"<b style='color:{color}'>{_e(L('so_' + so['result']))}</b> "
           f"{_e(L('so_by', who=so.get('who') or '—', ts=_ts(so['ts'])))}")
    if so.get("note"):
        out += f"<br>{_e(L('reason'))}: “{_e(so['note'])}”"
    out += f"<br><span class='note'>{_e(L('so_open', e=so.get('open_errors', 0), w=so.get('open_warnings', 0)))}</span>"
    return out


def _img(out_dir: Path, rel: str, mode: str) -> str | None:
    p = out_dir / rel
    if not p.exists():
        return None
    if mode == "relative":
        return rel
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


CSS = """
body {font-family: ldv, Arial, Helvetica, sans-serif; font-size: 9pt; color: #202124; line-height: 1.35;}
h1 {font-size: 16pt; margin: 0 0 2pt 0;}
h2 {font-size: 11.5pt; margin: 14pt 0 5pt 0; padding-bottom: 2pt; border-bottom: 1px solid #c4c7cc;}
p {margin: 3pt 0;}
.sub, .note {color: #5f6368; font-size: 8pt;}
table {border-collapse: collapse; width: 100%; margin: 3pt 0 6pt 0;}
th, td {border: 1px solid #dadce0; padding: 2pt 4pt; vertical-align: top; text-align: left;}
th {background-color: #f1f3f4; font-weight: bold;}
table.finding th {font-weight: normal; color: #5f6368; background-color: #fafafa;}
table.finding {margin-bottom: 8pt;}
code {font-family: monospace; font-size: 8pt;}
"""


def _page(title: str, body: str) -> str:
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{_e(title)}</title><style>{CSS}"
            "body{max-width:1000px;margin:24px auto;padding:0 16px}</style></head><body>" + body + "</body></html>")


# ------------------------------------------------------------------ PDF
FONTS = [  # first one found is used for the PDF (needs Vietnamese letters)
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", None),
]


def to_pdf(html_doc: str, path: Path, out_dir: Path, footer: str) -> Path:
    """Lay the report HTML out on A4 pages (MuPDF Story), with a footer 'page n / N' on every page."""
    import pymupdf
    body = html_doc.split("<body>", 1)[-1].rsplit("</body>", 1)[0]
    font_css, arch = "", pymupdf.Archive(str(out_dir))
    for reg, bold in FONTS:
        if Path(reg).exists():
            arch.add(pymupdf.Archive(str(Path(reg).parent)))
            font_css = f"@font-face {{font-family: ldv; src: url({Path(reg).name});}}"
            if bold and Path(bold).exists():
                font_css += f"@font-face {{font-family: ldv; src: url({Path(bold).name}); font-weight: bold;}}"
            break
    story = pymupdf.Story(html=body, user_css=font_css + CSS, archive=arch)
    buf = io.BytesIO()
    w = pymupdf.DocumentWriter(buf)
    page, where = pymupdf.paper_rect("a4"), pymupdf.paper_rect("a4") + (40, 40, -40, -50)
    more = 1
    while more:
        dev = w.begin_page(page)
        more, _ = story.place(where)
        story.draw(dev)
        w.end_page()
    w.close()
    doc = pymupdf.open("pdf", buf.getvalue())
    for i, pg in enumerate(doc, 1):
        pg.insert_text((40, page.height - 25), f"{footer} · {i} / {doc.page_count}", fontsize=7, color=(0.4, 0.4, 0.4))
    doc.set_metadata({"title": footer, "creator": "LDV", "producer": "LDV"})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


# ------------------------------------------------------------------ Excel
def to_xlsx(s: dict, marks: dict, trails: dict, cmp: dict | None, signoff: dict | None, opts: dict, path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    L = _L(opts.get("lang", "en"))
    rev = s.get("revision") or 1
    st = lambda f: marks.get(f["sig"], {}).get("status", "open")
    head = lambda ws: [setattr(c, "font", Font(bold=True, color="FFFFFF")) or
                       setattr(c, "fill", PatternFill("solid", fgColor="34495E")) for c in ws[1]]
    wrap = Alignment(wrap_text=True, vertical="top")
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    key, _, n_err, n_warn = outcome(s, marks)
    so = signoff
    rows = [(L("title"), ""), (L("review_id"), f"{s['shipment']}-R{rev}"), (L("shipment"), s["shipment"]),
            (L("package"), s.get("name", "")), (L("checked"), _ts(s.get("check_ts") or s.get("created"))),
            (L("generated"), _ts(datetime.now().isoformat(timespec="seconds"))), (L("n_docs"), len(s["docs"])),
            (L("auto"), L(key, n=n_err or n_warn or len(s.get("unrecognised", [])))),
            (L("human"), L("so_" + so["result"]) if so else L("so_none"))]
    if so:
        rows += [("", L("so_by", who=so.get("who") or "—", ts=_ts(so["ts"]))), (L("reason"), so.get("note") or "")]
    rows += [(L.sev(x), sum(f["severity"] == x for f in s["findings"])) for x in SEVERITY]
    for r in rows:
        ws.append(list(r))
    ws["A1"].font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 34, 80

    ws = wb.create_sheet("Documents")
    ws.append([L("file"), L("type"), L("pages"), L("findings")])
    head(ws)
    for d in s["docs"]:
        ws.append([d["name"], L.kind(d["kind"], d.get("form", "")), d.get("pages"), sum(d["name"] in wrong_docs(f) for f in s["findings"])])
    for col, w in zip("ABCD", (50, 36, 8, 10)):
        ws.column_dimensions[col].width = w

    ws = wb.create_sheet("Findings")
    ws.append([L("id"), L("severity"), "Message (EN)", "Nội dung (VI)", L("doc"), L("page"), L("found"), L("expected"),
               L("ref_doc"), L("action"), L("rule"), L("rev_status"), L("rev_note"), L("trail")])
    head(ws)
    for f in s["findings"]:
        if not opts.get("info") and f["severity"] == "INFO" or opts.get("only_open") and st(f) not in OPEN:
            continue
        m = marks.get(f["sig"], {})
        tr = "\n".join(f"{_ts(e['ts'])} {e.get('who') or ''}: {L.status(e['old_status'])} → {L.status(e['status'])}"
                       + (f" “{e['note']}”" if e.get("note") else "") for e in trails.get(f["sig"], []))
        ws.append([finding_id(s["shipment"], rev, f["no"]), f["severity"], f.get("msg_en"), f.get("msg_vi"), "\n".join(wrong_docs(f)),
                   f.get("page"), f.get("current"), f.get("suggested"), ", ".join(ref_docs(f)),
                   L.note(f).replace("<br>", "\n"), f["key"], L.status(m.get("status", "open")), m.get("note", ""), tr])
        row = ws[ws.max_row]
        for c in row:
            c.alignment = wrap
        row[1].fill = PatternFill("solid", fgColor=TINT[f["severity"]].lstrip("#"))
    for col, w in zip("ABCDEFGHIJKLMN", (22, 9, 45, 45, 34, 6, 20, 20, 30, 40, 18, 18, 30, 40)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "B2"

    if cmp and cmp["rows"]:
        ws = wb.create_sheet("Cross-check")
        ws.append([L("field")] + [L.pick(c["en"], c["vi"]) for c in cmp["columns"]] + [L("result")])
        head(ws)
        for r in cmp["rows"]:
            cells = [r["cells"][c["id"]] for c in cmp["columns"]]
            ws.append([L.pick(r["en"], r["vi"])] + [
                (f'{c.get("label", "")}: {L("blank")}' if c["state"] == "blank" else
                 {"value": c.get("show", ""), "missing": L("not_read"), "na": "", "nodoc": L("nodoc")}[c["state"]])
                for c in cells] + [L("cmp_" + r["result"])])
            row = ws[ws.max_row]
            for i, c in enumerate(cells, 1):
                if c.get("odd"):
                    row[i].fill = PatternFill("solid", fgColor="FCE8E6")
                elif c["state"] == "blank":
                    row[i].font = Font(color=COLOR["WARNING"].lstrip("#"), bold=True)
        for i in range(len(cmp["columns"]) + 2):
            ws.column_dimensions[chr(65 + i)].width = 26
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ------------------------------------------------------------------ one call for the UI
def gather(s: dict, hist, check_id: int | None) -> dict:
    """Reviewer decisions, their trails, the cross-check and the latest sign-off for a stored review."""
    from .compare import compare
    marks = hist.marks(s["shipment"])
    trails = {f["sig"]: list(reversed(hist.log(s["shipment"], f["sig"]))) for f in s["findings"]}
    cmp = compare(s) if any(d.get("fields") for d in s["docs"]) else None
    so = (hist.signoffs(check_id) or [None])[0] if check_id else None
    return dict(marks=marks, trails=trails, cmp=cmp, signoff=so)


def generate(s: dict, hist, check_id: int | None, opts: dict, fmt: str) -> Path:
    """Write the report (fmt: pdf | xlsx | html) to <report folder>/reports/ and return its path."""
    g = gather(s, hist, check_id)
    out_dir = Path(s["out_dir"])
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / "reports" / f"LDV_review_{s['shipment']}_R{s.get('revision') or 1}_{opts.get('lang', 'en')}_{stamp}.{fmt}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "xlsx":
        return to_xlsx(s, g["marks"], g["trails"], g["cmp"], g["signoff"], opts, path)
    doc = build_html(s, g["marks"], g["trails"], g["cmp"], g["signoff"], opts,
                     images="relative" if fmt == "pdf" else "base64")
    if fmt == "pdf":
        return to_pdf(doc, path, out_dir, f"LDV · {s['shipment']}-R{s.get('revision') or 1} · {stamp}")
    path.write_text(doc, encoding="utf-8")
    return path


def history(s: dict) -> list[Path]:
    """Reports generated earlier for this review, newest first."""
    d = Path(s.get("out_dir") or "") / "reports"
    return sorted((p for p in d.glob("LDV_review_*") if p.suffix in (".pdf", ".xlsx", ".html")),
                  key=lambda p: p.stat().st_mtime, reverse=True) if d.exists() else []
