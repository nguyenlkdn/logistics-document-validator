"""Dashboard: the state of the open document package at a glance. Every number opens the matching findings."""
import streamlit as st

from engine.rules import SEVERITY

from .. import components as ui
from .. import state
from ..i18n import kind_label, sev_label, sev_short, t, t1, unrec_text


def render():
    s = state.current()
    if not s:
        return empty()
    if st.session_state.get("job_files"):
        st.info(f"{t('from_menu')}: " + ", ".join(st.session_state["job_files"]), icon=":material/mouse:")
    mk = state.marks()
    c = state.counts(s, mk)
    rev = f" · {t('rev')} {s['revision']}" if s.get("revision") else ""
    ui.header(s["shipment"], ui.esc(t("checked_at", when=(s.get("check_ts") or s["created"]).replace("T", " ")) + rev
                                    + f" · {len(s['docs'])} {t('k_docs').lower()}"))
    ui.stepper(s, c)

    gaps = [u for u in s.get("unrecognised", [])]
    small = t("verdict_gaps", n=len(gaps)) if gaps else ""
    if c["open_error"]:
        ui.verdict(t("verdict_errors", n=c["open_error"]), "ERROR", small)
    elif c["open_warning"]:
        ui.verdict(t("verdict_warn", n=c["open_warning"]), "WARNING", small)
    elif gaps:                                       # nothing open, but not everything could be checked
        ui.verdict(t("verdict_gaps_only", n=len(gaps)), "WARNING")
    else:
        ui.verdict(t("verdict_ok"), "RESOLVED", small)

    # ---- numbers
    n_skipped = len(s.get("skipped", []))
    left, mid, right = st.columns([3, 5, 4], gap="medium")
    with left:
        ui.label(t1("k_package"))
        a, b = st.columns(2)
        with a:
            if ui.tile("docs", len(s["docs"]) + n_skipped, t1("k_docs")):
                state.show_findings()
        with b:
            unrec_clicked = ui.tile("unrec", len(gaps), t1("k_unrec"), "WARNING" if gaps else "MUTED", disabled=not gaps)
    with mid:
        ui.label(t1("k_findings"))
        cols = st.columns(5)
        with cols[0]:
            if ui.tile("total", c["total"], t1("k_total"), disabled=not c["total"]):
                state.show_findings()
        for col, sev in zip(cols[1:], SEVERITY):
            with col:
                if ui.tile(sev, c[sev], sev_short(sev), sev, disabled=not c[sev]):
                    state.show_findings(sev=[sev])
    with right:
        ui.label(t1("k_progress"))
        cols = st.columns(3)
        with cols[0]:
            if ui.tile("open", c["todo"], t1("k_open"), "ERROR" if c["open_error"] else "MUTED", disabled=not c["todo"]):
                state.show_findings(status=["open", "in_review"])
        with cols[1]:
            if ui.tile("waiting", c["waiting"], t1("k_waiting"), "WAITING", disabled=not c["waiting"]):
                state.show_findings(status=["waiting"])
        with cols[2]:
            if ui.tile("resolved", c["done"], t1("k_resolved"), "RESOLVED", disabled=not c["done"]):
                state.show_findings(status=list(state.DONE))
    st.caption(t("click_hint"))

    # ---- distribution, progress, documents
    st.write("")
    l, r = st.columns([2, 3], gap="large")
    with l:
        st.subheader(t("distribution"))
        ui.bars([(sev_label(sev), c[sev], sev) for sev in SEVERITY], max([c[sev] for sev in SEVERITY] + [1]))
        st.write("")
        st.subheader(t("k_progress"))
        st.caption(t("progress_txt", done=c["done"], n=c["actionable"]))
        ui.stack([(t1("st_fixed"), c["fixed"], "RESOLVED"), (t1("st_accepted"), c["accepted"], "RESOLVED"),
                  (t1("st_not_error"), c["not_error"], "MUTED"), (t1("st_waiting"), c["waiting"], "WAITING"),
                  (t1("st_in_review"), c["in_review"], "INFO"), (t1("st_open"), c["open"], "ERROR")])
    with r:
        if any(d.get("fields") for d in s["docs"]):
            from engine.compare import compare
            n_diff = sum(x["result"] == "mismatch" for x in compare(s)["rows"])
            if st.button(t1("cmp_link", n=n_diff) if n_diff else t1("cmp_link_ok"), type="tertiary",
                         icon=":material/compare:", key="dash_cmp"):
                state.go("compare")
        st.subheader(t("docs_status"))
        st.caption(t("docs_click"))
        rows = state.per_doc(s)
        table = [{"doc": x["name"], "type": kind_label(x["kind"], short=True), "pages": x["pages"],
                  **{sev: str(x[sev]) if x[sev] else "" for sev in SEVERITY}, "total": x["total"]} for x in rows]
        small = lambda lab: st.column_config.TextColumn(lab, width=44)
        ev = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                          key=f"dash_docs_{state.check_id()}",
                          column_config={"doc": st.column_config.TextColumn(t1("col_doc")),
                                         "type": st.column_config.TextColumn(t1("col_kind"), width=70),
                                         "pages": st.column_config.NumberColumn(t1("col_pages"), width=52),
                                         "total": st.column_config.NumberColumn(t1("k_total"), width=52),
                                         **{sev: small(ui.ICON[sev]) for sev in SEVERITY}})
        if ev and ev.selection and ev.selection.rows:
            state.show_findings(doc=rows[ev.selection.rows[0]]["name"])

    if gaps:
        with st.expander(f"{t('unrec_title')} ({len(gaps)})", expanded=unrec_clicked):
            for u in gaps:
                st.markdown(f"- **{ui.esc(u['doc'])}** — {ui.esc(unrec_text(u))}")


def empty():
    ui.header(t("dash_title"))
    ui.stepper(None)
    with st.container(border=True):
        st.markdown(f"#### {t('empty_title')}")
        st.write(t("empty_body"))
        a, b, _ = st.columns([2, 2, 5])
        if a.button(t1("start_new"), type="primary", icon=":material/upload_file:", width="stretch"):
            state.go("new")
        if b.button(t1("open_hist"), icon=":material/history:", width="stretch"):
            state.go("history")
    rows = state.HIST.checks(limit=8)
    if rows:
        st.subheader(t("recent"))
        table = [{t1("date"): r["ts"].replace("T", " "), t1("shipment"): r["shipment"], t1("rev"): r["revision"],
                  f"{ui.ICON['ERROR']} {sev_short('ERROR')}": r["n_error"],
                  f"{ui.ICON['WARNING']} {sev_short('WARNING')}": r["n_warning"], t1("open_cnt"): r["n_open"]}
                 for r in rows]
        ev = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                          key="dash_recent")
        if ev and ev.selection and ev.selection.rows and state.open_check(rows[ev.selection.rows[0]]["id"]):
            st.rerun()
