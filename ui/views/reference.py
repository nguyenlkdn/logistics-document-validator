"""Reference data: the HS master list (company Excel). Preview and validate before replacing the current list."""
import json
from pathlib import Path

import streamlit as st

from engine import hs_suggest, master, places

from .. import components as ui
from .. import state
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

    suggestions(hs)
    place_names()

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


@st.cache_data(show_spinner=False, max_entries=4)
def _reviews(files: tuple) -> list:
    """The newest review of every shipment (review.json). files: ((path, modification time), …)."""
    out = []
    for p, _m in files:
        try:
            out.append(json.loads(Path(p).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def _review_files() -> tuple:
    latest = {}
    for c in state.HIST.checks(limit=2000):                # newest first
        latest.setdefault(c["shipment"], Path(c["out_dir"] or "") / "review.json")
    return tuple((str(p), p.stat().st_mtime) for p in latest.values() if p.is_file())


def _evidence(r: dict) -> str:
    e = []
    if r["typo_of"]:
        e.append(t1("hs_sug_typo", m=r["typo_of"]))
    if r["conflict"]:
        e.append(t1("hs_sug_conf", c=" / ".join(master.fmt(c) for c in r["conflict"])))
    if r["series_differs"]:
        e.append(t1("hs_sug_sdiff", c=", ".join(master.fmt(c) for c in r["series"])))
    if r["bl_no"]:
        e.append(t1("hs_sug_blno"))
    if r["bl_ok"]:
        e.append(t1("hs_sug_bl"))
    if r["from_series"]:
        e.append(t1("hs_sug_series"))
    elif len(r["hs"]) == 6:
        e.append(t1("hs_sug_f6"))
    if not r["codes"]:
        e.append(t1("hs_sug_noco"))
    return " · ".join(e)


def suggestions(hs: dict):
    """Models of the checked documents that the list does not have; the user confirms what is added."""
    st.subheader(t("hs_sug"))
    if not hs["loaded"]:
        st.info(t("hs_sug_need"))
        return
    for kind, text in st.session_state.pop("hs_sug_msg", []):
        (st.success if kind == "ok" else st.error)(text)
    known = {**master.added(), **master.load()["items"]}
    rows = hs_suggest.suggest(_reviews(_review_files()), known)
    if not rows:
        st.caption(t("hs_sug_none"))
    else:
        st.caption(t("hs_sug_intro"))
        label = {"ok": t1("hs_sug_ok"), "check": t1("hs_sug_check"), "none": t1("hs_sug_nocode"),
                 "single": t1("hs_sug_single")}
        table = [dict(pick=False, model=r["model"], hs=master.fmt(r["hs"]), state=label[r["state"]], why=_evidence(r),
                      docs=", ".join(dict.fromkeys(d for c in r["codes"].values() for _s, d, _p in c["docs"]))
                      or ", ".join(dict.fromkeys(d for d, _p in r["invoices"]))) for r in rows]
        # a new key when the rows change, so ticks never land on another model
        ed = st.data_editor(table, hide_index=True, width="stretch", height=min(38 + 35 * len(table), 460),
                            key=f"hs_sug_{hash(tuple(r['key'] for r in rows))}", disabled=["model", "state", "why", "docs"],
                            column_config={"pick": st.column_config.CheckboxColumn(t1("hs_sug_pick"), width=60),
                                           "model": st.column_config.TextColumn(t1("hs_col_model"), width=170),
                                           "hs": st.column_config.TextColumn(t1("hs_col_hs"), width=120),
                                           "state": st.column_config.TextColumn(t1("hs_sug_state"), width=120),
                                           "why": st.column_config.TextColumn(t1("hs_sug_why"), width="large"),
                                           "docs": st.column_config.TextColumn(t1("hs_sug_docs"), width="large")})
        picked = [(r, e) for r, e in zip(rows, ed) if e["pick"]]
        if st.button(t1("hs_sug_add", n=len(picked)), type="primary", icon=":material/playlist_add:", disabled=not picked,
                     key="hs_sug_btn"):
            n, bad = add_picked([(r, e["hs"]) for r, e in picked], state.reviewer())
            st.session_state["hs_sug_msg"] = ([("ok", t("hs_sug_done", n=n))] if n else []) + (
                [("bad", t("hs_sug_bad", m=", ".join(bad)))] if bad else [])
            st.rerun()
    mine = master.added()
    if mine:
        with st.expander(t("hs_add_title", n=len(mine)), expanded=False):
            st.caption(t("hs_add_note"))
            st.dataframe([{t1("hs_col_model"): v["model"], t1("hs_col_hs"): master.fmt(v["hs"]),
                           t1("hs_add_at"): v["added_at"].replace("T", " "), t1("hs_add_by"): v.get("by", ""),
                           t1("hs_sug_docs"): ", ".join(v.get("docs", []))} for v in mine.values()],
                         hide_index=True, width="stretch")
            st.download_button(t1("hs_add_dl"), master.added_xlsx(), "HS_added.xlsx", icon=":material/download:")
            drop = st.multiselect(t1("hs_add_rm"), list(mine), format_func=lambda k: mine[k]["model"], key="hs_add_drop")
            if st.button(t1("hs_add_rm"), disabled=not drop, icon=":material/delete:", key="hs_add_drop_btn"):
                for k in drop:
                    master.remove(k)
                st.session_state.pop("hs_add_drop", None)
                st.rerun()


def place_names():
    """Place names of the checked B/Ls that belong to no known city; the user confirms the city of each."""
    st.subheader(t("pl_names"))
    for kind, text in st.session_state.pop("pl_msg", []):
        (st.success if kind == "ok" else st.error)(text)
    rows = places.suggest(_reviews(_review_files()))
    if not rows:
        st.caption(t("pl_none"))
    else:
        st.caption(t("pl_intro"))
        table = [dict(pick=False, name=r["name"], city=r["city"],
                      why=(t1("pl_conf", c=" / ".join(r["conflict"])) if r["conflict"] else
                           t1("pl_from_bl", c=r["city"]) if r["city"] else t1("pl_no_city")),
                      docs=", ".join(r["docs"])) for r in rows]
        ed = st.data_editor(table, hide_index=True, width="stretch", height=min(38 + 35 * len(table), 300),
                            key=f"pl_{hash(tuple(r['key'] for r in rows))}", disabled=["name", "why", "docs"],
                            column_config={"pick": st.column_config.CheckboxColumn(t1("hs_sug_pick"), width=60),
                                           "name": st.column_config.TextColumn(t1("pl_name"), width=170),
                                           "city": st.column_config.TextColumn(t1("pl_city"), width=190),
                                           "why": st.column_config.TextColumn(t1("hs_sug_why"), width="large"),
                                           "docs": st.column_config.TextColumn(t1("hs_sug_docs"), width="large")})
        picked = [(r, e) for r, e in zip(rows, ed) if e["pick"]]
        if st.button(t1("pl_add", n=len(picked)), type="primary", icon=":material/add_location_alt:", disabled=not picked,
                     key="pl_btn"):
            n, bad = 0, []
            for r, e in picked:
                try:
                    places.add(r["name"], e["city"], r["docs"], state.reviewer())
                    n += 1
                except ValueError:
                    bad.append(r["name"])
            st.session_state["pl_msg"] = ([("ok", t("pl_done", n=n))] if n else []) + (
                [("bad", t("pl_bad", m=", ".join(bad)))] if bad else [])
            st.rerun()
    mine = places.added()
    if mine:
        with st.expander(t("pl_mine", n=len(mine)), expanded=False):
            st.dataframe([{t1("pl_name"): v["name"], t1("pl_city"): v["city"], t1("hs_add_at"): v["added_at"].replace("T", " "),
                           t1("hs_add_by"): v.get("by", ""), t1("hs_sug_docs"): ", ".join(v.get("docs", []))}
                          for v in mine.values()], hide_index=True, width="stretch")
            drop = st.multiselect(t1("hs_add_rm"), list(mine), format_func=lambda k: mine[k]["name"], key="pl_drop")
            if st.button(t1("hs_add_rm"), disabled=not drop, icon=":material/delete:", key="pl_drop_btn"):
                for k in drop:
                    places.remove(k)
                st.session_state.pop("pl_drop", None)
                st.rerun()


def add_picked(picked: list, by: str) -> tuple:
    """(number added, models whose code is not valid). picked = [(suggestion, HS code as edited)]."""
    n, bad = 0, []
    for r, code in picked:
        docs = list(dict.fromkeys(d for c in r["codes"].values() for _s, d, _p in c["docs"])) or [d for d, _p in r["invoices"]]
        try:
            master.add(r["model"], code or "", docs, by)
            n += 1
        except ValueError:
            bad.append(r["model"])
    return n, bad


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
