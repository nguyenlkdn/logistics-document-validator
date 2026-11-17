"""Findings of the open review: filter toolbar, document navigator, page preview with highlights, finding details.

Reviewer decisions (status, note) are stored in history.db apart from the automated findings, which are never changed.
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

from engine.history import STATUSES
from engine.rules import SEVERITY

from .. import components as ui
from .. import state
from ..i18n import kind_label, msg, note, sev_label, sev_short, status_label, t, t1, unrec_text


@st.cache_data(show_spinner=False, max_entries=20)
def page_images(path: str, mtime: float, marks: tuple) -> list[bytes]:
    """PNG of every page with the findings boxed in their severity colour (in memory; the PDF is not changed)."""
    from engine.evidence import annotated_pages
    return annotated_pages(path, marks)


def open_folder(path: str):
    if sys.platform.startswith("win"):
        os.startfile(path)                                  # noqa: S606 — local folder on the user's PC
    elif sys.platform == "darwin":
        subprocess.run(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _scroll_to(key: str):
    st.iframe(f"""<script>/* {datetime.now().timestamp()} */
    const doc = window.parent.document;
    function go(n) {{
      const el = doc.querySelector('div.st-key-{key}'), main = doc.querySelector('[data-testid="stMain"]');
      if (!el || !main) {{ if (n < 40) setTimeout(() => go(n + 1), 100); return; }}
      const y = el.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop - 70;
      if (y < main.scrollTop) main.scrollTo({{top: Math.max(0, y), behavior: 'smooth'}});
    }}
    go(0);
    </script>""", height=1)


def _pick_doc(name):
    st.session_state["f_doc"] = name


def _init(widget, source, default):
    if widget not in st.session_state:
        st.session_state[widget] = st.session_state.get(source, default)


def _clear():
    state.reset_filters()


def render():
    s = state.current()
    if not s:
        st.info(t("no_workspace"))
        if st.button(t1("start_new"), type="primary", icon=":material/upload_file:"):
            state.go("new")
        return
    cid = state.check_id()
    mk = state.marks()

    # ---- header + actions
    rev = f" · {t('rev')} {s['revision']}" if s.get("revision") else ""
    h, a = st.columns([5, 3], vertical_alignment="bottom")
    with h:
        ui.header(s["shipment"], ui.esc(t("checked_at", when=(s.get("check_ts") or s["created"]).replace("T", " ")) + rev))
    with a:
        b1, b2 = st.columns(2)
        xl = s.get("excel_path")
        if xl and Path(xl).exists():
            b1.download_button(t1("download"), Path(xl).read_bytes(), file_name=f"{s['name']}_report.xlsx",
                               icon=":material/download:", width="stretch",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if s.get("out_dir") and Path(s["out_dir"]).exists() and b2.button(t1("open_folder"), icon=":material/folder_open:",
                                                                           width="stretch"):
            open_folder(s["out_dir"])
    revision_banner(cid)
    if s.get("legacy"):
        st.caption(t("legacy"))

    # ---- filter toolbar
    _init("w_sev", "f_sev", list(SEVERITY))
    _init("w_status", "f_status", list(STATUSES))
    _init("w_q", "f_q", "")
    f1, f2, f3 = st.columns([5, 5.5, 3], vertical_alignment="bottom")
    with f1:
        sev = st.pills(t("flt_sev"), SEVERITY, selection_mode="multi", key="w_sev",
                       format_func=lambda x: f"{ui.ICON[x]} {sev_short(x)}")
    with f2:
        stt = st.pills(t("flt_status"), STATUSES, selection_mode="multi", key="w_status", format_func=status_label)
    with f3:
        q = st.text_input(t("flt_search"), key="w_q", placeholder=t1("flt_search_ph"))
    st.session_state.update(f_sev=sev, f_status=stt, f_q=q)
    sev, stt = set(sev or SEVERITY), set(stt or STATUSES)
    doc_names = [d["name"] for d in s["docs"]]
    pick = st.session_state.get("f_doc")
    if pick not in doc_names:
        pick = None

    status_of = lambda f: mk.get(f["sig"], {}).get("status", "open")
    ql = q.strip().lower()
    hit = lambda f: not ql or any(ql in str(f.get(k) or "").lower()
                                  for k in ("msg_en", "msg_vi", "current", "suggested", "key", "doc"))
    base = [f for f in s["findings"] if f["severity"] in sev and status_of(f) in stt and hit(f)]
    shown = [f for f in base if pick is None or f["doc"] == pick]

    # ---- document navigator | preview + findings
    nav, main = st.columns([1.15, 4], gap="medium")
    with nav, st.container(key="docnav"):
        ui.label(t1("k_docs"))
        st.button(f"**{t1('all_docs')}**  \n{len(base)} / {len(s['findings'])}", key="docbtn_all",
                  type="primary" if pick is None else "secondary", on_click=_pick_doc, args=(None,), width="stretch")
        for i, r in enumerate(state.per_doc(s)):
            n = {x: sum(f["severity"] == x and f["doc"] == r["name"] for f in base) for x in SEVERITY}
            counts = " ".join(f"{ui.ICON[x]}{n[x]}" for x in SEVERITY if n[x]) or "✓"
            pages = f" · {r['pages']} {t1('pages') if (r['pages'] or 0) > 1 else t1('page')}" if r["pages"] else ""
            st.button(f"**{r['name']}**  \n{kind_label(r['kind'], short=True)}{pages} · {counts}", key=f"docbtn_{i}",
                      type="primary" if pick == r["name"] else "secondary", on_click=_pick_doc, args=(r["name"],),
                      width="stretch")

    with main, st.container(key="rv_main"):
        if pick:
            preview(s, pick, sev)
        if pick != st.session_state.get("rv_last_doc"):
            st.session_state["rv_last_doc"] = pick
            if pick:
                _scroll_to("rv_main")
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        c1.caption(t("showing_n", n=len(shown), total=len(s["findings"])) + (f" · **{pick}**" if pick else ""))
        if len(shown) < len(s["findings"]):
            c2.button(t1("flt_clear"), on_click=_clear, type="tertiary", icon=":material/filter_alt_off:")
        if not s["findings"]:
            st.success(t("none"))
        elif not shown:
            st.info(t("none_match"))
        else:
            st.caption(t("legend"))
        for f in shown:
            finding(s, f, mk.get(f["sig"], dict(status="open", note="")), cid, pick)

        if s.get("unrecognised"):
            with st.expander(f"⚪ {t('unrec_title')} ({len(s['unrecognised'])})"):
                for u in s["unrecognised"]:
                    st.markdown(f"- **{ui.esc(u['doc'])}** — {ui.esc(unrec_text(u))}")


def preview(s, name, sev):
    d = next(d for d in s["docs"] if d["name"] == name)
    path = d.get("path")
    if not path or not Path(path).exists():
        st.warning(t("no_preview"))
        return
    mk = tuple(tuple(m) for m in s.get("marks", {}).get(name, []) if m[5] in sev)
    imgs = page_images(path, Path(path).stat().st_mtime, mk)
    flag = "" if d.get("is_draft") or d.get("is_draft") is None or d["kind"] in ("CI", "SC") else f" · ⚠️ {t1('not_draft')}"
    with st.expander(f"📄 {t1('preview')}: {name} — {kind_label(d['kind'])} · {len(imgs)} "
                     f"{t1('pages') if len(imgs) > 1 else t1('page')}{flag}", expanded=True):
        st.caption(t("boxes"))
        for n, png in enumerate(imgs, 1):
            st.image(png, caption=f"{t1('page')} {n} / {len(imgs)}", width="stretch")


def finding(s, f, mk, cid, pick):
    i, sig = f["no"], f["sig"]
    text = msg(f)
    badge = "" if mk["status"] == "open" else f"{status_label(mk['status'])} · "
    title = f"{ui.ICON[f['severity']]} **#{i}** {badge}{text}"
    if mk["status"] in state.DONE:
        title = f"{ui.ICON[f['severity']]} **#{i}** {badge}~~{text}~~"
    with st.expander(title, expanded=f["severity"] == "ERROR" and mk["status"] in state.OPEN):
        if cid:
            s1, s2 = st.columns([1, 2])
            new_st = s1.selectbox(t1("status"), STATUSES, index=STATUSES.index(mk["status"]), format_func=status_label,
                                  key=f"st_{cid}_{i}_{sig}")
            new_note = s2.text_input(t1("note_in"), value=mk["note"], key=f"nt_{cid}_{i}_{sig}")
            if (new_st, new_note) != (mk["status"], mk["note"]):
                state.set_mark(sig, new_st, new_note)
                st.toast(t1("saved_marks"))
                st.rerun()
        a, b = st.columns([3, 2])
        with a:
            pg = f" ({t1('page')} {f['page']})" if f.get("page") else ""
            st.markdown(f"{ui.sev_chip(f['severity'])} &nbsp; **{t1('doc')}:** {ui.esc(f['doc'])}{pg}",
                        unsafe_allow_html=True)
            if f.get("related"):
                st.markdown(f"**{t1('related')}:** " + " · ".join(f"_{ui.esc(n)}_" for n in f["related"]))
            if f.get("current") or f.get("suggested"):
                st.markdown(f"**{t1('current')}:** `{f['current']}`  \n**{t1('suggested')}:** `{f['suggested']}`")
        with b:
            n = note(f)
            if n:
                st.info(f"**{t1('note')}:** {n}")
            st.caption(f"{t1('rule')}: `{f['key']}` · {sev_label(f['severity'])}")
        has_file = any(d["name"] == f["doc"] and d.get("path") for d in s["docs"])
        if pick == f["doc"]:
            if s.get("marks", {}).get(f["doc"]) and any(m[6] == i for m in s["marks"][f["doc"]]):
                st.caption("🖍️ " + t("in_preview", n=i))
        else:
            if has_file:
                st.button(t1("show_doc"), key=f"go_{cid}_{i}_{sig}", icon=":material/find_in_page:",
                          on_click=_pick_doc, args=(f["doc"],))
            for p in f.get("evidence_paths", []):
                if Path(p).exists():
                    st.image(p, width="stretch")


def revision_banner(cid):
    if not cid:
        return
    cmp = state.HIST.compare(cid)
    if not cmp:
        return
    c = state.HIST.check(cid)
    st.info(t("rev_info", rev=c["revision"], ship=c["shipment"], prev=cmp["prev_revision"], res=len(cmp["resolved"]),
              still=len(cmp["still"]), new=len(cmp["new"])), icon=":material/compare_arrows:")
    if cmp["resolved"]:
        with st.expander(f"✔ {t('resolved_prev')} ({len(cmp['resolved'])})"):
            for f in cmp["resolved"]:
                st.markdown(f"- ~~{ui.esc(msg(f))}~~ — {ui.esc(f['doc'])}")
