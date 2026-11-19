"""Reference data: the HS master list (company Excel). Preview and validate before replacing the current list."""
from pathlib import Path

import streamlit as st

from engine import master

from .. import components as ui
from ..i18n import t, t1


def render():
    ui.header(t("ref_title"))
    st.subheader(t("hs_master"))
    st.caption(t("hs_intro"))
    try:
        done = master.refresh()                       # the Excel may have been saved since the last import
    except Exception:
        done = None
    done = done or st.session_state.pop("hs_done", None)
    if done:
        st.success(t("hs_done", n=done["count"], a=len(done["added"]), r=len(done["removed"]), c=len(done["changed"])))
    hs = master.status()

    if hs["loaded"]:
        ui.stats([(t1("hs_models"), hs["count"]), (t1("hs_imported"), hs["imported_at"].replace("T", " ")),
                  (t1("hs_skipped_n"), len(hs["skipped"]))])
        st.markdown(f"**{t1('hs_source')}:** `{hs['source']}`")
        if not hs["source_found"]:
            st.warning(t("hs_missing"))
        st.caption(t("hs_auto"))
    else:
        st.info(t("hs_none"))

    # ---- import with preview
    st.write("")
    with st.container(border=True):
        st.session_state.setdefault("hs_path", hs.get("source", ""))
        path = st.text_input(t("hs_path"), key="hs_path").strip().strip('"')
        with st.container(horizontal=True):
            st.button(t1("hs_browse_btn"), icon=":material/folder_open:", on_click=_browse, args=(path,),
                      help=t1("hs_browse_help"))
            if st.button(t1("hs_preview_btn"), icon=":material/preview:", disabled=not path):
                st.session_state["hs_preview_path"] = path
        if st.session_state.get("hs_pick_failed"):           # no file dialog on this PC: upload a copy instead
            st.caption(t("hs_upload_note"))
            up = st.file_uploader(t1("hs_upload"), type=["xlsx", "xlsm"], key="hs_upload")
            if up is not None:
                dest = master.data_dir() / "uploaded" / up.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(up.getvalue())
                st.session_state["hs_preview_path"] = str(dest)
                path = str(dest)
        pv = st.session_state.get("hs_preview_path")
        if pv and pv == path:
            preview_import(Path(pv), hs)

    # ---- current list
    if hs["loaded"]:
        st.subheader(t("hs_browse"))
        items = list((master.load() or {}).get("items", {}).values())
        q = st.text_input(t("hs_filter"), key="hs_q").strip().upper()
        rows = [dict(m=i["model"], h=master.fmt(i["hs"]), r=i["row"]) for i in items
                if not q or q in i["model"].upper() or q.replace(".", "") in i["hs"]]
        st.dataframe([{t1("hs_col_model"): r["m"], t1("hs_col_hs"): r["h"], t1("hs_col_row"): r["r"]} for r in rows],
                     hide_index=True, width="stretch", height=min(38 + 35 * len(rows), 420))
        if hs["skipped"]:
            with st.expander(f"{t1('hs_skipped_n')} ({len(hs['skipped'])})"):
                skipped_table(hs["skipped"])


def _browse(current: str):
    """Open the PC's own file dialog; the chosen Excel goes into the path box and its preview opens."""
    from ..filepick import pick_excel
    chosen = pick_excel(current)
    if chosen is None:
        st.session_state["hs_pick_failed"] = True
    elif chosen:
        st.session_state["hs_path"] = chosen
        st.session_state["hs_preview_path"] = chosen
        st.session_state.pop("hs_pick_failed", None)


def skipped_table(rows):
    st.dataframe([{t1("hs_col_row"): s["row"], t1("hs_col_model"): s.get("model", ""), t1("hs_col_hs"): s.get("hs", ""),
                   t1("hs_col_reason"): s["reason"]} for s in rows], hide_index=True, width="stretch")


def preview_import(path: Path, hs: dict):
    try:
        items, skipped = master.read_xlsx(path)        # read only: the Excel is never changed
    except Exception as e:                              # wrong path, not an Excel, no header row
        st.error(str(e))
        return
    old = (master.load() or {}).get("items", {})
    added = [k for k in items if k not in old]
    removed = [k for k in old if k not in items]
    changed = [k for k in items if k in old and old[k]["hs"] != items[k]["hs"]]
    st.markdown(f"**{t('hs_preview', name=path.name)}**")
    st.write(t("hs_valid", n=len(items), s=len(skipped)))
    if hs["loaded"]:
        st.write(t("hs_diff", a=len(added), r=len(removed), c=len(changed)))
    st.dataframe([{t1("hs_col_model"): i["model"], t1("hs_col_hs"): master.fmt(i["hs"]), t1("hs_col_row"): i["row"],
                   "": "＋" if k in added else ("≠" if k in changed else "")} for k, i in list(items.items())[:200]],
                 hide_index=True, width="stretch", height=260)
    if skipped:
        st.markdown(f"**{t1('hs_skipped_n')}** ({len(skipped)})")
        skipped_table(skipped)
    ok = st.checkbox(t("hs_confirm"), key="hs_ok") if hs["loaded"] else True
    if st.button(t1("hs_import"), type="primary", icon=":material/upload:", disabled=not ok or not items):
        st.session_state["hs_done"] = master.import_xlsx(path)
        st.session_state.pop("hs_preview_path", None)
        st.session_state.pop("hs_ok", None)
        st.rerun()
