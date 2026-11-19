"""Page screenshots for each finding: red box = wrong value, green box = reference value."""
from collections import OrderedDict
from pathlib import Path

import pymupdf

RED, GREEN = (0.86, 0.1, 0.1), (0.1, 0.6, 0.2)
SEV_COLOR = dict(ERROR=(0.86, 0.1, 0.1), WARNING=(0.93, 0.5, 0.05), MINOR=(0.8, 0.62, 0.0), INFO=(0.15, 0.4, 0.85))
DPI = 150
CONTEXT = 90          # points of page shown above/below the boxes


def _rects(page, loc):
    if loc.text:
        clip = pymupdf.Rect(loc.clip) + (-2, -2, 2, 2) if loc.clip else None
        hits = page.search_for(loc.text, clip=clip)
        if hits:
            r = pymupdf.Rect(hits[0])
            for h in hits[1:]:                       # one visual run may come back in pieces
                if abs(h.y0 - hits[0].y0) < 2:
                    r |= h
            return [r]
    return [pymupdf.Rect(loc.clip)] if loc.clip else []


def _resolve_page(pdf, loc):
    if loc.page is not None:
        return loc.page
    for pno, page in enumerate(pdf):
        if loc.text and page.search_for(loc.text):
            return pno
    return None


def marks(findings) -> dict:
    """Where each finding's value to check sits: document name -> [(page, x0, y0, x1, y1, severity, number)].
    Computed while the checked PDFs still exist; used to highlight findings on the full-page preview."""
    out, pdfs = {}, {}
    for no, f in enumerate(findings, 1):
        for loc in f.locs:
            if loc.role != "wrong":
                continue
            pdf = pdfs.setdefault(loc.doc.path, pymupdf.open(loc.doc.path))
            pno = _resolve_page(pdf, loc)
            if pno is None:
                continue
            for r in _rects(pdf[pno], loc):
                out.setdefault(loc.doc.name, []).append((pno, r.x0, r.y0, r.x1, r.y1, f.severity, no))
    for pdf in pdfs.values():
        pdf.close()
    return out


def locations(findings) -> list[list[dict]]:
    """Every located value of every finding: [{doc, page (0-based), bbox, role}] per finding, role = wrong | ref.
    Unlike marks(), reference values (green) are kept too, so a viewer can show both sides of a comparison."""
    out, pdfs = [], {}
    for f in findings:
        locs = []
        for loc in f.locs:
            pdf = pdfs.setdefault(loc.doc.path, pymupdf.open(loc.doc.path))
            pno = _resolve_page(pdf, loc)
            if pno is None:
                continue
            for r in _rects(pdf[pno], loc):
                locs.append(dict(doc=loc.doc.name, page=pno, bbox=[round(r.x0, 1), round(r.y0, 1), round(r.x1, 1),
                                                                   round(r.y1, 1)], role=loc.role))
        out.append(locs)
    for pdf in pdfs.values():
        pdf.close()
    return out


def tag_places(boxes: list, tag_h: float = 10.0, page_w: float | None = None, words: list | None = None) -> list[str]:
    """Where to put each box's "#n" tag: never over another finding's box, and over as little printed text as possible
    (words: [(x0, y0, x1, y1)] of the page), so a tag is not read as marking the line it covers.
    'above' (default), 'above_end' (above, at the box's right end), 'right', 'left', 'below', 'below_end'.
    boxes: [(x0, y0, x1, y1, no)] in PDF points on one page. Same rule for the PNGs and the viewer."""
    rects = [(b[0], b[1], b[2], b[3]) for b in boxes]
    words = words or []

    def area(r, o):
        return max(0, min(r[2], o[2]) - max(r[0], o[0])) * max(0, min(r[3], o[3]) - max(r[1], o[1]))

    def cost(r, own):                     # other findings' boxes first, then text covered; off the page: never
        if r[1] < 0 or r[0] < 0 or (page_w is not None and r[2] > page_w):
            return float("inf")
        return (sum(area(r, o) for i, o in enumerate(rects) if i != own), sum(area(r, o) for o in words))
    out = []
    for i, (x0, y0, x1, y1, no) in enumerate(boxes):
        w = 7 + 4.6 * len(str(no))
        cands = [("above", (x0, y0 - tag_h, x0 + w, y0)), ("above_end", (x1 - w, y0 - tag_h, x1, y0)),
                 ("right", (x1, y0, x1 + w, y0 + tag_h)), ("left", (x0 - w, y0, x0, y0 + tag_h)),
                 ("below", (x0, y1, x0 + w, y1 + tag_h)), ("below_end", (x1 - w, y1, x1, y1 + tag_h))]
        ok = [c for c in cands if cost(c[1], i) != float("inf")]
        best = min(ok, key=lambda c: (cost(c[1], i), [n for n, _ in cands].index(c[0]))) if ok else ("below", None)
        out.append(best[0])
    return out


def annotated_pages(path, page_marks, dpi: int = 110) -> list[bytes]:
    """PNG per page with a box in the severity colour and a "#n" tag on each marked value (in memory only)."""
    with pymupdf.open(path) as doc:
        marks = [m for m in page_marks if m[0] < len(doc)]
        place = {}
        for pno in {m[0] for m in marks}:
            on = [m for m in marks if m[0] == pno]
            rs = [tuple(pymupdf.Rect(m[1], m[2], m[3], m[4]) + (-3, -2, 3, 2)) + (m[6],) for m in on]
            words = [tuple(wd[:4]) for wd in doc[pno].get_text("words")]
            for m, where in zip(on, tag_places(rs, page_w=doc[pno].rect.width, words=words)):
                place[id(m)] = where
        tagged = set()
        for m in marks:
            pno, x0, y0, x1, y1, sev, no = m
            page, c = doc[pno], SEV_COLOR.get(sev, RED)
            r = pymupdf.Rect(x0, y0, x1, y1) + (-3, -2, 3, 2)
            page.draw_rect(r, color=c, width=1.8)
            w = 7 + 4.6 * len(str(no))
            tag = dict(above=pymupdf.Rect(r.x0, r.y0 - 10, r.x0 + w, r.y0), right=pymupdf.Rect(r.x1, r.y0, r.x1 + w, r.y0 + 10),
                       above_end=pymupdf.Rect(r.x1 - w, r.y0 - 10, r.x1, r.y0),
                       below_end=pymupdf.Rect(r.x1 - w, r.y1, r.x1, r.y1 + 10),
                       left=pymupdf.Rect(r.x0 - w, r.y0, r.x0, r.y0 + 10),
                       below=pymupdf.Rect(r.x0, r.y1, r.x0 + w, r.y1 + 10))[place.get(id(m), "above")]
            if (pno, no) in tagged:                    # one finding over several boxes (a phrase on 2 lines): one tag
                continue
            tagged.add((pno, no))
            page.draw_rect(tag, color=c, fill=c)
            page.insert_text((tag.x0 + 2, tag.y1 - 2.3), f"#{no}", fontsize=7.5, color=(1, 1, 1))
        return [pg.get_pixmap(dpi=dpi).tobytes("png") for pg in doc]


def render(finding, out_dir: Path, idx: int) -> list[Path]:
    """Write one PNG per (document, page) involved; the 'wrong' page first."""
    if not finding.locs:
        return []
    groups: "OrderedDict[tuple, list]" = OrderedDict()
    pdfs = {}
    for loc in sorted(finding.locs, key=lambda l: l.role != "wrong"):
        pdf = pdfs.setdefault(loc.doc.path, pymupdf.open(loc.doc.path))
        pno = _resolve_page(pdf, loc)
        if pno is not None:
            groups.setdefault((loc.doc.path, pno), []).append(loc)
    out = []
    for n, ((path, pno), locs) in enumerate(groups.items()):
        page = pdfs[path][pno]
        boxes = []
        for loc in locs:
            for r in _rects(page, loc):
                r = r + (-3, -2, 3, 2)
                page.draw_rect(r, color=RED if loc.role == "wrong" else GREEN, width=1.6)
                boxes.append(r)
        if not boxes:
            continue
        y0 = max(0, min(b.y0 for b in boxes) - CONTEXT)
        y1 = min(page.rect.height, max(b.y1 for b in boxes) + CONTEXT)
        pix = page.get_pixmap(dpi=DPI, clip=pymupdf.Rect(0, y0, page.rect.width, y1))
        f = out_dir / f"{idx:02d}_{finding.key}_{chr(97 + n)}.png"
        pix.save(f)
        out.append(f)
    for pdf in pdfs.values():
        pdf.close()                                   # boxes were drawn in memory only; files untouched
    return out
