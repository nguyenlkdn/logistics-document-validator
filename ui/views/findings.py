"""Findings: every finding across documents (and across reviews) in one table, with reviewer status.

Select rows to change their status or add a comment in one go. The automated findings are never changed: a decision
is stored in history.db next to them, and every change is logged with who made it and when.
"""
import hashlib
import io
from datetime import date

import streamlit as st

from engine.rules import SEVERITY

from .. import components as ui
from .. import state
from ..i18n import kind_label, msg, sev_short, status_label, t, t1

KINDS = ("CI", "SC", "BL", "CO")


def fid(f: dict) -> str:
    return f"{f['shipment']}-R{f['revision']}-{f['no']:02d}"


def render():
    ui.header(t("fm_title"), ui.esc(t("fm_sub")))
    cid = state.check_id()
    scopes = (["open"] if cid else []) + ["latest", "all"]
    if st.session_state.get("fm_scope") not in scopes:
        st.session_state["fm_scope"] = scopes[0]
    scope = st.segmented_control(t1("fm_scope"), scopes, key="fm_scope", label_visibility="collapsed",
                                 format_func=lambda k: {"open": t1("fm_scope_open"), "latest": t1("fm_scope_latest"),
                                                        "all": t1("fm_scope_all")}[k]) or scopes[0]
    if scope == "open":
        rows = state.HIST.all_findings(check_id=cid)
    else:
        rows = state.HIST.all_findings(latest_only=scope == "latest")
    if not rows:
        st.info(t("no_hist"))
        return

    # ---- filters
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):      # wraps on narrow screens
        sev = st.pills(t("flt_sev"), SEVERITY, selection_mode="multi", key="fm_sev", width="content",
                       format_func=lambda x: f"{ui.ICON[x]} {sev_short(x)}")
        stt = st.pills(t("flt_status"), state.STATUSES, selection_mode="multi", key="fm_status", width="content",
                       format_func=status_label)
    g1, g2, g3, g4 = st.columns([2.2, 2.6, 2.4, 3], vertical_alignment="bottom")
    kinds = g1.multiselect(t1("col_kind"), KINDS, key="fm_kind", format_func=lambda k: kind_label(k, short=True),
                           placeholder=t1("hs_all"))
    rules = g2.multiselect(t1("rule"), sorted({r["key"] for r in rows}), key="fm_rule", placeholder=t1("hs_all"))
    days = sorted(date.fromisoformat(r["ts"][:10]) for r in rows)
    rng = g3.date_input(t1("hist_dates"), value=(days[0], days[-1]), min_value=days[0], max_value=days[-1],
                        key=f"fm_dates_{scope}", format="YYYY-MM-DD", disabled=scope == "open")
    q = g4.text_input(t1("flt_search"), key="fm_q", placeholder=t1("fm_search_ph")).strip().lower()
    lo, hi = (rng[0], rng[1]) if isinstance(rng, tuple) and len(rng) == 2 else (days[0], days[-1])

    def keep(r):
        if sev and r["severity"] not in sev or stt and r["status"] not in stt:
            return False
        if kinds and r["doc_kind"] not in kinds or rules and r["key"] not in rules:
            return False
        if not lo <= date.fromisoformat(r["ts"][:10]) <= hi:
            return False
        return not q or any(q in str(r.get(k) or "").lower() for k in
                            ("msg_en", "msg_vi", "current", "suggested", "doc", "shipment", "key", "note")) \
            or q in fid(r).lower()

    rows = [r for r in rows if keep(r)]
    n_open = sum(r["status"] in state.OPEN and r["severity"] != "INFO" for r in rows)
    st.caption(t("fm_count", n=len(rows), open=n_open))
    if not rows:
        st.info(t("none_match"))
        return

    # ---- table (multi-row selection)
    table = [{"id": fid(r), "sev": f"{ui.ICON[r['severity']]} {sev_short(r['severity'])}", "status": status_label(r["status"]),
              "msg": msg(r), "doc": r["doc"], "kind": kind_label(r["doc_kind"], short=True, form=r.get("doc_form", "")), "page": r["page"],
              "cur": r["current"], "sug": r["suggested"], "note": r["note"], "ts": r["ts"].replace("T", " ")[:16]}
             for r in rows]
    sig = hashlib.sha1(repr((scope, sev, stt, kinds, rules, lo, hi, q, len(rows))).encode()).hexdigest()[:10]
    ev = st.dataframe(
        table, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key=f"fm_tbl_{sig}",
        height=min(38 + 35 * len(table), 520),
        column_order=["id", "sev", "status", "msg", "doc", "kind", "page", "cur", "sug", "note", "ts"],
        column_config={"id": st.column_config.TextColumn(t1("fm_id"), width=180),
                       "sev": st.column_config.TextColumn(t1("severity"), width=90),
                       "status": st.column_config.TextColumn(t1("status"), width=120),
                       "msg": st.column_config.TextColumn(t1("fm_finding"), width="large"),
                       "doc": st.column_config.TextColumn(t1("doc"), width="medium"),
                       "kind": st.column_config.TextColumn(t1("col_kind"), width=60),
                       "page": st.column_config.NumberColumn(t1("page").capitalize(), width=50),
                       "cur": t1("found"), "sug": t1("expected"), "note": t1("note_in"),
                       "ts": st.column_config.TextColumn(t1("date"), width=120)})
    picked = [rows[i] for i in (ev.selection.rows if ev and ev.selection else []) if i < len(rows)]

    a, b = st.columns([5, 1.4], vertical_alignment="bottom")
    with b:
        st.download_button(t1("fm_export"), lambda rows=rows: excel(rows), file_name="LDV_findings.xlsx", icon=":material/download:",
                           width="stretch", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with a:
        if not picked:
            st.caption(t("fm_pick"))
    if picked:
        bulk(picked)


def bulk(picked: list[dict]):
    with st.container(border=True):
        st.markdown(f"**{t1('fm_selected', n=len(picked))}**")
        c1, c2, c3, c4 = st.columns([2.2, 4, 1.3, 1.8], vertical_alignment="bottom")
        k = st.session_state.get("fm_round", 0)                # new keys after each apply = cleared inputs
        new = c1.selectbox(t1("fm_set_status"), ["", *state.STATUSES], key=f"fm_new_status_{k}",
                           format_func=lambda k: t1("fm_keep") if not k else status_label(k))
        note = c2.text_input(t1("fm_comment"), key=f"fm_comment_{k}", placeholder=t1("fm_comment_ph"))
        if c3.button(t1("fm_apply"), type="primary", disabled=not new and not note.strip(), width="stretch"):
            n = sum(state.set_mark(r["sig"], new or r["status"], note.strip() or r["note"], shipment=r["shipment"])
                    for r in picked)
            st.session_state["fm_round"] = k + 1
            st.toast(t1("fm_applied", n=n))
            st.rerun()
        if len(picked) == 1 and c4.button(t1("fm_open"), icon=":material/find_in_page:", width="stretch"):
            state.open_finding(picked[0]["check_id"], picked[0]["no"])
        if not state.reviewer():
            st.caption(t("fm_no_name"))


def excel(rows: list[dict]) -> bytes:
    """The filtered findings as an Excel table (EN and VI messages, reviewer status and note)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Findings"
    ws.append(["ID", "Checked", "Shipment", "Revision", "No", "Severity", "Rule", "Document", "Type", "Page",
               "Message (EN)", "Nội dung (VI)", "Found", "Expected", "Status", "Reviewer note"])
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="34495E")
    for r in rows:
        ws.append([fid(r), r["ts"].replace("T", " "), r["shipment"], r["revision"], r["no"], r["severity"], r["key"],
                   r["doc"], r["doc_kind"], r["page"], r["msg_en"], r["msg_vi"], r["current"], r["suggested"],
                   r["status"], r["note"]])
    for col, w in zip("ABCDEFGHIJKLMNOP", (22, 17, 16, 8, 5, 9, 18, 34, 6, 6, 50, 50, 20, 20, 11, 36)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
