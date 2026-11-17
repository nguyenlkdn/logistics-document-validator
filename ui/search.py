"""Global search dialog (Ctrl+K): reviews, reference numbers, documents and findings across the history."""
from pathlib import Path

import streamlit as st

from engine import search

from . import components as ui
from . import state
from .i18n import kind_label, lang, status_label, t, t1


@st.cache_data(show_spinner=False, max_entries=4, ttl=300)
def _index(db_mtime: float, _hist) -> dict:
    return search.build(_hist)


def index() -> dict:
    p = Path(state.HIST.path)
    return _index(p.stat().st_mtime if p.exists() else 0.0, state.HIST)


def _focus():
    st.iframe("""<script>
    const doc = window.parent.document;
    function go(n) { const i = doc.querySelector('div[role=dialog] input');
      if (i) { i.focus(); return; } if (n < 30) setTimeout(() => go(n + 1), 50); }
    go(0);</script>""", height=1)


def _body():
    q = st.text_input(t1("gs_label"), key="gs_q", placeholder=t1("gs_ph"), label_visibility="collapsed",
                      icon=":material/search:")
    _focus()
    if len(q.strip()) < 2:
        st.caption(t("gs_hint"))
        return
    r = search.query(index(), q)
    if not any(r.values()):
        st.info(t("gs_none"))
        return
    pick = lambda en, vi: vi if lang() == "vi" else en
    if r["reviews"]:
        ui.label(t1("gs_reviews"))
        for x in r["reviews"]:
            lab = (f"**{x['shipment']}** · {t1('rev_short')} {x['revision']} · {x['ts'].replace('T', ' ')[:16]}"
                   + (f" · {x['n_open']} {t1('open_cnt').lower()}" if x["n_open"] else ""))
            if st.button(lab, key=f"gs_r_{x['check_id']}", type="tertiary"):
                if state.open_check(x["check_id"]):
                    state.go("dashboard")
    if r["refs"]:
        ui.label(t1("gs_refs"))
        for i, x in enumerate(r["refs"]):
            lab = f"{pick(*x['label'])}: **{x['value']}** · {x['shipment']} · {x['doc']}"
            if st.button(lab, key=f"gs_f_{i}", type="tertiary"):
                if state.open_check(x["check_id"]):
                    st.session_state.update(f_doc=x["doc"], v_page=x.get("page") or 1, v_find=x["value"].split(",")[0])
                    state.go("review")
    if r["findings"]:
        ui.label(t1("gs_findings"))
        for x in r["findings"]:
            lab = (f"{ui.ICON[x['severity']]} **{x['fid']}** · {pick(x['msg_en'], x['msg_vi'])}"
                   f" · _{status_label(x['status'])}_")
            if st.button(lab, key=f"gs_x_{x['fid']}", type="tertiary"):
                state.open_finding(x["check_id"], x["no"])
    if r["docs"]:
        ui.label(t1("gs_docs"))
        for i, x in enumerate(r["docs"]):
            lab = f"📄 **{x['doc']}** · {kind_label(x['kind'], short=True)} · {x['shipment']}"
            if st.button(lab, key=f"gs_d_{i}", type="tertiary"):
                if state.open_check(x["check_id"]):
                    st.session_state.update(f_doc=x["doc"], v_page=1)
                    state.go("review")


def open_dialog():
    st.dialog(t1("gs_title"), width="large")(_body)()
