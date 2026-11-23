"""A carrier B/L or sea waybill with its box labels printed as text ('SHIPPER … NAME AND ADDRESS', 'PORT OF LOADING',
'VESSEL / VOY NO.' …), in two cargo layouts:

    typed page      one monospaced line per row: container rows, then 'N/M   100 ACME FAN   1234.5KGS  12.3CBM', the
                    description keeps its character column over the pages; footnotes ('++VIET NAM') complete the boxes
    columns         containers / packages / description / weight / volume as separate pieces of text

Each box value is the text under its label, in the label's column. The fields are those of the other B/L readers."""
import re

from . import bl_plain
from .grammar import DOC_ID, NUM
from .pdftext import Line

_LABEL = {
    "shipper": r"(?:\d+\.\s*)?SHIPPER\b.*\b(?i:NAME)\b",
    "consignee": r"(?:\d+\.\s*)?CONSIGNEE\b.*\b(?i:NAME)\b",
    "notify": r"(?:\d+\.\s*)?NOTIFY PARTY\b.*\b(?i:NAME)\b",
    "precarriage": r"(?:\d+\.\s*)?PRE-?CARRIAGE",
    "receipt": r"(?:\d+\.\s*)?PLACE OF RECEIPT",
    "vessel": r"(?:\d+\.\s*)?(?:OCEAN\s+)?VESSEL\s*/\s*VOY",
    "pol": r"(?:\d+\.\s*)?PORT OF LOADING",
    "pod": r"(?:\d+\.\s*)?PORT OF DISCHARGE",
    "delivery": r"(?:\d+\.\s*)?PLACE OF DELIVERY",
}


def _labels(lines):
    out = {}
    for l in lines:
        if l.page:
            break
        for s in l.spans:
            for k, rx in _LABEL.items():
                if k not in out and re.match(r"\s*" + rx, s.text):
                    out[k] = (l, s)
    return out


def is_box_bl(lines) -> bool:
    text = "\n".join(l.text for l in lines if l.page == 0)
    if "[ SHIPPER ]" in text.upper() or not re.search(r"WAYBILL|BILL OF LADING", text, re.I):
        return False
    return {"shipper", "consignee", "notify", "vessel", "pol", "pod"} <= set(_labels(lines))


def _typed(d, L):
    """The typed (monospaced) cargo page: cartons, weight, volume, then the description at its character column."""
    from .extract import Field
    from .util import num
    rx = re.compile(rf"^(.*?)(?<!\S)({NUM})\s(\S.*?)\s{{2,}}({NUM})KGS\s+({NUM})CBM")
    hit = next(((l, l.spans[0], m) for l in L for m in [rx.match(l.spans[0].text)]
                if m and len(l.spans) == 1 and not re.match(r"\s*TOTAL", l.text)), None)
    if not hit:
        return False
    l0, s0, m = hit
    for k, g in (("ctn", 2), ("gw", 4), ("cbm", 5)):
        d.f[k] = bl_plain._span_field(l0, s0, m, g, num(m[g]))
    col = m.start(3)
    goods, rest = [(l0, s0, m[3])], False
    for l in L[L.index(l0) + 1:]:
        s = l.spans[0]
        if re.match(r"\s*TOTAL\s*:", s.text):
            break
        t = s.text[col:].strip()
        if not t or len(l.spans) > 1 or not re.fullmatch(rf"\s*{bl_plain._PKG}?\s*", s.text[:col]):
            continue                               # page header / footer between the two parts of the description
        q = bl_plain._QTY_PHRASE.match(t)
        if q:
            rest = True
            q = bl_plain._QTY_PHRASE.search(s.text)
            for k, g, v in (("bl_qty_ctn", 1, num(q[1])), ("bl_qty", 2, num(q[2])), ("bl_unit", 3, q[3])):
                d.f[k] = bl_plain._span_field(l, s, q, g, v)
            d.f["bl_qty_phrase"] = bl_plain._span_field(l, s, q, 0, q[0])
            continue
        x = re.search(rf"INVOICE NO\.?\s*:?\s*({DOC_ID})", s.text)
        if x:
            d.f["invoice_no"] = d.f.get("invoice_no") or bl_plain._span_field(l, s, x, 1, x[1])
            rest = True
        elif not d.f.get("hs") and bl_plain.hs_codes(d, l, s, t, s.text.find(t)):
            rest = True
        x = re.match(r"(\+{2,})\s*([A-Z][A-Z ]+)$", t)
        if x:                                      # 'PORT A,++' … '++COUNTRY': the rest of the port boxes
            k = s.text.find(x[2])
            d.f["dest_country"] = Field(x[2], x[2], Line(l.page, l.y, [s]), k, k + len(x[2]))
        if re.match(r"[*+]{1,3}", t):
            rest = True
        if not rest:
            goods.append((l, s, t))
    text = re.sub(r"\s+", " ", " ".join(g[2] for g in goods)).strip()
    k = m.start(3)
    d.f["goods"] = d.f["goods_full"] = Field(text, m[3], Line(l0.page, l0.y, [s0]), k, k + len(m[3]))
    return True


def extract(d):
    from .extract import Field, _vessel
    from .extract import _search
    W = d.page_width
    L = [l for l in d.lines if l.page < 2]                # page 3 on: printed terms
    P = [l for l in L if l.page == 0]
    d.f["bl_no"] = bl_plain.number(P, W)
    lab = _labels(L)

    def below(k, reach=14):
        """(line, span) directly under label k, in its column; None when the box is empty."""
        if k not in lab:
            return None
        ll, ls = lab[k]
        for l in P:
            if not 2 < l.y - ll.y < reach:
                continue
            for s in l.spans:
                if -15 < s.bbox[0] - ls.bbox[0] < 110 and s.text.strip():
                    if any(s is x for _, x in lab.values()):
                        return None
                    return l, s
        return None

    def names(k, until):
        if k not in lab:
            return None
        ll, ls = lab[k]
        end = lab[until][0].y if until in lab else ll.y + 80
        rows = [Line(0, l.y, [s]) for l in P if ll.y + 2 < l.y < end - 2 for s in l.spans
                if abs(s.bbox[0] - ls.bbox[0]) < 5 and not s.text.strip().startswith("(")]
        return bl_plain._name(rows)
    d.f["shipper"] = names("shipper", "consignee")
    d.f["consignee"] = names("consignee", "notify")
    d.f["notify"] = names("notify", "precarriage" if "precarriage" in lab else "receipt")
    v = below("vessel")
    if v:
        t = v[1].text.strip()
        ln = Line(0, v[0].y, [v[1]])
        if re.search(r"[A-Z]{2}", t):
            d.f["vessel"] = Field(_vessel(t), t, ln, 0, len(ln.text.rstrip()))
    blank_vessel = not v and "vessel" in lab
    if blank_vessel:
        l, s = lab["vessel"]
        d.f["blank:vessel"] = Field("VESSEL / VOY. NO.", s.text, Line(0, l.y, [s]), 0, len(s.text))
    for k in ("receipt", "pol", "pod", "delivery"):
        x = below(k)
        m = re.match(r"\s*([A-Z][A-Z .]*?[A-Z])\s*(?:,\s*([A-Z][A-Z ]*[A-Z])?|\+|$)", x[1].text) if x else None
        if m:
            ln = Line(0, x[0].y, [x[1]])
            d.f[k] = Field(m[1], m[1], ln, m.start(1), m.end(1))
            if k == "pod" and m[2]:
                d.f["dest_country"] = Field(m[2], m[2], ln, m.start(2), m.end(2))
    bl_plain.containers(d, L)
    if not _typed(d, L):
        bl_plain.goods_column(d, L)
        bl_plain.weights(d, L, W)
    bl_plain.finish(d, L)
    if blank_vessel:
        a = d.f.get("absent")
        d.f["absent"] = Field((a.value + ", " if a else "") + "vessel", "", d.lines[0], 0, 0)
