"""Review workspace: documents | page viewer | findings.

- Left: the documents of the package with page and finding counts.
- Centre: the original page (read only) with every finding boxed in its severity colour, the selected finding
  emphasised, reference values in dashed green, search hits in yellow, and selectable text.
- Right: the selected finding (found vs expected value, document, evidence locations, rule note, reviewer status and
  note) above the list of findings. Clicking a finding opens its document at its page and centres its box.

Only boxes recorded by the analysis are drawn; a finding without a location is shown without inventing one.
Reviewer decisions (status, note) are stored in history.db, apart from the automated findings.
"""
import os
import subprocess
import sys
from pathlib import Path

import streamlit as st

from engine.history import STATUSES
from engine.rules import SEVERITY
from engine.session import ref_docs, wrong_docs

from .. import components as ui
from .. import state, viewer
from ..i18n import T, kind_label, msg, note, sev_short, status_label, t, t1, unrec_text


def open_folder(path: str):
    if sys.platform.startswith("win"):
        os.startfile(path)                                  # noqa: S606 — local folder on the user's PC
    elif sys.platform == "darwin":
        subprocess.run(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ------------------------------------------------------------------ locations
def locs_of(s: dict, f: dict) -> list[dict]:
    """Where the finding sits: stored locations, or (reviews saved before they were stored) the preview marks."""
    if "locs" in f:
        return f["locs"]
    return [dict(doc=doc, page=m[0], bbox=list(m[1:5]), role="wrong")
            for doc, ms in s.get("marks", {}).items() for m in ms if m[6] == f["no"]]


def target(s: dict, f: dict, stay: str | None = None) -> tuple[str, int]:
    """Document and 1-based page to show for a finding: its first 'wrong' location (in document `stay` if
    it has one there), else its document/page."""
    ls = locs_of(s, f)
    first = next((l for l in ls if l["role"] == "wrong" and l["doc"] == stay), None) or \
        next((l for l in ls if l["role"] == "wrong"), ls[0] if ls else None)
    if first:
        return first["doc"], first["page"] + 1
    return f["doc"], f.get("page") or 1


# ------------------------------------------------------------------ callbacks (run before the page is drawn)
def _pick_doc(name):
    if st.session_state.get("f_doc") != name:
        st.session_state.update(f_doc=name, v_page=1)


def _go(doc, page):
    st.session_state.update(f_doc=doc, v_page=page)


def _select(no, s):
    f = next((x for x in s["findings"] if x["no"] == no), None)
    if not f:
        return
    doc, page = target(s, f, st.session_state.get("f_doc") if st.session_state.get("f_scope") == "doc" else None)
    st.session_state.update(f_sel=no, f_doc=doc, v_page=page)


def _step(order: list[int], delta: int, s):
    if not order:
        return
    cur = st.session_state.get("f_sel")
    i = order.index(cur) + delta if cur in order else (0 if delta > 0 else len(order) - 1)
    _select(order[max(0, min(len(order) - 1, i))], s)


def _page(delta, n):
    st.session_state["v_page"] = max(1, min(n, st.session_state.get("v_page", 1) + delta))


def _close():
    st.session_state["f_sel"] = None


def _scope(key):
    st.session_state["f_scope"] = st.session_state.get(key) or st.session_state.get("f_scope", "all")


def _init(widget, source, default):
    if widget not in st.session_state:
        st.session_state[widget] = st.session_state.get(source, default)


# ------------------------------------------------------------------ page
def render():
    s = state.current()
    if not s:
        st.info(t("no_workspace"))
        if st.button(t1("start_new"), type="primary", icon=":material/upload_file:"):
            state.go("new")
        return
    st.markdown("<style>.block-container {max-width: none; padding-left: 2rem; padding-right: 2rem;}</style>",
                unsafe_allow_html=True)
    cid, mk = state.check_id(), state.marks()

    # ---- header + actions
    rev = f" · {t('rev')} {s['revision']}" if s.get("revision") else ""
    h, a = st.columns([5, 3], vertical_alignment="bottom")
    with h:
        ui.header(s["shipment"], ui.esc(t("checked_at", when=(s.get("check_ts") or s["created"]).replace("T", " ")) + rev))
    with a:
        b1, b2 = st.columns(2)
        xl = s.get("excel_path")
        if xl and Path(xl).exists():
            b1.download_button(t1("download"), lambda xl=xl: Path(xl).read_bytes(), file_name=f"{s['name']}_report.xlsx",
                               icon=":material/download:", width="stretch",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if s.get("out_dir") and Path(s["out_dir"]).exists() and b2.button(
                t1("open_folder"), icon=":material/folder_open:", width="stretch"):
            open_folder(s["out_dir"])
    revision_banner(cid)
    if s.get("legacy"):
        st.caption(t("legacy"))

    # ---- filters
    _init("w_sev", "f_sev", list(SEVERITY))
    _init("w_status", "f_status", list(STATUSES))
    _init("w_q", "f_q", "")
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):      # wraps on narrow screens
        sev = st.pills(t("flt_sev"), SEVERITY, selection_mode="multi", key="w_sev", width="content",
                       format_func=lambda x: f"{ui.ICON[x]} {sev_short(x)}")
        stt = st.pills(t("flt_status"), STATUSES, selection_mode="multi", key="w_status", format_func=status_label,
                       width="content")
        q = st.text_input(t("flt_search"), key="w_q", placeholder=t1("flt_search_ph"), width=260)
    st.session_state.update(f_sev=sev, f_status=stt, f_q=q)
    sev, stt = set(sev or SEVERITY), set(stt or STATUSES)
    status_of = lambda f: mk.get(f["sig"], {}).get("status", "open")
    ql = q.strip().lower()
    hit = lambda f: not ql or any(ql in str(f.get(k) or "").lower()
                                  for k in ("msg_en", "msg_vi", "current", "suggested", "key", "doc")) or any(ql in n.lower() for n in wrong_docs(f))
    base = [f for f in s["findings"] if f["severity"] in sev and status_of(f) in stt and hit(f)]

    # ---- current document / finding
    docs = state.per_doc(s)
    names = [d["name"] for d in docs]
    if st.session_state.get("f_doc") not in names:
        first = next((f["doc"] for f in base if f["doc"] in names), names[0] if names else None)
        st.session_state.update(f_doc=first, v_page=1)
    doc = st.session_state.get("f_doc")
    scope = st.session_state.get("f_scope", "all")
    listed = [f for f in base if scope == "all" or doc in wrong_docs(f)]
    sel = next((f for f in s["findings"] if f["no"] == st.session_state.get("f_sel")), None)

    nav, view, panel = st.columns([1.05, 3.3, 2.15], gap="small")
    with nav, st.container(key="docnav"):
        ui.label(t1("k_docs"))
        for i, r in enumerate(docs):
            n = {x: sum(f["severity"] == x and r["name"] in wrong_docs(f) for f in base) for x in SEVERITY}
            counts = " ".join(f"{ui.ICON[x]}{n[x]}" for x in SEVERITY if n[x]) or "✓"
            pages = f" · {r['pages']} {t1('pages') if (r['pages'] or 0) > 1 else t1('page')}" if r["pages"] else ""
            mine = " ✎" if next((d for d in s["docs"] if d["name"] == r["name"]), {}).get("kind_set_by_user") else ""
            st.button(f"**{r['name']}**  \n{kind_label(r['kind'], short=True, form=r.get('form', ''))}{mine}{pages} · {counts}", key=f"docbtn_{i}",
                      type="primary" if doc == r["name"] else "secondary", on_click=_pick_doc, args=(r["name"],),
                      width="stretch")
        if s.get("unrecognised"):
            with st.popover(f"{t1('k_unrec')} ({len(s['unrecognised'])})", width="stretch"):
                for u in s["unrecognised"]:
                    st.markdown(f"- **{ui.esc(u['doc'])}** — {ui.esc(unrec_text(u))}")
    with view:
        page_view(s, doc, sel, base)
    with panel:
        finding_panel(s, sel, listed, base, mk, cid, doc, scope)
    viewer.keyboard()
    viewer.zoom_on_page()


# ------------------------------------------------------------------ centre: page viewer
def page_view(s, doc, sel, base):
    d = next((x for x in s["docs"] if x["name"] == doc), None)
    path = d.get("path") if d else None
    if not path or not Path(path).exists():
        st.warning(t("no_preview"))
        return
    mtime = Path(path).stat().st_mtime
    n = len(viewer.doc_info(path, mtime))
    st.session_state["v_page"] = max(1, min(n, st.session_state.get("v_page", 1)))
    pno = st.session_state["v_page"] - 1
    if not st.session_state.get("v_zoom"):
        st.session_state["v_zoom"] = "fit_width"

    on_page = {}
    for f in base:
        for l in locs_of(s, f):
            if l["doc"] == doc and l["role"] == "wrong":
                on_page.setdefault(l["page"], set()).add(f["no"])
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):      # wraps on narrow screens
        st.button(t1("pg_prev"), icon=":material/chevron_left:", key="pg_prev", on_click=_page, args=(-1, n),
                  disabled=pno == 0, help=t1("pg_prev"), width="content")
        st.selectbox(t1("page"), list(range(1, n + 1)), key="v_page", label_visibility="collapsed", width=170,
                     format_func=lambda p: f"{t1('page').capitalize()} {p} / {n}"
                                           + (f"  ·  {len(on_page[p - 1])} ⚑" if on_page.get(p - 1) else ""))
        st.button(t1("pg_next"), icon=":material/chevron_right:", key="pg_next", on_click=_page, args=(1, n),
                  disabled=pno >= n - 1, help=t1("pg_next"), width="content")
        st.segmented_control(t1("zoom"), viewer.ZOOMS, key="v_zoom", label_visibility="collapsed", width="content",
                             format_func=lambda z: {"fit_width": t1("fit_width"), "fit_page": t1("fit_page")}.get(z, f"{z}%"))
    zoom = st.session_state.get("v_zoom") or "fit_width"

    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        find = st.text_input(t1("find_in_doc"), key="v_find", placeholder=t1("find_in_doc"), label_visibility="collapsed",
                             icon=":material/search:", width="stretch").strip()
        st.download_button(t1("orig_pdf"), lambda path=path: Path(path).read_bytes(), file_name=doc,
                           mime="application/pdf", icon=":material/picture_as_pdf:", width="content", key="dl_pdf",
                           help=t1("orig_pdf_help"))
    hits = viewer.search(path, mtime, find) if len(find) >= 2 else {}
    if len(find) >= 2:
        if hits:
            pages = sorted(hits)
            st.caption(t1("find_hits", n=sum(len(v) for v in hits.values()), pages=", ".join(str(p + 1) for p in pages)))
            if pno not in hits:
                for col, p in zip(st.columns(min(len(pages), 8)), pages[:8]):
                    col.button(f"{t1('page')} {p + 1}", key=f"hitpg_{p}", on_click=_go, args=(doc, p + 1),
                               type="tertiary")
        else:
            st.caption(t1("find_none"))

    boxes, tagged = [], set()
    for f in base + ([sel] if sel and sel not in base else []):
        focus = sel is not None and f["no"] == sel["no"]
        for l in locs_of(s, f):
            if l["doc"] != doc or l["page"] != pno or (l["role"] == "ref" and not focus):
                continue
            tag = l["role"] == "wrong" and f["no"] not in tagged          # one "#n" per finding and page
            if tag:
                tagged.add(f["no"])
            boxes.append(dict(bbox=l["bbox"], sev=f["severity"], role=l["role"], focus=focus, fno=f["no"],
                              no=f["no"] if tag else None,
                              title=f"#{f['no']} {msg(f)}" + (f" — {t1('ref_value')}" if l["role"] == "ref" else "")))
    token = f"{sel['no']}|{doc}|{pno}|{zoom}" if sel else ""
    viewer.render(path, pno, zoom, boxes, hits.get(pno, []), token)
    with st.container(key="boxsel"):                      # hidden: clicking a box on the page presses one of these
        for no in sorted({b["fno"] for b in boxes}):
            st.button(f"#{no}", key=f"boxsel_{no}", on_click=st.session_state.update, kwargs=dict(f_sel=no))
    st.caption(t("boxes_v2"))
    st.caption(t("zoom_hint"))
    if sel and st.session_state.get("v_focus_last") != (sel["no"], doc, pno, zoom):
        st.session_state["v_focus_last"] = (sel["no"], doc, pno, zoom)
        if any(b["focus"] for b in boxes):
            viewer.scroll_to_focus(token)


# ------------------------------------------------------------------ right: finding detail + list
def finding_panel(s, sel, listed, base, mk, cid, doc, scope):
    order = [f["no"] for f in listed]
    if sel:
        detail(s, sel, mk.get(sel["sig"], dict(status="open", note="")), cid, order)
    else:
        st.caption(t("pick_finding"))

    top = st.columns([2, 3], vertical_alignment="center")
    top[0].markdown(f'<div class="ldv-label">{ui.esc(t1("k_findings"))} · {len(listed)}</div>', unsafe_allow_html=True)
    key = f"w_scope_{scope}"
    top[1].segmented_control(t1("scope"), ["doc", "all"], default=scope, key=key, label_visibility="collapsed",
                             width="stretch", on_change=_scope, args=(key,),
                             format_func=lambda k: t1("scope_doc") if k == "doc" else t1("scope_all"))
    if not s["findings"]:
        st.success(t("none"))
        return
    if not listed:
        st.info(t("none_match"))
        if len(base) < len(s["findings"]):
            st.button(t1("flt_clear"), on_click=state.reset_filters, type="tertiary", icon=":material/filter_alt_off:")
        return
    with st.container(height=380 if sel else 620, border=False):
        for f in listed:
            m = mk.get(f["sig"], {}).get("status", "open")
            text = msg(f)
            text = text if len(text) <= 110 else text[:107] + "…"
            badge = "" if m == "open" else f" · _{status_label(m)}_"
            label = f"{ui.ICON[f['severity']]} **#{f['no']}** {'~~' + text + '~~' if m in state.DONE else text}{badge}"
            if scope == "all" and doc not in wrong_docs(f):
                more = f" +{len(wrong_docs(f)) - 1}" if len(wrong_docs(f)) > 1 else ""
                label += f"  \n_{kind_label(f['doc_kind'], short=True, form=f.get('doc_form', ''))} · {f['doc']}{more}_"
            st.button(label, key=f"fbtn_{f['no']}", on_click=_select, args=(f["no"], s), width="stretch",
                      type="primary" if sel and sel["no"] == f["no"] else "secondary")


def detail(s, f, mk, cid, order):
    with st.container(border=True):
        h, b = st.columns([3, 2], vertical_alignment="center")
        h.markdown(f"{ui.sev_chip(f['severity'])} {ui.chip(status_label(mk['status']), ui.STATUS_COLOR.get(mk['status'], 'MUTED'))}"
                   f" &nbsp;<span style='color:#5f6368;font-size:.85rem'>#{f['no']}</span>", unsafe_allow_html=True)
        with b:
            x, y, z = st.columns(3, gap="small")
            i = order.index(f["no"]) if f["no"] in order else -1
            with x, st.container(key="fprev"):
                st.button(t1("prev_finding"), icon=":material/keyboard_arrow_up:", on_click=_step, args=(order, -1, s),
                          disabled=i == 0 or not order, help=t1("prev_finding"), width="stretch")
            with y, st.container(key="fnext"):
                st.button(t1("next_finding"), icon=":material/keyboard_arrow_down:", on_click=_step, args=(order, 1, s),
                          disabled=i == len(order) - 1 or not order, help=t1("next_finding"), width="stretch")
            with z, st.container(key="fclose"):
                st.button(t1("close_panel"), icon=":material/close:", on_click=_close, help=t1("close_panel"), width="stretch")
        st.markdown(f'<div style="font-weight:620;font-size:1rem;line-height:1.35;margin:.1rem 0 .4rem 0">'
                    f'{ui.esc(msg(f))}</div>', unsafe_allow_html=True)
        if f.get("suspect"):                     # P5: built on a possibly misread value
            why = " ".join(t(f"suspect_{w.strip()}") for w in f["suspect"].split(",") if f"suspect_{w.strip()}" in T)
            st.warning(t("suspect") + (f" {why}" if why else ""), icon=":material/help:")

        rows = [(t1("doc"), "<br>".join(ui.esc(n) + (f" · {t1('page')} {f['page']}" if n == f["doc"] and f.get("page") else "")
                                        for n in wrong_docs(f)))]
        if f.get("current") or f.get("suggested"):
            rows.append((t1("found"), f'<span class="ldv-val" style="background:{ui.TINT["ERROR"]}">'
                                      f'{ui.esc(f["current"]) or "—"}</span>'))
            rows.append((t1("expected"), f'<span class="ldv-val" style="background:{ui.TINT["RESOLVED"]}">'
                                         f'{ui.esc(f["suggested"]) or "—"}</span>'))
        if ref_docs(f):
            rows.append((t1("related"), " · ".join(ui.esc(n) for n in ref_docs(f))))
        rows.append((t1("rule"), f"<code>{ui.esc(f['key'])}</code>"))
        st.markdown('<div class="ldv-kv">' + "".join(f'<div class="k">{ui.esc(k)}</div><div>{v}</div>' for k, v in rows)
                    + "</div>", unsafe_allow_html=True)

        ls = locs_of(s, f)
        if ls:
            ui.label(t1("evidence_at"))
            seen = []
            for l in ls:
                k = (l["doc"], l["page"], l["role"])
                if k in seen:
                    continue
                seen.append(k)
                role = t1("wrong_value") if l["role"] == "wrong" else t1("ref_value")
                st.button(f"{'🟥' if l['role'] == 'wrong' else '🟩'} {l['doc']} · {t1('page')} {l['page'] + 1} — {role}",
                          key=f"ev_{f['no']}_{len(seen)}", on_click=_go, args=(l["doc"], l["page"] + 1),
                          type="tertiary")
        else:
            st.caption(t("legacy") if s.get("legacy") else t("no_location"))
        n = note(f)
        if n:
            ui.label(t1("action"))
            st.markdown(n)
        if cid:
            s1, s2 = st.columns([1, 1.6])
            new_st = s1.selectbox(t1("status"), STATUSES, index=STATUSES.index(mk["status"]), format_func=status_label,
                                  key=f"st_{cid}_{f['no']}_{f['sig']}")
            new_note = s2.text_input(t1("note_in"), value=mk["note"], key=f"nt_{cid}_{f['no']}_{f['sig']}")
            if (new_st, new_note) != (mk["status"], mk["note"]):
                state.set_mark(f["sig"], new_st, new_note)
                st.toast(t1("saved_marks"))
                st.rerun()
            trail = state.HIST.log(s["shipment"], f["sig"])
            if trail:
                with st.expander(f"{t1('activity')} ({len(trail)})"):
                    activity(trail)
        crops = [p for p in f.get("evidence_paths", []) if Path(p).exists()]
        if crops:
            with st.expander(f"{t1('snapshots')} ({len(crops)})"):
                st.caption(t("legend"))
                for p in crops:
                    st.image(p, width="stretch")


def activity(trail: list[dict]):
    """Reviewer trail of one finding: when, who, status change, note."""
    for e in trail:
        who = f" · <b>{ui.esc(e['who'])}</b>" if e.get("who") else ""
        change = (f"{ui.esc(status_label(e['old_status']))} → <b>{ui.esc(status_label(e['status']))}</b>"
                  if e["old_status"] != e["status"] else t1("note_changed"))
        line = f"<span style='color:#5f6368'>{e['ts'].replace('T', ' ')}</span>{who} · {change}"
        if e.get("note"):
            line += f"<br><span style='color:#3c4043'>“{ui.esc(e['note'])}”</span>"
        st.markdown(f"<div style='font-size:.83rem;margin-bottom:.35rem'>{line}</div>", unsafe_allow_html=True)


def revision_banner(cid):
    if not cid:
        return
    cmp = state.HIST.compare(cid)
    if not cmp:
        return
    c = state.HIST.check(cid)
    with st.expander(t("rev_info", rev=c["revision"], ship=c["shipment"], prev=cmp["prev_revision"],
                       res=len(cmp["resolved"]), still=len(cmp["still"]), new=len(cmp["new"])),
                     icon=":material/compare_arrows:"):
        if not cmp["resolved"]:
            st.caption("—")
        for f in cmp["resolved"]:
            st.markdown(f"- ~~{ui.esc(msg(f))}~~ — {ui.esc(f['doc'])}")
