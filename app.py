"""LDV - Logistics Document Validator: local web app (report only, documents are never modified).

Run:  Start.bat   (or: python -m streamlit run app.py)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import check, report_root                 # noqa: E402
from engine import master                           # noqa: E402
from engine.history import STATUSES, History        # noqa: E402
from engine.report import ICON, per_file                        # noqa: E402
from engine.rules import CONFIG, SEVERITY              # noqa: E402

st.set_page_config(page_title="LDV - Logistics Document Validator", page_icon="📦", layout="wide")

T = {
    "title": ("LDV - Logistics Document Validator", "LDV - Kiểm tra bộ chứng từ xuất nhập khẩu"),
    "intro": ("Upload ONE shipment: a .zip, or the PDF files. Documents are only read, never changed.",
              "Tải lên MỘT lô hàng: file .zip hoặc các file PDF. Chứng từ chỉ được đọc, không bị sửa."),
    "upload": ("Shipment documents (.zip or .pdf)", "Bộ chứng từ (.zip hoặc .pdf)"),
    "check": ("Check documents", "Kiểm tra"),
    "one_zip": ("Please upload one shipment at a time (one .zip).", "Vui lòng tải lên từng lô hàng (một file .zip)."),
    "running": ("Checking…", "Đang kiểm tra…"),
    "docs": ("Documents found", "Chứng từ đã nhận diện"),
    "findings": ("Findings", "Kết quả kiểm tra"),
    "none": ("No issues found.", "Không phát hiện lỗi."),
    "current": ("Current", "Hiện tại"),
    "suggested": ("Suggested", "Đề xuất"),
    "doc": ("Document", "Chứng từ"),
    "page": ("page", "trang"),
    "note": ("Note", "Ghi chú"),
    "unrec": ("Not recognised", "Không đọc được"),
    "all_ok": ("Everything recognised.", "Đã đọc được toàn bộ."),
    "download": ("Download Excel report", "Tải báo cáo Excel"),
    "saved": ("Report saved in", "Báo cáo đã lưu tại"),
    "open": ("Open report folder", "Mở thư mục báo cáo"),
    "lang": ("Language / Ngôn ngữ", "Language / Ngôn ngữ"),
    "filter": ("Show severity", "Hiển thị mức độ"),
    "evidence": ("Screenshots", "Ảnh minh họa"),
    "legend": ("Red box = value to check · Green box = reference value",
               "Khung đỏ = giá trị cần kiểm tra · Khung xanh = giá trị tham chiếu"),
    "not_draft": ("not marked DRAFT", "không có chữ DRAFT"),
    "by_file": ("Findings by file", "Lỗi theo từng file"),
    "file_col": ("File", "Tên file"),
    "total": ("Total", "Tổng"),
    "file_filter": ("Show file", "Hiển thị file"),
    "all_files": ("All files", "Tất cả file"),
    "click_file": ("Click a file to show only its findings and preview the document. Click it again to show all files.",
                   "Bấm vào một file để xem lỗi của file đó và xem trước chứng từ. Bấm lại để xem tất cả."),
    "preview": ("Document preview", "Xem trước chứng từ"),
    "pages": ("pages", "trang"),
    "boxes": ("Boxes on the page: red = Error, orange = Warning, yellow = Minor, blue = Info; #n = finding number below",
              "Khung trên trang: đỏ = Lỗi, cam = Cảnh báo, vàng = Lỗi nhỏ, xanh dương = Thông tin; #n = số thứ tự lỗi bên dưới"),
    "in_preview": ("Highlighted as #{n} in the document preview above", "Được đánh dấu #{n} trong phần xem trước ở trên"),
    "showing": ("Showing findings of", "Đang hiển thị lỗi của"),
    "version": ("Version", "Phiên bản"),
    "hs_master": ("HS master list", "Danh mục mã HS"),
    "hs_none": ("No HS master list yet: HS codes are only compared between documents.",
                "Chưa có danh mục mã HS: mã HS chỉ được so sánh giữa các chứng từ."),
    "hs_status": ("{n} models · imported {when}", "{n} model · nhập lúc {when}"),
    "hs_from": ("From", "Từ file"),
    "hs_missing": ("The Excel file is not found at this path any more; the last import is used.",
                   "Không còn thấy file Excel ở đường dẫn này; đang dùng lần nhập gần nhất."),
    "hs_auto": ("Edit the Excel any time: LDV re-imports it automatically before the next check.",
                "Có thể sửa file Excel bất cứ lúc nào: LDV tự nhập lại trước lần kiểm tra sau."),
    "hs_path": ("Excel file path", "Đường dẫn file Excel"),
    "hs_import": ("Import", "Nhập"),
    "hs_done": ("Imported {n} models: {a} added, {r} removed, {c} changed", "Đã nhập {n} model: thêm {a}, bỏ {r}, đổi {c}"),
    "hs_skipped": ("Skipped rows", "Dòng bị bỏ qua"),
    "from_menu": ("Checked from right-click menu", "Kiểm tra từ menu chuột phải"),
    "nav": ("Page", "Trang"),
    "pg_check": ("🔎 Check", "Kiểm tra"),
    "pg_hist": ("🗂️ History", "Lịch sử"),
    "st_open": ("Open", "Chưa xử lý"),
    "st_fixed": ("✔ Fixed", "✔ Đã sửa"),
    "st_not_error": ("✗ Not an error", "✗ Không phải lỗi"),
    "st_waiting": ("⏳ Waiting for supplier", "⏳ Chờ NCC sửa"),
    "status": ("Status", "Trạng thái"),
    "note_in": ("Note", "Ghi chú"),
    "rev": ("Revision", "Lần"),
    "rev_info": ("Revision {rev} of {ship}: {res} fixed since revision {prev}, {still} still there, {new} new",
                 "Lần {rev} của {ship}: {res} lỗi đã sửa so với lần {prev}, {still} lỗi còn lại, {new} lỗi mới"),
    "resolved": ("Fixed since previous revision", "Đã sửa so với lần trước"),
    "no_hist": ("No checks yet.", "Chưa có lần kiểm tra nào."),
    "hist_pick": ("Select a row to see its findings and set their status.",
                  "Chọn một dòng để xem lỗi và cập nhật trạng thái."),
    "export": ("Download feedback Excel (all findings + status)", "Tải Excel phản hồi (tất cả lỗi + trạng thái)"),
    "date": ("Checked", "Ngày kiểm tra"),
    "shipment": ("Shipment", "Lô hàng"),
    "open_cnt": ("Still open", "Còn mở"),
    "files": ("Files", "File"),
    "saved_marks": ("Saved", "Đã lưu"),
}
_vf = Path(__file__).resolve().parent / "VERSION"
VERSION = _vf.read_text(encoding="utf-8").strip() if _vf.exists() else "dev"

HIST = History(report_root() / "history.db")

with st.sidebar:
    lang_choice = st.radio(T["lang"][0], ["English", "Tiếng Việt", "Both / Cả hai"], index=0)
    langs = {"English": ["en"], "Tiếng Việt": ["vi"]}.get(lang_choice, ["en", "vi"])
    L = 0 if langs[0] == "en" else 1


def t(key):
    pair = T[key]
    return pair[L] if len(langs) == 1 else f"{pair[0]} / {pair[1]}"


def sev_label(s):
    return " / ".join(CONFIG["severity"][s][l] for l in langs)


with st.sidebar:
    page = st.radio(t("nav"), ["check", "history"], format_func=lambda k: t("pg_check" if k == "check" else "pg_hist"),
                    horizontal=True, key="page")
    show = st.multiselect(t("filter"), SEVERITY, default=SEVERITY, format_func=lambda s: f"{ICON[s]} {sev_label(s)}")
    st.caption(f"{t('saved')}:\n\n`{report_root()}`")
    with st.expander(f"📋 {t('hs_master')}"):
        try:
            done = master.refresh()
        except Exception:
            done = None
        hs = master.status()
        done = done or st.session_state.pop("hs_done", None)
        if done:
            st.success(t("hs_done").format(n=done["count"], a=len(done["added"]), r=len(done["removed"]), c=len(done["changed"])))
        if hs["loaded"]:
            st.markdown(t("hs_status").format(n=hs["count"], when=hs["imported_at"].replace("T", " ")))
            st.caption(f"{t('hs_from')}: `{hs['source']}`")
            if not hs["source_found"]:
                st.warning(t("hs_missing"))
            if hs["skipped"]:
                st.caption(f"{t('hs_skipped')}: " + ", ".join(str(x["row"]) for x in hs["skipped"]))
            st.caption(t("hs_auto"))
        else:
            st.info(t("hs_none"))
        path = st.text_input(t("hs_path"), value=hs.get("source", ""), key="hs_path")
        if st.button(t("hs_import"), key="hs_import") and path.strip():
            try:
                st.session_state["hs_done"] = master.import_xlsx(Path(path.strip().strip('"')))
            except Exception as e:                          # wrong path, not an Excel, no header row
                st.error(str(e))
            else:
                st.rerun()                                  # show the new status above
    st.caption(f"{t('version')} {VERSION}")

@st.cache_data(show_spinner=False, max_entries=20)
def page_images(path: str, mtime: float, marks: tuple) -> list[bytes]:
    """PNG of every page of a PDF with the findings boxed in their severity colour (cached)."""
    from engine.evidence import annotated_pages
    return annotated_pages(path, marks)


def status_label(k):
    return t(f"st_{k}")


def history_page():
    st.title(t("pg_hist"))
    rows = HIST.checks()
    if not rows:
        st.info(t("no_hist"))
        return
    tmp = Path(tempfile.gettempdir()) / "LDV_feedback.xlsx"
    st.download_button(f"⬇️ {t('export')}", HIST.export(tmp).read_bytes(), file_name="LDV_feedback.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.caption(t("hist_pick"))
    table = [{t("date"): r["ts"].replace("T", " "), t("shipment"): r["shipment"], t("rev"): r["revision"],
              f"{ICON['ERROR']} {sev_label('ERROR')}": r["n_error"], f"{ICON['WARNING']} {sev_label('WARNING')}": r["n_warning"],
              t("open_cnt"): r["n_open"], t("files"): ", ".join(json.loads(r["files"]))} for r in rows]
    ev = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                      key="hist_table")
    sel = ev.selection.rows if ev and ev.selection else []
    if not sel:
        return
    c = rows[sel[0]]
    st.subheader(f"{c['shipment']} — {t('rev')} {c['revision']}")
    if c["out_dir"] and Path(c["out_dir"]).exists():
        st.caption(f"{t('saved')}: `{c['out_dir']}`")
        if sys.platform.startswith("win") and st.button(f"📂 {t('open')}", key="hist_open"):
            os.startfile(c["out_dir"])                  # noqa: S606 — local folder on the user's PC
    revision_banner(c["id"])
    fs = HIST.findings(c["id"])
    if not fs:
        st.success(t("none"))
        return
    import pandas as pd
    msg = "msg_en" if L == 0 else "msg_vi"
    df = pd.DataFrame([{"no": f["no"], "sev": ICON[f["severity"]], "doc": f["doc"], "msg": f[msg],
                        "cur": f["current"], "sug": f["suggested"], "status": status_label(f["status"]),
                        "note": f["note"]} for f in fs])
    edited = st.data_editor(df, hide_index=True, width="stretch", key=f"ed_{c['id']}",
                            column_order=["no", "sev", "status", "note", "msg", "cur", "sug", "doc"],
                            disabled=["no", "sev", "doc", "msg", "cur", "sug"],
                            column_config={
                                "no": st.column_config.NumberColumn("#", width=40), "sev": st.column_config.TextColumn("", width=40),
                                "doc": t("doc"), "msg": st.column_config.TextColumn(t("findings"), width="large"),
                                "cur": t("current"), "sug": t("suggested"),
                                "status": st.column_config.SelectboxColumn(t("status"), options=[status_label(k) for k in STATUSES],
                                                                           required=True, width="medium"),
                                "note": st.column_config.TextColumn(t("note_in"), width="medium")})
    back = {status_label(k): k for k in STATUSES}
    changed = 0
    for f, (_, row) in zip(fs, edited.iterrows()):
        stt, note = back[row["status"]], row["note"] or ""
        if (stt, note) != (f["status"], f["note"]):
            HIST.set_mark(c["shipment"], f["sig"], stt, note)
            changed += 1
    if changed:
        st.toast(t("saved_marks"))


def revision_banner(cid):
    cmp = HIST.compare(cid)
    if not cmp:
        return
    c = HIST.check(cid)
    st.info(t("rev_info").format(rev=c["revision"], ship=c["shipment"], prev=cmp["prev_revision"],
                                 res=len(cmp["resolved"]), still=len(cmp["still"]), new=len(cmp["new"])))
    if cmp["resolved"]:
        with st.expander(f"✔ {t('resolved')} ({len(cmp['resolved'])})"):
            for f in cmp["resolved"]:
                st.markdown(f"- ~~{f['msg_en' if L == 0 else 'msg_vi']}~~ — {f['doc']}")


if page == "history":
    history_page()
    st.stop()

st.title(f"📦 {t('title')}")
st.write(t("intro"))

files = st.file_uploader(t("upload"), type=["zip", "pdf", "jpg", "jpeg", "png"], accept_multiple_files=True)
if st.button(t("check"), type="primary", disabled=not files):
    zips = [f for f in files if f.name.lower().endswith(".zip")]
    if len(zips) > 1 or (zips and len(files) > 1):
        st.error(t("one_zip"))
    else:
        with st.spinner(t("running")), tempfile.TemporaryDirectory() as tmp:
            paths = []
            for f in files:
                p = Path(tmp) / Path(f.name).name
                p.write_bytes(f.getvalue())
                paths.append(p)
            name = Path(zips[0].name).stem if zips else None
            st.session_state["result"] = check(paths, name=name)
            st.session_state["check_id"] = HIST.record(st.session_state["result"], VERSION)
            st.session_state.pop("job_files", None)

# ---- right-click "Send to > LDV Checker": ldv_open.py leaves the selected paths in a job file
job = st.query_params.get("job", "")
if re.fullmatch(r"[0-9a-f]{32}", job) and st.session_state.get("job_done") != job:
    st.session_state["job_done"] = job
    jf = Path(tempfile.gettempdir()) / "ldv_jobs" / f"{job}.json"
    if jf.exists():
        paths = [Path(p) for p in json.loads(jf.read_text(encoding="utf-8"))["paths"]]
        jf.unlink(missing_ok=True)
        zips = [p for p in paths if p.suffix.lower() == ".zip"]
        if len(zips) > 1 or (zips and len(paths) > 1):
            st.error(t("one_zip"))
        else:
            one = paths[0] if len(paths) == 1 and (paths[0].is_dir() or zips) else None
            with st.spinner(t("running")):
                st.session_state["result"] = check(paths, name=one.stem if one else None)
            st.session_state["check_id"] = HIST.record(st.session_state["result"], VERSION)
            st.session_state["job_files"] = [p.name for p in paths]
    st.query_params.clear()
if st.session_state.get("job_files") and st.session_state.get("result"):
    st.info(f"🖱️ {t('from_menu')}: " + ", ".join(st.session_state["job_files"]))

res = st.session_state.get("result")
if res:
    # ---- documents
    st.subheader(f"📄 {t('docs')}")
    for d in res.docs:
        kind = " / ".join(CONFIG["doc_kinds"][d.kind][l] for l in langs)
        flag = "" if d.is_draft or d.kind in ("CI", "SC") else f"  ⚠️ _{t('not_draft')}_"
        st.markdown(f"- **{kind}** — {d.name}{flag}")

    # ---- summary
    st.subheader(f"🔎 {t('findings')}")
    cols = st.columns(4)
    for c, s in zip(cols, SEVERITY):
        c.metric(f"{ICON[s]} {sev_label(s)}", sum(f.severity == s for f in res.findings))

    st.markdown(f"**{t('by_file')}**")
    st.caption(t("click_file"))
    rows = per_file(res)
    ev = st.dataframe([{t("file_col"): r["file"], **{f"{ICON[s]} {sev_label(s)}": r[s] for s in SEVERITY},
                        t("total"): r["total"]} for r in rows], hide_index=True, width="stretch",
                      on_select="rerun", selection_mode="single-row", key=f"pf_{st.session_state.get('check_id')}")
    picked = rows[ev.selection.rows[0]]["file"] if ev and ev.selection and ev.selection.rows else None
    if picked and res.doc_files.get(picked) and Path(res.doc_files[picked]).exists():
        pdf = Path(res.doc_files[picked])
        mk = tuple(m for m in res.marks.get(picked, []) if m[5] in show)
        imgs = page_images(str(pdf), pdf.stat().st_mtime, mk)
        with st.expander(f"📄 {t('preview')}: {picked} ({len(imgs)} {t('pages') if len(imgs) > 1 else t('page')})", expanded=True):
            st.caption(t("boxes"))
            for n, png in enumerate(imgs, 1):
                st.image(png, caption=f"{t('page')} {n}", width="stretch")

    c1, c2, _ = st.columns([2, 2, 3])
    c1.download_button(f"⬇️ {t('download')}", res.excel.read_bytes(), file_name=f"{res.name}_report.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if sys.platform.startswith("win") and c2.button(f"📂 {t('open')}"):
        os.startfile(res.out_dir)                       # noqa: S606 — local folder on the user's PC
    elif sys.platform == "darwin" and c2.button(f"📂 {t('open')}"):
        subprocess.run(["open", res.out_dir])
    st.caption(f"{t('saved')}: `{res.out_dir}`")

    # ---- findings
    cid = st.session_state.get("check_id")
    if cid:
        revision_banner(cid)
    marks = {f["sig"]: f for f in HIST.findings(cid)} if cid else {}
    ship = History.shipment_of(res)
    sigs = History.sigs(res.findings)
    pick = picked
    if pick:
        st.info(f"{t('showing')}: **{pick}**")
    shown = [(i, f) for i, f in enumerate(res.findings, 1)
             if f.severity in show and (pick is None or f.doc_names[0] == pick)]
    if not res.findings:
        st.success(t("none"))
    st.caption(t("legend"))
    for i, f in shown:
        msg = " — ".join(f.text(l) for l in langs)
        sig = sigs[i - 1]
        mk = marks.get(sig, {"status": "open", "note": ""})
        badge = "" if mk["status"] == "open" else f"{status_label(mk['status'])} · "
        title = f"{ICON[f.severity]} **#{i}** {badge}{msg}"
        if mk["status"] in ("fixed", "not_error"):
            title = f"{ICON[f.severity]} **#{i}** {badge}~~{msg}~~"
        with st.expander(title, expanded=f.severity == "ERROR" and mk["status"] in ("open", "waiting")):
            if cid:
                s1, s2 = st.columns([1, 2])
                new_st = s1.selectbox(t("status"), STATUSES, index=STATUSES.index(mk["status"]),
                                      format_func=status_label, key=f"st_{cid}_{i}_{sig}")
                new_note = s2.text_input(t("note_in"), value=mk["note"], key=f"nt_{cid}_{i}_{sig}")
                if (new_st, new_note) != (mk["status"], mk["note"]):
                    HIST.set_mark(ship, sig, new_st, new_note)
                    st.rerun()
            a, b = st.columns([3, 2])
            with a:
                pg = f" ({t('page')} {f.page})" if f.page else ""
                st.markdown(f"**{t('doc')}:** {f.doc_names[0]}{pg}")
                if len(f.doc_names) > 1:
                    st.markdown(" · ".join(f"_{n}_" for n in f.doc_names[1:]))
                if f.current or f.suggested:
                    st.markdown(f"**{t('current')}:** `{f.current}`  \n**{t('suggested')}:** `{f.suggested}`")
            with b:
                notes = [f.note(l) for l in langs if f.note(l)]
                if notes:
                    st.info(f"**{t('note')}:** " + "  \n".join(notes))
            if pick:                                    # file view: boxed on the full page above instead
                st.caption("🖍️ " + t("in_preview").format(n=i))
            else:
                for p in f.evidence:
                    st.image(str(p), width="stretch")

    # ---- not recognised
    st.subheader(f"⚪ {t('unrec')}")
    if res.unrecognised:
        for u in res.unrecognised:
            st.warning(f"{u['doc']}: " + " / ".join(u["what" if l == "en" else "vi"] for l in langs))
    else:
        st.success(t("all_ok"))
