"""New review: upload one shipment, see what LDV recognised in each file, then start the analysis."""
import hashlib
import io
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import streamlit as st

from .. import components as ui
from .. import state
from ..i18n import kind_label, t, t1

KINDS = ("CI", "SC", "BL", "CO")


@st.cache_data(show_spinner=False, max_entries=128)
def probe_pdf(data: bytes) -> dict:
    """Same classification as the analysis (engine.extract.classify), read-only and in memory."""
    import pymupdf
    from engine.extract import classify
    from engine.pdftext import doc_lines
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            kind = classify("\n".join(l.text for l in doc_lines(pdf)))
            return dict(kind=kind, pages=pdf.page_count)
    except Exception:
        return dict(kind=None, pages=None, broken=True)


def _junk(name: str) -> bool:
    p = PurePosixPath(name)
    return p.name.startswith(".") or p.name.lower() == "thumbs.db" or "__MACOSX" in p.parts


def inventory(files) -> tuple[list[dict], list[str]]:
    """One row per document (zip members expanded) + blocking errors."""
    rows, errors, seen = [], [], {}
    zips = [f for f in files if f.name.lower().endswith(".zip")]
    if len(zips) > 1 or (zips and len(files) > 1):
        errors.append(t("one_zip"))

    def add(name, data, inside=""):
        h = hashlib.sha1(data).hexdigest()
        row = dict(name=name, inside=inside, size=len(data), kind=None, pages=None)
        if not name.lower().endswith(".pdf"):
            row["status"], row["level"] = t1("ok_notpdf"), "warn"
        else:
            p = probe_pdf(data)
            row.update(kind=p["kind"], pages=p["pages"])
            if p.get("broken"):
                row["status"], row["level"] = t1("ok_broken"), "error"
            elif h in seen:
                row["status"], row["level"] = t1("ok_dup", name=seen[h]), "warn"
            elif not p["kind"]:
                row["status"], row["level"] = t1("ok_unrec"), "warn"
            else:
                row["status"], row["level"] = t1("ok_ready"), "ok"
            seen.setdefault(h, name)
        rows.append(row)

    for f in files:
        data = f.getvalue()
        if f.name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for m in z.infolist():
                        if not m.is_dir() and not _junk(m.filename):
                            add(PurePosixPath(m.filename).name, z.read(m), f.name)
            except zipfile.BadZipFile:
                errors.append(t("bad_zip", name=f.name))
        else:
            add(f.name, data)
    return rows, errors


def render():
    ui.header(t("new_title"), ui.esc(t("new_intro")))
    ui.stepper(None)
    files = st.file_uploader(t("upload"), type=["zip", "pdf", "jpg", "jpeg", "png"], accept_multiple_files=True,
                             help=t("upload_help"), key="uploader")
    st.caption(t("upload_help"))
    if not files:
        return
    rows, errors = inventory(files)
    for e in errors:
        st.error(e, icon=":material/block:")

    st.subheader(t("inventory"))
    mark = {"ok": "✅", "warn": "⚠️", "error": "⛔"}
    has_zip = any(r["inside"] for r in rows)
    none = "—"
    labels = {kind_label(k): k for k in KINDS}
    import pandas as pd
    df = pd.DataFrame([{"file": r["name"], "in": r["inside"], "type": kind_label(r["kind"]) if r["kind"] else none,
                        "pages": r["pages"], "size": ui.size_txt(r["size"]),
                        "status": f"{mark[r['level']]} {r['status']}"} for r in rows])
    sig = hashlib.sha1("|".join(f"{f.name}:{f.size}" for f in files).encode()).hexdigest()[:10]
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key=f"inv_{sig}",
        disabled=["file", "in", "pages", "size", "status"],
        column_order=["file"] + (["in"] if has_zip else []) + ["type", "pages", "size", "status"],
        column_config={"file": st.column_config.TextColumn(t1("col_file"), width="large"),
                       "in": t1("col_in"),
                       "type": st.column_config.SelectboxColumn(t1("col_type"), options=[none, *labels], required=True,
                                                                help=t1("type_help")),
                       "pages": t1("col_pages"), "size": t1("col_size"),
                       "status": st.column_config.TextColumn(t1("col_status"), width="large")})
    st.caption(t("inv_hint") + " " + t("type_hint"))
    kinds = {}
    for r, (_, e) in zip(rows, edited.iterrows()):
        chosen = labels.get(e["type"])
        if r["name"].lower().endswith(".pdf") and r["level"] != "error" and chosen and chosen != r["kind"]:
            kinds[r["name"]] = chosen
            r["kind"], r["level"] = chosen, "ok"
    if kinds:
        st.info(t("type_changed", files=", ".join(kinds)), icon=":material/edit:")
    found = {r["kind"] for r in rows if r["level"] == "ok"}
    for k in KINDS:
        if k not in found:
            st.warning(t("missing_kind", kind=kind_label(k)), icon=":material/help:")

    ready = [r for r in rows if r["level"] == "ok"]
    if st.button(t1("start"), type="primary", icon=":material/play_arrow:", disabled=bool(errors) or not ready):
        with st.status(t("running", n=len(rows)), expanded=False) as box, tempfile.TemporaryDirectory() as tmp:
            paths = []
            for f in files:
                p = Path(tmp) / Path(f.name).name
                p.write_bytes(f.getvalue())
                paths.append(p)
            zips = [f for f in files if f.name.lower().endswith(".zip")]
            state.run_check(paths, name=Path(zips[0].name).stem if zips else None, kinds=kinds)
            st.session_state.pop("job_files", None)
            box.update(label=t("run_done"), state="complete")
        state.go("dashboard")
