"""Page viewer for the review workspace: one rendered page + HTML overlays (finding boxes, search hits) + a transparent
text layer so the text can be selected and copied. The PDF itself is only read; nothing is drawn into it.

Positions are kept in PDF points and placed in % of the page, so boxes stay on their value at every zoom level.
"""
import base64
import html
from datetime import datetime
from pathlib import Path

import streamlit as st

from .components import COLOR
from .i18n import t1

ZOOMS = ["fit_width", "fit_page", 100, 150, 200]
VIEW_H = "calc(100vh - 17rem)"          # viewer height: fills the window under the toolbars


@st.cache_data(show_spinner=False, max_entries=8)
def doc_info(path: str, mtime: float) -> list[tuple[float, float]]:
    """(width, height) in points of every page."""
    import pymupdf
    with pymupdf.open(path) as pdf:
        return [(p.rect.width, p.rect.height) for p in pdf]


@st.cache_data(show_spinner=False, max_entries=48)
def page_image(path: str, mtime: float, pno: int, dpi: int) -> str:
    """Base64 PNG of one page (rendered on demand, cached per page and resolution)."""
    import pymupdf
    with pymupdf.open(path) as pdf:
        return base64.b64encode(pdf[pno].get_pixmap(dpi=dpi).tobytes("png")).decode()


@st.cache_data(show_spinner=False, max_entries=48)
def page_lines(path: str, mtime: float, pno: int) -> list[tuple]:
    """Text lines of a page with their box, for the selectable text layer: (x0, y0, x1, y1, text)."""
    import pymupdf
    with pymupdf.open(path) as pdf:
        words = pdf[pno].get_text("words")
    lines = {}
    for x0, y0, x1, y1, w, b, ln, _ in words:
        lines.setdefault((b, ln), []).append((x0, y0, x1, y1, w))
    out = []
    for ws in lines.values():
        x0, y0 = min(w[0] for w in ws), min(w[1] for w in ws)
        x1, y1 = max(w[2] for w in ws), max(w[3] for w in ws)
        if y1 - y0 < 30:                                      # skip rotated watermarks and the like
            out.append((x0, y0, x1, y1, " ".join(w[4] for w in sorted(ws))))
    return out


@st.cache_data(show_spinner=False, max_entries=16)
def search(path: str, mtime: float, query: str) -> dict[int, list[tuple]]:
    """Every occurrence of query (case-insensitive), by page."""
    import pymupdf
    hits = {}
    with pymupdf.open(path) as pdf:
        for pno, page in enumerate(pdf):
            rects = page.search_for(query)
            if rects:
                hits[pno] = [(r.x0, r.y0, r.x1, r.y1) for r in rects]
    return hits


def dpi_for(zoom) -> int:
    return 200          # also at "fit": the page can be zoomed in the browser (zoom_on_page) and should stay sharp


def _pct(b, w, h, pad=0.0):
    x0, y0, x1, y1 = b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad
    return f"left:{100 * x0 / w:.3f}%;top:{100 * y0 / h:.3f}%;width:{100 * (x1 - x0) / w:.3f}%;height:{100 * (y1 - y0) / h:.3f}%"


def _rgba(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def render(path: str, pno: int, zoom, boxes: list[dict], hits: list[tuple]):
    """boxes: [{bbox, sev, no, role, focus, title}] on this page; hits: search boxes on this page."""
    mtime = Path(path).stat().st_mtime
    w, h = doc_info(path, mtime)[pno]
    img = page_image(path, mtime, pno, dpi_for(zoom))
    if zoom == "fit_width":
        width = "100%"
    elif zoom == "fit_page":
        width = f"min(100%, calc(({VIEW_H} - 26px) * {w / h:.4f}))"
    else:
        width = f"{w * 96 / 72 * zoom / 100:.0f}px"
    parts = [f'<img src="data:image/png;base64,{img}" alt="page {pno + 1}">']
    for b in hits:
        parts.append(f'<div class="ldv-hit" style="{_pct(b, w, h)}"></div>')
    for b in sorted(boxes, key=lambda b: b.get("focus", False)):     # the selected finding on top
        col = COLOR["RESOLVED"] if b["role"] == "ref" else COLOR.get(b["sev"], COLOR["ERROR"])
        cls = "ldv-box" + (" ldv-ref" if b["role"] == "ref" else "") + (" ldv-focus" if b.get("focus") else "")
        style = f"{_pct(b['bbox'], w, h, 2.5)};border-color:{col};background:{_rgba(col, .10 if b.get('focus') else .04)}"
        if b.get("focus"):
            style += f";box-shadow:0 0 0 4px {_rgba(col, .25)}"
        tag = f'<span class="ldv-tag" style="background:{col}">#{b["no"]}</span>' if b.get("no") else ""
        parts.append(f'<div class="{cls}" style="{style}" title="{html.escape(b.get("title", ""))}">{tag}</div>')
    text = []
    for x0, y0, x1, y1, s in page_lines(path, mtime, pno):
        fs = 100 * (y1 - y0) / w * 0.86
        text.append(f'<span style="{_pct((x0, y0, x1, y1), w, h)};font-size:{fs:.3f}cqw">{html.escape(s)}</span><br>')
    parts.append(f'<div class="ldv-text">{"".join(text)}</div>')
    zbar = ('<div class="ldv-zbar"><div>'
            f'<button type="button" data-ldvz="out" title="{html.escape(t1("zoom_out"))}">−</button>'
            f'<button type="button" data-ldvz="reset" class="ldv-zpct" title="{html.escape(t1("zoom_reset"))}"></button>'
            f'<button type="button" data-ldvz="in" title="{html.escape(t1("zoom_in"))}">+</button></div></div>')
    st.markdown(f'<div class="ldv-viewer" tabindex="0" style="height:{VIEW_H}">{zbar}'
                f'<div class="ldv-page" style="width:{width}" data-wpt="{w:.2f}" data-key="{html.escape(f"{path}|{zoom}")}">'
                f'{"".join(parts)}</div></div>', unsafe_allow_html=True)


def zoom_on_page():
    """Zoom on the page itself, in the browser (no reload): Ctrl + mouse wheel or touchpad pinch zooms around the
    pointer; the -/%/+ buttons in the viewer corner, or + - 0 while the viewer has the focus. The extra zoom is a
    factor on top of the toolbar zoom: it is kept across pages of the same document and reset when the toolbar
    zoom or the document changes."""
    st.iframe("""<script>
    const w = window.parent, doc = w.document;
    if (!w.__ldvZoom) {
      w.__ldvZoom = true;
      const s = doc.createElement('script');
      s.textContent = `(() => {
        const Z = {f: 1, key: null}, MIN = 0.25, MAX = 6;
        const page = () => document.querySelector('.ldv-page[data-wpt]');
        function apply() {
          const p = page(); if (!p) return;
          if (p.dataset.key !== Z.key) { Z.key = p.dataset.key; Z.f = 1; }
          if (!p.dataset.base) { p.dataset.orig = p.style.width; p.dataset.base = p.getBoundingClientRect().width; }
          if (p.dataset.f !== String(Z.f)) {
            p.style.width = Z.f === 1 ? p.dataset.orig : (p.dataset.base * Z.f) + 'px';
            p.dataset.f = String(Z.f);
          }
          const lbl = document.querySelector('.ldv-zpct');
          if (lbl) lbl.textContent = Math.round(100 * p.getBoundingClientRect().width / (p.dataset.wpt * 96 / 72)) + '%';
        }
        function zoomTo(f, cx, cy) {
          const p = page(), v = p && p.closest('.ldv-viewer'); if (!v) return;
          f = Math.min(MAX, Math.max(MIN, f));
          if (Math.abs(f - 1) < 0.03) f = 1;
          const vr = v.getBoundingClientRect();
          if (cx === undefined) { cx = vr.left + vr.width / 2; cy = vr.top + vr.height / 2; }
          const r = p.getBoundingClientRect(), rx = (cx - r.left) / r.width, ry = (cy - r.top) / r.height;
          Z.f = f; apply();
          const r2 = p.getBoundingClientRect();          // keep the point under the pointer where it was
          v.scrollLeft += r2.left + rx * r2.width - cx;
          v.scrollTop += r2.top + ry * r2.height - cy;
        }
        document.addEventListener('wheel', e => {
          if (!e.ctrlKey || !e.target.closest || !e.target.closest('.ldv-viewer')) return;
          e.preventDefault();                            // not the browser zoom
          zoomTo(Z.f * Math.exp(-Math.max(-100, Math.min(100, e.deltaY)) * 0.004), e.clientX, e.clientY);
        }, {passive: false, capture: true});
        document.addEventListener('click', e => {
          const b = e.target.closest && e.target.closest('[data-ldvz]'); if (!b) return;
          e.preventDefault();
          const a = b.dataset.ldvz;
          zoomTo(a === 'reset' ? 1 : Z.f * (a === 'in' ? 1.25 : 0.8));
        }, true);
        document.addEventListener('keydown', e => {
          const a = document.activeElement;
          if (e.ctrlKey || e.altKey || e.metaKey || !a || !a.closest || !a.closest('.ldv-viewer')) return;
          const k = {'+': 1.25, '=': 1.25, '-': 0.8, '0': 0}[e.key];
          if (k === undefined) return;
          e.preventDefault(); zoomTo(k ? Z.f * k : 1);
        });
        let queued = false;                              // the page is drawn again after every rerun
        new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; apply(); }); } })
          .observe(document.body, {childList: true, subtree: true});
        apply();
      })();`;
      doc.head.appendChild(s);
    }
    </script>""", height=1)


def scroll_to_focus():
    """Bring the selected finding's box into view inside the viewer (runs once per selection)."""
    st.iframe(f"""<script>/* {datetime.now().timestamp()} */
    const doc = window.parent.document;
    function go(n) {{
      const el = doc.querySelector('.ldv-focus'), v = doc.querySelector('.ldv-viewer');
      if (!el || !v) {{ if (n < 30) setTimeout(() => go(n + 1), 100); return; }}
      const er = el.getBoundingClientRect(), vr = v.getBoundingClientRect();
      v.scrollTo({{top: v.scrollTop + er.top - vr.top - vr.height / 2 + er.height / 2,
                   left: v.scrollLeft + er.left - vr.left - vr.width / 2 + er.width / 2, behavior: 'smooth'}});
    }}
    go(0);
    </script>""", height=1)


def keyboard():
    """↑/↓ (or k/j) = previous/next finding, Esc = close the finding panel. Ignored while typing in a field or
    while the page viewer has the focus (there the arrow keys scroll the page)."""
    st.iframe("""<script>
    const w = window.parent, doc = w.document;
    if (!w.__ldvKeys) {
      w.__ldvKeys = true;
      const s = doc.createElement('script');
      s.textContent = `document.addEventListener('keydown', e => {
        const a = document.activeElement;
        if (e.ctrlKey || e.altKey || e.metaKey) return;
        if (a && (a.isContentEditable || /INPUT|TEXTAREA|SELECT/.test(a.tagName) || a.closest('.ldv-viewer'))) return;
        const map = {ArrowDown: 'fnext', j: 'fnext', ArrowUp: 'fprev', k: 'fprev', Escape: 'fclose'};
        const key = map[e.key]; if (!key) return;
        const b = document.querySelector('div.st-key-' + key + ' button');
        if (b && !b.disabled) { e.preventDefault(); b.click(); }
      });`;
      doc.head.appendChild(s);
    }
    </script>""", height=1)
