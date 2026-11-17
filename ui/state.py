"""Application state shared by the pages: the open review session, its reviewer marks, filters, navigation."""
from pathlib import Path

import streamlit as st

from engine import check, report_root, session
from engine.history import History
from engine.rules import SEVERITY

APP = Path(__file__).resolve().parent.parent
VERSION = (APP / "VERSION").read_text(encoding="utf-8").strip() if (APP / "VERSION").exists() else "dev"
HIST = History(report_root() / "history.db")
PAGES: dict = {}                     # key -> st.Page, filled by app.py
OPEN = ("open", "waiting")           # statuses that still need work
DONE = ("fixed", "not_error")


def go(page: str):
    st.switch_page(PAGES[page])


# ------------------------------------------------------------------ session
def current() -> dict | None:
    return st.session_state.get("session")


def check_id() -> int | None:
    return st.session_state.get("check_id")


def open_check(cid: int) -> bool:
    """Load a past review from its report folder (no re-analysis). False if the check does not exist."""
    c = HIST.check(cid)
    if not c:
        return False
    s = session.load(c["out_dir"]) if c.get("out_dir") and Path(c["out_dir"]).exists() else None
    if s is None:
        s = session.from_history(c, HIST.findings(cid))
    s["revision"], s["check_ts"] = c["revision"], c["ts"]
    st.session_state["session"], st.session_state["check_id"] = s, cid
    reset_filters()
    return True


def run_check(paths: list[Path], name: str | None = None) -> int:
    res = check(paths, name=name)
    cid = HIST.record(res, VERSION)
    open_check(cid)
    return cid


def marks() -> dict:
    """sig -> {status, note} for the open review (reviewer decisions, stored apart from the findings)."""
    cid = check_id()
    if not cid:
        return {}
    return {f["sig"]: dict(status=f["status"], note=f["note"]) for f in HIST.findings(cid)}


def set_mark(sig: str, status: str, note: str):
    s = current()
    HIST.set_mark(s["shipment"], sig, status, note)


def counts(s: dict, mk: dict | None = None) -> dict:
    mk = marks() if mk is None else mk
    fs = s["findings"]
    st_of = lambda f: mk.get(f["sig"], {}).get("status", "open")
    c = {sev: sum(f["severity"] == sev for f in fs) for sev in SEVERITY}
    c["total"] = len(fs)
    actionable = [f for f in fs if f["severity"] != "INFO"]
    for k in ("open", "waiting", "fixed", "not_error"):
        c[k] = sum(st_of(f) == k for f in actionable)
    c["actionable"] = len(actionable)
    c["open_error"] = sum(f["severity"] == "ERROR" and st_of(f) in OPEN for f in fs)
    c["open_warning"] = sum(f["severity"] == "WARNING" and st_of(f) in OPEN for f in fs)
    return c


def per_doc(s: dict) -> list[dict]:
    """Findings per document (the document holding the value to fix), in document order."""
    order = {"CI": 0, "SC": 1, "BL": 2, "CO": 3}
    rows = []
    for d in s["docs"]:
        own = [f for f in s["findings"] if f["doc"] == d["name"]]
        rows.append(dict(name=d["name"], kind=d["kind"], pages=d.get("pages"), total=len(own),
                         **{sev: sum(f["severity"] == sev for f in own) for sev in SEVERITY}))
    rows.sort(key=lambda r: (order.get(r["kind"], 9), r["name"]))
    return rows


# ------------------------------------------------------------------ filters (kept outside widget keys so other pages can set them)
def reset_filters():
    for k in ("f_sev", "f_status", "f_doc", "f_q"):
        st.session_state.pop(k, None)
    for k in [k for k in st.session_state if str(k).startswith("w_")]:
        del st.session_state[k]


def show_findings(sev=None, status=None, doc=None):
    """Open the findings page with these filters (used by the dashboard numbers and tables)."""
    reset_filters()
    if sev:
        st.session_state["f_sev"] = list(sev)
    if status:
        st.session_state["f_status"] = list(status)
    if doc:
        st.session_state["f_doc"] = doc
    go("review")
