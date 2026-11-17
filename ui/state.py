"""Application state shared by the pages: the open review session, its reviewer marks, filters, navigation."""
from pathlib import Path

import streamlit as st

import json

from engine import check, master, report_root, session
from engine.history import DONE, OPEN, STATUSES, History
from engine.rules import SEVERITY

APP = Path(__file__).resolve().parent.parent
VERSION = (APP / "VERSION").read_text(encoding="utf-8").strip() if (APP / "VERSION").exists() else "dev"
HIST = History(report_root() / "history.db")
PAGES: dict = {}                     # key -> st.Page, filled by app.py
# ------------------------------------------------------------------ local UI settings (no login: the name is typed once)
def _ui_file() -> Path:
    return master.data_dir() / "ui_settings.json"


def ui_settings() -> dict:
    try:
        return json.loads(_ui_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ui_settings(**kw):
    d = ui_settings() | kw
    _ui_file().parent.mkdir(parents=True, exist_ok=True)
    _ui_file().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def reviewer() -> str:
    return ui_settings().get("reviewer", "")


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
    for k in ("f_doc", "f_sel", "f_scope", "v_page", "v_find", "v_focus_last"):
        st.session_state.pop(k, None)
    return True


def run_check(paths: list[Path], name: str | None = None, kinds: dict | None = None) -> int:
    res = check(paths, name=name, kinds=kinds)
    cid = HIST.record(res, VERSION)
    open_check(cid)
    return cid


def marks() -> dict:
    """sig -> {status, note} for the open review (reviewer decisions, stored apart from the findings)."""
    s = current()
    return HIST.marks(s["shipment"]) if s else {}


def set_mark(sig: str, status: str, note: str, shipment: str | None = None) -> bool:
    return HIST.set_mark(shipment or current()["shipment"], sig, status, note, who=reviewer())


def counts(s: dict, mk: dict | None = None) -> dict:
    mk = marks() if mk is None else mk
    fs = s["findings"]
    st_of = lambda f: mk.get(f["sig"], {}).get("status", "open")
    c = {sev: sum(f["severity"] == sev for f in fs) for sev in SEVERITY}
    c["total"] = len(fs)
    actionable = [f for f in fs if f["severity"] != "INFO"]
    for k in STATUSES:
        c[k] = sum(st_of(f) == k for f in actionable)
    c["todo"] = sum(c[k] for k in ("open", "in_review"))
    c["done"] = sum(c[k] for k in DONE)
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


def open_finding(cid: int, no: int) -> bool:
    """Open a review in the workspace with one finding selected (its document and page shown)."""
    if not open_check(cid):
        return False
    s = current()
    f = next((x for x in s["findings"] if x["no"] == no), None)
    if f:
        from .views.review import target
        doc, page = target(s, f)
        st.session_state.update(f_sel=no, f_doc=doc, v_page=page, f_scope="all")
    go("review")
    return True


def show_findings(sev=None, status=None, doc=None):
    """Open the findings page with these filters (used by the dashboard numbers and tables)."""
    reset_filters()
    st.session_state["f_scope"] = "doc" if doc else "all"
    st.session_state.pop("f_sel", None)
    if sev:
        st.session_state["f_sev"] = list(sev)
    if status:
        st.session_state["f_status"] = list(status)
    if doc:
        st.session_state.update(f_doc=doc, v_page=1)
    go("review")
