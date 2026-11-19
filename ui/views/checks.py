"""Checks: every check LDV made on the open review and what happened to it (LDV 2.3, engine/checks.py).

Read only: the records come from review.json and are never changed. The status column is the automated result;
a finding closed by the reviewer is shown in the Findings / Review pages, not by changing the check.
"""
import streamlit as st

from engine.checks import CheckStatus, check_name, reason_text
from engine.report import check_rows

from .. import components as ui
from .. import state
from ..i18n import langs, t, t1

COLOR = dict(PASS="RESOLVED", FAIL="ERROR", REVIEW_REQUIRED="WARNING", NOT_RUN="WAITING", NOT_APPLICABLE="MUTED")
ICON = dict(PASS="✅", FAIL="🔴", REVIEW_REQUIRED="🟠", NOT_RUN="⏸️", NOT_APPLICABLE="➖")
CATS = ("reading", "master_data", "package", "dependency", "system")


def _both(fn) -> str:
    return " / ".join(fn(l) for l in langs())


def render():
    s = state.current()
    ui.header(t("ck_title"), ui.esc(t("ck_sub")))
    if not s:
        st.info(t("empty_body"))
        return
    if not s.get("checks"):
        st.warning(t("ck_legacy", v=s.get("version") or "≤ 2.2"), icon=":material/history:")
        return
    dashboard_verdict(s)
    rows = check_rows(s["checks"])
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):
        default = st.session_state.pop("ck_preset", None)
        if default is not None:
            st.session_state["ck_status"] = default
        stt = st.pills(t("ck_status"), list(CheckStatus.ALL), selection_mode="multi", key="ck_status",
                       format_func=lambda x: f"{ICON[x]} {t1('cks_' + x)} ({sum(r['status'] == x for r in rows)})")
        cats = st.pills(t("ck_cat"), list(CATS), selection_mode="multi", key="ck_cat",
                        format_func=lambda c: t1("cat_" + c))
        core = st.toggle(t1("ck_core_only"), key="ck_core")
    keep = [r for r in rows if (not stt or r["status"] in stt) and (not core or r["core"])
            and (not cats or r.get("category") in cats)]
    if not keep:
        st.info(t("ck_none"))
        return
    table = [{"st": f"{ICON[r['status']]} {t1('cks_' + r['status'])}", "core": "✔" if r["core"] else "",
              "check": _both(lambda l: check_name(r["id"], l)), "id": r["id"],
              "group": r.get("group_label") or r["group"], "doc": r.get("doc") or "",
              "reason": _both(lambda l: reason_text(r, l)) if reason_text(r, "en") else "",
              "findings": ", ".join(f"#{n}" for n in r["findings"])} for r in keep]
    ev = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                      key=f"ck_tab_{state.check_id()}",
                      column_config={"st": st.column_config.TextColumn(t1("ck_status"), width=120),
                                     "core": st.column_config.TextColumn(t1("ck_col_core"), width=50),
                                     "check": st.column_config.TextColumn(t1("ck_col_check"), width="large"),
                                     "id": st.column_config.TextColumn("ID", width=150),
                                     "group": st.column_config.TextColumn(t1("ck_col_group"), width=130),
                                     "doc": st.column_config.TextColumn(t1("ck_col_doc")),
                                     "reason": st.column_config.TextColumn(t1("ck_col_reason"), width="large"),
                                     "findings": st.column_config.TextColumn(t1("ck_col_findings"), width=80)})
    if ev and ev.selection and ev.selection.rows:
        r = keep[ev.selection.rows[0]]
        with st.container(border=True):
            st.markdown(f"**{ui.esc(_both(lambda l: check_name(r['id'], l)))}** · `{r['id']}` · "
                        + ui.chip(t1("cks_" + r["status"]), COLOR[r["status"]]), unsafe_allow_html=True)
            if reason_text(r, "en"):
                st.write(_both(lambda l: reason_text(r, l)))
            if r.get("inputs"):
                ui.label(t1("ck_col_inputs"))
                st.markdown("\n".join(f"- `{x['kind']}.{x['name']}` — {ui.esc(x['doc'])}: **{x['status']}**"
                                      for x in r["inputs"]))
            with st.container(horizontal=True):
                for n in r["findings"]:
                    if st.button(t1("ck_open_find", n=n), key=f"ck_f_{r['id']}_{r['group']}_{n}", type="tertiary"):
                        state.open_finding(state.check_id(), n)


def dashboard_verdict(s: dict):
    """The verdict banner + its detail line (used by the Dashboard and this page)."""
    from engine.checks import effective
    from engine.review_report import outcome
    v = effective(s, state.marks())
    if v is None:
        return False
    key, color, n_err, n_open = outcome(s, state.marks())
    ui_key = dict(v_red="verdict_red", v_amber="verdict_amber", v_green="verdict_green")[key]
    passed = sum(r["core"] and r["status"] == CheckStatus.PASS for r in s["checks"])
    small = t("verdict_detail", passed=passed, total=v["core_total"], nr=v["core_not_run"], rv=v["core_review"],
              other=v["noncore_not_run"])
    if v["categories"]:
        small += " · " + t("verdict_cats", cats=", ".join(f"{t1('cat_' + c)} ({n})" for c, n in v["categories"].items()))
    if v["reviewer_closed"]:
        small += " · " + t("verdict_closed", n=v["reviewer_closed"])
    ui.verdict(t(ui_key, n=n_err or n_open), {"OK": "RESOLVED"}.get(color, color), small)
    return True
