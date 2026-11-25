"""Rebuild visual text lines (with span geometry) from a PDF page."""
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass, field
import pymupdf

SEP_WIDE = "   "


@dataclass
class Span:
    text: str
    bbox: tuple
    font: str
    size: float
    color: int
    flags: int
    origin: tuple


@dataclass
class Line:
    page: int
    y: float
    spans: list = field(default_factory=list)
    _text: str = None
    _offs: list = None

    def _build(self):
        out, offs, last_x = "", [], None
        for s in self.spans:
            if last_x is not None:
                gap = s.bbox[0] - last_x
                out += SEP_WIDE if gap > s.size * 0.8 else ("" if gap < s.size * 0.15 else " ")
            offs.append((len(out), len(out) + len(s.text), s))
            out += s.text
            last_x = s.bbox[2]
        self._text, self._offs = out, offs

    @property
    def text(self) -> str:
        if self._text is None:
            self._build()
        return self._text

    def spans_for(self, start: int, end: int) -> list:
        self.text
        return [s for a, b, s in self._offs if a < end and b > start]

    def span_end(self, end: int) -> int:
        """End offset of the span containing position end-1."""
        self.text
        for a, b, s in self._offs:
            if a < end <= b:
                return b
        return end

    def span_start(self, start: int) -> int:
        self.text
        for a, b, s in self._offs:
            if a <= start < b:
                return a
        return start

    def prev_span_x1(self, start: int) -> float:
        self.text
        prev = 0.0
        for a, b, s in self._offs:
            if b <= start:
                prev = s.bbox[2]
        return prev

    def next_span_x(self, end: int, page_width: float) -> float:
        self.text
        for a, b, s in self._offs:
            if a >= end:
                return s.bbox[0]
        return page_width - 15

    def cells(self) -> list:
        """The line split into cells at wide gaps (the same gaps that put three spaces into .text): one cell per
        column the line crosses. Each cell is a Line of its own spans, so Fields read from it keep their place."""
        out, cur, last_x = [], [], None
        for s in self.spans:
            if cur and last_x is not None and s.bbox[0] - last_x > s.size * 0.8:
                out.append(Line(self.page, self.y, cur))
                cur = []
            cur.append(s)
            last_x = s.bbox[2]
        if cur:
            out.append(Line(self.page, self.y, cur))
        return out

    @property
    def bbox(self):
        return (min(s.bbox[0] for s in self.spans), min(s.bbox[1] for s in self.spans),
                max(s.bbox[2] for s in self.spans), max(s.bbox[3] for s in self.spans))


def wrapped_cells(lines: list, cell: Line, stop: str, rows: int = 2):
    """The cell joined with the cells right under it in the same column (a value that did not fit the column's width):
    with one row, then two … Ends at a gap, another column or a cell that matches stop (the next value)."""
    import re
    spans, last = list(cell.spans), cell
    for _ in range(rows):
        h = last.bbox[3] - last.bbox[1]
        under = [c for l in lines if l.page == cell.page and 0 < l.y - last.y < h * 1.8
                 for c in l.cells() if abs(c.bbox[0] - cell.bbox[0]) < 4]
        nxt = min(under, key=lambda c: c.y, default=None)
        if nxt is None or re.match(stop, nxt.text):
            return
        spans = spans + list(nxt.spans)
        last = nxt
        yield Line(cell.page, cell.y, spans)


class Page:
    """The text of a PDF page, read once: get_text() / get_text("dict") without the images."""

    def __init__(self, page):
        self.width = page.rect.width
        self._text = page.get_text()
        d = page.get_text("dict")
        d["blocks"] = [b for b in d["blocks"] if b.get("lines")]
        self._dict = d
        self._path, self._no, self._drawn = None, page.number, None

    def drawings(self) -> list:
        """The vertical edges drawn on the page: (x, top, bottom) of each vertical line or thin box (once per page)."""
        if self._drawn is None:
            self._drawn = []
            with pymupdf.open(self._path) as pdf:
                for dr in pdf[self._no].get_drawings():
                    for it in dr["items"]:
                        if it[0] == "l" and abs(it[1].x - it[2].x) < 1:
                            a, b = it[1], it[2]
                            self._drawn.append((round(a.x, 1), min(a.y, b.y), max(a.y, b.y)))
                        elif it[0] == "re" and it[1].width < 2:
                            self._drawn.append((round(it[1].x0, 1), it[1].y0, it[1].y1))
        return self._drawn

    def get_text(self, what: str = "text"):
        return self._dict if what == "dict" else self._text


@lru_cache(maxsize=48)
def _pages(path: str, _mtime: int, _size: int) -> tuple:
    with pymupdf.open(path) as pdf:
        out = tuple(Page(p) for p in pdf)
    for p in out:
        p._path = path
    return out


def pages(path) -> tuple:
    """The pages of a PDF; a document that is read again (engine/unwrap.py) is not opened again."""
    st = Path(path).stat()
    return _pages(str(path), st.st_mtime_ns, st.st_size)


def page_lines(page: pymupdf.Page, pno: int) -> list[Line]:
    spans = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            if abs(l["dir"][1]) > 0.01:          # skip rotated text (watermarks / stamps)
                continue
            for s in l["spans"]:
                if s["text"].strip():
                    spans.append(Span(s["text"], tuple(s["bbox"]), s["font"], s["size"],
                                      s["color"], s["flags"], tuple(s["origin"])))
    spans.sort(key=lambda s: ((s.bbox[1] + s.bbox[3]) / 2, s.bbox[0]))
    lines: list[Line] = []
    for s in spans:
        yc = (s.bbox[1] + s.bbox[3]) / 2
        if lines and abs(lines[-1].y - yc) <= max(2.0, s.size * 0.3):
            lines[-1].spans.append(s)
        else:
            lines.append(Line(pno, yc, [s]))
    for l in lines:
        l.spans.sort(key=lambda s: s.bbox[0])
    return lines


def doc_lines(doc) -> list[Line]:
    out = []
    for pno, page in enumerate(doc):
        out.extend(page_lines(page, pno))
    return out
