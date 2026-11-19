"""Rebuild visual text lines (with span geometry) from a PDF page."""
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


def doc_lines(doc: pymupdf.Document) -> list[Line]:
    out = []
    for pno, page in enumerate(doc):
        out.extend(page_lines(page, pno))
    return out
