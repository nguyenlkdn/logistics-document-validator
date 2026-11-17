"""Report: reviewer sign-off, report options, preview, export (PDF / Excel / HTML) and earlier reports.

The sign-off is the reviewer's conclusion for this revision. 'Approved' is refused while an error is open; the
reviewer can record 'Approved with exception' with a reason instead (the history database enforces the same rule).
"""
from datetime import datetime
from pathlib import Path

import streamlit as st

from engine import review_report as rr

from .. import components as ui
from .. import state
from ..i18n import t, t1

MIME = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "html": "text/html"}
RESULTS = ("approved", "approved_exception", "returned")
SO_COLOR = dict(approved="RESOLVED", approved_exception="WARNING", returned="ERROR")


def render():
    s = state.current()
    cid = state.check_id()
    if not s or not cid:
        st.info(t("no_workspace"))
        return
    mk = state.marks()
    c = state.counts(s, mk)
    rev = s.get("revision") or 1
    ui.header(t("rep_title"), ui.esc(f"{s['shipment']} · {t1('rev')} {rev}"))
    ui.stepper(s, c)
    signoff(s, cid, c)
    st.write("")
    report(s, cid)
    earlier(s)


# ------------------------------------------------------------------ sign-off
def signoff(s, cid, c):
    st.subheader(t("so_title"))
    hist = state.HIST.signoffs(cid)
    last = hist[0] if hist else None
    key, color, n_err, n_warn = rr.outcome(s, state.marks())
    a, b = st.columns(2, gap="large")
    with a:
        ui.label(t1("so_auto"))
        ui_key = dict(auto_err="verdict_errors", auto_warn="verdict_warn", auto_gaps="verdict_gaps_only",
                      auto_ok="verdict_ok")[key]
        ui.verdict(t(ui_key, n=n_err or n_warn or len(s.get("unrecognised", []))), {"OK": "RESOLVED"}.get(color, color))
    with b:
        ui.label(t1("so_human"))
        if last:
            ui.verdict(t1(f"so_{last['result']}") + " — " + t1("so_by", who=last["who"] or "—",
                                                               ts=last["ts"].replace("T", " ")),
                       SO_COLOR[last["result"]], last.get("note") or "")
        else:
            ui.verdict(t1("so_none"), "MUTED")

    with st.container(border=True):
        if n_err:
            st.warning(t("so_blocked", n=n_err), icon=":material/block:")
        k = f"{cid}_{st.session_state.get('so_round', 0)}"      # new keys after signing = an empty form
        res = st.radio(t1("so_result"), RESULTS, horizontal=True, key=f"so_res_{k}",
                       format_func=lambda k: t1(f"so_{k}"), index=None)
        note = st.text_area(t1("so_note"), key=f"so_note_{k}", height=80,
                            placeholder=t1("so_note_req") if res in ("approved_exception", "returned") else "")
        who = state.reviewer()
        if not who:
            who = st.text_input(t1("set_name"), key="so_who", help=t1("set_name_help")).strip()
        bad = (not res or (res == "approved" and n_err) or (res != "approved" and not note.strip()) or not who)
        if res == "approved" and n_err:
            st.caption(t("so_use_exception"))
        if st.button(t1("so_sign"), type="primary", icon=":material/verified:", disabled=bad, key=f"so_btn_{cid}"):
            if who != state.reviewer():
                state.save_ui_settings(reviewer=who)
            try:
                state.HIST.sign(cid, res, note, who=who)
            except ValueError as e:                     # same rule enforced in the database layer
                st.error(str(e))
            else:
                st.toast(t1("so_saved"))
                st.session_state["so_round"] = st.session_state.get("so_round", 0) + 1
                st.rerun()
    if len(hist) > 1 or (hist and hist[0].get("note")):
        with st.expander(f"{t1('so_history')} ({len(hist)})"):
            for h in hist:
                st.markdown(f"{ui.chip(t1('so_' + h['result']), SO_COLOR[h['result']])} "
                            f"<span style='color:#5f6368;font-size:.85rem'>{ui.esc(h['ts'].replace('T', ' '))} · "
                            f"{ui.esc(h['who'] or '—')} · {ui.esc(t1('so_open_at', e=h['open_errors'], w=h['open_warnings']))}"
                            f"</span>" + (f"<br><span style='font-size:.88rem'>“{ui.esc(h['note'])}”</span>" if h["note"] else ""),
                            unsafe_allow_html=True)


# ------------------------------------------------------------------ report
def _lang():
    return st.session_state.get("rep_lang") or (st.session_state.get("lang") or "en")


def report(s, cid):
    st.subheader(t("rep_report"))
    o1, o2 = st.columns([2, 5], vertical_alignment="top")
    with o1:
        st.segmented_control(t1("rep_lang"), ["en", "vi", "both"], key="rep_lang",
                             default=st.session_state.get("lang") or "en",
                             format_func=lambda k: {"en": "English", "vi": "Tiếng Việt", "both": "EN + VI"}[k])
    with o2:
        x1, x2, x3, x4 = st.columns(4)
        info = x1.toggle(t1("rep_info"), value=False, key="rep_info")
        only_open = x2.toggle(t1("rep_open"), value=False, key="rep_only_open")
        snaps = x3.toggle(t1("rep_snaps"), value=True, key="rep_snaps")
        cross = x4.toggle(t1("rep_cross"), value=True, key="rep_cross")
    opts = dict(lang=_lang(), info=info, only_open=only_open, snapshots=snaps, crosscheck=cross)
    if not s.get("out_dir") or not Path(s["out_dir"]).exists():
        st.warning(t("missing_folder"))
        return

    b1, b2, b3, _ = st.columns([1.3, 1.3, 1.3, 4])
    made = None
    for col, fmt, icon in ((b1, "pdf", ":material/picture_as_pdf:"), (b2, "xlsx", ":material/table_view:"),
                           (b3, "html", ":material/code:")):
        if col.button(t1(f"rep_make_{fmt}"), icon=icon, width="stretch", type="primary" if fmt == "pdf" else "secondary"):
            with st.spinner(t1("rep_making")):
                made = rr.generate(s, state.HIST, cid, opts, fmt)
    if made:
        st.success(t("rep_made", name=made.name), icon=":material/check_circle:")
        st.download_button(t1("rep_download", name=made.name), made.read_bytes(), file_name=made.name,
                           mime=MIME[made.suffix[1:]], icon=":material/download:", key=f"dl_new_{made.name}")
    st.caption(t("rep_where", path=str(Path(s["out_dir"]) / "reports")))

    if st.toggle(t1("rep_preview"), value=True, key="rep_show_preview"):
        g = rr.gather(s, state.HIST, cid)
        doc = rr.build_html(s, g["marks"], g["trails"], g["cmp"], g["signoff"], opts, images="base64")
        st.iframe(doc, height=900)


def earlier(s):
    files = rr.history(s)
    if not files:
        return
    st.subheader(t("rep_earlier"))
    for p in files[:10]:
        a, b, c = st.columns([5, 2, 1.4], vertical_alignment="center")
        a.markdown(f"`{p.name}`")
        b.caption(datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M") + f" · {p.stat().st_size // 1024} KB")
        c.download_button(t1("rep_dl"), p.read_bytes(), file_name=p.name, mime=MIME.get(p.suffix[1:], "application/octet-stream"),
                          key=f"dl_{p.name}", icon=":material/download:", width="stretch")
