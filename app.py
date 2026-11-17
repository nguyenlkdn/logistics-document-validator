"""LDV - Logistics Document Validator: local web app (report only, documents are never modified).

Run:  Start.bat   (or: python -m streamlit run app.py)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import check, report_root                 # noqa: E402
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
    "version": ("Version", "Phiên bản"),
}
_vf = Path(__file__).resolve().parent / "VERSION"
VERSION = _vf.read_text(encoding="utf-8").strip() if _vf.exists() else "dev"

with st.sidebar:
    lang_choice = st.radio(T["lang"][0], ["English", "Tiếng Việt", "Both / Cả hai"], index=2)
    langs = {"English": ["en"], "Tiếng Việt": ["vi"]}.get(lang_choice, ["en", "vi"])
    L = 0 if langs[0] == "en" else 1


def t(key):
    pair = T[key]
    return pair[L] if len(langs) == 1 else f"{pair[0]} / {pair[1]}"


def sev_label(s):
    return " / ".join(CONFIG["severity"][s][l] for l in langs)


with st.sidebar:
    show = st.multiselect(t("filter"), SEVERITY, default=SEVERITY, format_func=lambda s: f"{ICON[s]} {sev_label(s)}")
    st.caption(f"{t('saved')}:\n\n`{report_root()}`")
    st.caption(f"{t('version')} {VERSION}")

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
    rows = per_file(res)
    st.dataframe([{t("file_col"): r["file"], **{f"{ICON[s]} {sev_label(s)}": r[s] for s in SEVERITY},
                   t("total"): r["total"]} for r in rows], hide_index=True, width="stretch")

    c1, c2, _ = st.columns([2, 2, 3])
    c1.download_button(f"⬇️ {t('download')}", res.excel.read_bytes(), file_name=f"{res.name}_report.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if sys.platform.startswith("win") and c2.button(f"📂 {t('open')}"):
        os.startfile(res.out_dir)                       # noqa: S606 — local folder on the user's PC
    elif sys.platform == "darwin" and c2.button(f"📂 {t('open')}"):
        subprocess.run(["open", res.out_dir])
    st.caption(f"{t('saved')}: `{res.out_dir}`")

    # ---- findings
    names = [r["file"] for r in rows]
    pick = st.selectbox(t("file_filter"), [None] + names,
                        format_func=lambda n: t("all_files") if n is None else
                        f"{n}  ({next(r['total'] for r in rows if r['file'] == n)})")
    shown = [(i, f) for i, f in enumerate(res.findings, 1)
             if f.severity in show and (pick is None or f.doc_names[0] == pick)]
    if not res.findings:
        st.success(t("none"))
    st.caption(t("legend"))
    for i, f in shown:
        msg = " — ".join(f.text(l) for l in langs)
        with st.expander(f"{ICON[f.severity]} **#{i}** {msg}", expanded=f.severity == "ERROR"):
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
            for p in f.evidence:
                st.image(str(p), width="stretch")

    # ---- not recognised
    st.subheader(f"⚪ {t('unrec')}")
    if res.unrecognised:
        for u in res.unrecognised:
            st.warning(f"{u['doc']}: " + " / ".join(u["what" if l == "en" else "vi"] for l in langs))
    else:
        st.success(t("all_ok"))
