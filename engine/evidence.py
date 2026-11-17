"""Page screenshots for each finding: red box = wrong value, green box = reference value."""
from collections import OrderedDict
from pathlib import Path

import pymupdf

RED, GREEN = (0.86, 0.1, 0.1), (0.1, 0.6, 0.2)
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
