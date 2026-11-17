"""LDV - Logistics Document Validator: local web app (report only, documents are never modified).

Run:  Start.bat   (or: python -m streamlit run app.py)

The pages live in ui/views/; analysis stays in engine/ (the UI only reads its results).
"""
import json
import re
import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui import components as ui                                     # noqa: E402
from ui import state                                                # noqa: E402
from ui.i18n import LANGS, t, t1                                    # noqa: E402
from ui.views import compare, dashboard, findings, history, new_review, reference, report, review, settings  # noqa: E402

st.set_page_config(page_title="LDV - Logistics Document Validator", page_icon="📦", layout="wide",
                   initial_sidebar_state="expanded")
ui.inject_css()
st.session_state.setdefault("lang", "en")

# ---- right-click "Send to > LDV Checker": ldv_open.py leaves the selected paths in a job file
job_done = False
job = st.query_params.get("job", "")
if re.fullmatch(r"[0-9a-f]{32}", job) and st.session_state.get("job_done") != job:
    st.session_state["job_done"] = job
    jf = Path(tempfile.gettempdir()) / "ldv_jobs" / f"{job}.json"
    if jf.exists():
        paths = [Path(p) for p in json.loads(jf.read_text(encoding="utf-8"))["paths"]]
        jf.unlink(missing_ok=True)
        zips = [p for p in paths if p.suffix.lower() == ".zip"]
        if len(zips) > 1 or (zips and len(paths) > 1):
            st.error(t("one_zip"))
        else:
            one = paths[0] if len(paths) == 1 and (paths[0].is_dir() or zips) else None
            with st.spinner(t("running", n=len(paths))):
                state.run_check(paths, name=one.stem if one else None)
            st.session_state["job_files"] = [p.name for p in paths]
            job_done = True
    st.query_params.clear()

# ---- navigation
P = state.PAGES
P["dashboard"] = st.Page(dashboard.render, title=t1("nav_dashboard"), icon=":material/space_dashboard:",
                         default=True)
P["new"] = st.Page(new_review.render, title=t1("nav_new"), icon=":material/upload_file:", url_path="new")
P["review"] = st.Page(review.render, title=t1("nav_review"), icon=":material/fact_check:", url_path="findings")
P["compare"] = st.Page(compare.render, title=t1("nav_compare"), icon=":material/compare:", url_path="cross-check")
P["findings"] = st.Page(findings.render, title=t1("nav_findings"), icon=":material/checklist:", url_path="all-findings")
P["report"] = st.Page(report.render, title=t1("nav_report"), icon=":material/description:", url_path="report")
P["history"] = st.Page(history.render, title=t1("nav_history"), icon=":material/history:", url_path="history")
P["reference"] = st.Page(reference.render, title=t1("nav_reference"), icon=":material/table_view:", url_path="reference")
P["settings"] = st.Page(settings.render, title=t1("nav_settings"), icon=":material/settings:", url_path="settings")
nav = st.navigation({t1("sec_review"): [P["dashboard"], P["new"], P["review"], P["compare"], P["findings"], P["report"]],
                     t1("sec_records"): [P["history"]],
                     t1("sec_data"): [P["reference"], P["settings"]]})

# ---- sidebar: open review, recent reviews, language, version
logo = Path(__file__).resolve().parent / "ldv.png"
if logo.exists():
    st.logo(str(logo), size="large")
with st.sidebar:
    s = state.current()
    st.markdown(f'<div class="ldv-label">{ui.esc(t1("workspace"))}</div>', unsafe_allow_html=True)
    if s:
        c = state.counts(s)
        rev = f" · {t1('rev_short')} {s['revision']}" if s.get("revision") else ""
        st.markdown(f'<div class="ldv-ws"><b>{ui.esc(s["shipment"])}</b>{ui.esc(rev)}<br>'
                    f'<span class="muted">{len(s["docs"])} {ui.esc(t1("k_docs").lower())} · '
                    f'{c["total"]} {ui.esc(t1("k_findings").lower())}</span></div>', unsafe_allow_html=True)
    else:
        st.caption(t1("no_workspace"))
    recent = state.HIST.checks(limit=5)
    if recent:
        with st.expander(t1("recent")):
            for r in recent:
                lab = f"{r['shipment']} · {t1('rev_short')} {r['revision']}"
                if st.button(lab, key=f"recent_{r['id']}", width="stretch", type="tertiary"):
                    if state.open_check(r["id"]):
                        state.go("dashboard")
    st.segmented_control(t1("lang"), list(LANGS), format_func=LANGS.get, key="lang", width="stretch")
    st.caption(f"LDV {t1('version')} {state.VERSION}")

if job_done and nav is not P["dashboard"]:
    st.switch_page(P["dashboard"])
nav.run()
