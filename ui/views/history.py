"""Review history: searchable list of past checks. Opening one restores its stored results (no re-analysis)."""
import json
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

from engine.history import STATUSES

from .. import components as ui
from .. import state
from ..i18n import msg, sev_short, status_label, t, t1
from .review import open_folder, revision_banner


def render():
    rows = state.HIST.checks()
    h, a = st.columns([5, 2], vertical_alignment="bottom")
    with h:
        ui.header(t("hist_title"), ui.esc(t("n_reviews", n=len(rows))))
    if not rows:
        st.info(t("no_hist"))
        return
    tmp = Path(tempfile.gettempdir()) / "LDV_feedback.xlsx"
    a.download_button(t1("export"), state.HIST.export(tmp).read_bytes(), file_name="LDV_feedback.xlsx",
                      icon=":material/download:", width="stretch",
                      mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ---- filters
    days = sorted(date.fromisoformat(r["ts"][:10]) for r in rows)
    f1, f2, f3 = st.columns([4, 3, 3], vertical_alignment="bottom")
    q = f1.text_input(t("hist_search"), placeholder=t1("hist_search_ph"), key="h_q").strip().lower()
    which = f2.segmented_control(t("hist_state"), ["all", "open", "clear"], default="all", key="h_state",
                                 format_func=lambda k: t1({"all": "hs_all", "open": "hs_open", "clear": "hs_clear"}[k]))
    rng = f3.date_input(t("hist_dates"), value=(days[0], days[-1]), min_value=days[0], max_value=days[-1], key="h_dates",
                        format="YYYY-MM-DD")
    lo, hi = (rng[0], rng[1]) if isinstance(rng, tuple) and len(rng) == 2 else (days[0], days[-1])

    def keep(r):
        files = json.loads(r["files"] or "[]")
        if q and q not in r["shipment"].lower() and q not in (r["name"] or "").lower() \
                and not any(q in f.lower() for f in files):
            return False
        if which == "open" and not r["n_open"] or which == "clear" and r["n_open"]:
            return False
        return lo <= date.fromisoformat(r["ts"][:10]) <= hi

    rows = [r for r in rows if keep(r)]
    st.caption(t("hist_pick"))
    table = [{t1("date"): r["ts"].replace("T", " "), t1("shipment"): r["shipment"], t1("rev"): r["revision"],
              t1("k_docs"): len(json.loads(r["files"] or "[]")),
              f"{ui.ICON['ERROR']} {sev_short('ERROR')}": r["n_error"],
              f"{ui.ICON['WARNING']} {sev_short('WARNING')}": r["n_warning"],
              f"{ui.ICON['MINOR']} {sev_short('MINOR')}": r["n_minor"],
              f"{ui.ICON['INFO']} {sev_short('INFO')}": r["n_info"],
              t1("open_cnt"): r["n_open"],
              t1("status"): "✅ " + t1("hs_clear") if not r["n_open"] else "⏳ " + t1("hs_open")} for r in rows]
    ev = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                      key="hist_table", height=min(38 + 35 * len(table), 420))
    sel = ev.selection.rows if ev and ev.selection else []
    if not sel or sel[0] >= len(rows):
        return
    c = rows[sel[0]]
    st.subheader(f"{c['shipment']} — {t1('rev')} {c['revision']}")
    folder = Path(c["out_dir"]) if c.get("out_dir") else None
    b1, b2, b3, _ = st.columns([2, 2, 2, 3])
    if b1.button(t1("open_review"), type="primary", icon=":material/open_in_new:", width="stretch"):
        if state.open_check(c["id"]):
            state.go("dashboard")
    xl = folder / "report.xlsx" if folder else None
    if xl and xl.exists():
        b2.download_button(t1("download"), xl.read_bytes(), file_name=f"{c['name']}_report.xlsx", width="stretch",
                           icon=":material/download:",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if folder and folder.exists():
        if b3.button(t1("open_folder"), icon=":material/folder_open:", width="stretch"):
            open_folder(str(folder))
        st.caption(f"{t('saved')}: `{folder}`")
    else:
        st.warning(t("missing_folder"))
    revision_banner(c["id"])
    with st.expander(t("quick_edit")):
        quick_edit(c)


def quick_edit(c):
    """Status + note for every finding of a past check in one table (same marks as on the findings page)."""
    fs = state.HIST.findings(c["id"])
    if not fs:
        st.success(t("none"))
        return
    import pandas as pd
    df = pd.DataFrame([{"no": f["no"], "sev": ui.ICON[f["severity"]], "doc": f["doc"], "msg": msg(f),
                        "cur": f["current"], "sug": f["suggested"], "status": status_label(f["status"]),
                        "note": f["note"]} for f in fs])
    edited = st.data_editor(df, hide_index=True, width="stretch", key=f"ed_{c['id']}",
                            column_order=["no", "sev", "status", "note", "msg", "cur", "sug", "doc"],
                            disabled=["no", "sev", "doc", "msg", "cur", "sug"],
                            column_config={
                                "no": st.column_config.NumberColumn("#", width=40),
                                "sev": st.column_config.TextColumn("", width=40),
                                "doc": t1("doc"), "msg": st.column_config.TextColumn(t1("nav_review"), width="large"),
                                "cur": t1("current"), "sug": t1("suggested"),
                                "status": st.column_config.SelectboxColumn(
                                    t1("status"), options=[status_label(k) for k in STATUSES], required=True,
                                    width="medium"),
                                "note": st.column_config.TextColumn(t1("note_in"), width="medium")})
    back = {status_label(k): k for k in STATUSES}
    changed = 0
    for f, (_, row) in zip(fs, edited.iterrows()):
        stt, nt = back[row["status"]], row["note"] or ""
        if (stt, nt) != (f["status"], f["note"]):
            changed += state.set_mark(f["sig"], stt, nt, shipment=c["shipment"])
    if changed:
        st.toast(t1("saved_marks"))
