"""A B/L whose box labels are part of the background picture: the PDF text has the values only, no '[ Shipper ]',
no 'BILL OF LADING' (for example a carrier's own draft B/L). The values are read by their order and column:

    shipper / consignee / notify party      the three name blocks at the top left, separated by empty space
    B/L number                              the code at the top right
    place of receipt                        the row under the notify party (second column)
    vessel + voyage | port of loading        the next row
    port of discharge | place of delivery    the row after it
    containers                              'ABCD1234567 /SEAL   40HC' rows
    cartons, goods, quantity, HS, invoice   the said-to-contain column; weight (KGS) and measurement (CBM) beside it
    'TOTAL: 2×40HC CONTAINERS ONLY'         container summary;  'FREIGHT PREPAID / COLLECT'

The fields are the ones the labelled B/L reader fills, so all B/L rules apply unchanged.
"""
import re

from .grammar import DEC, DOC_ID, NUM
from .pdftext import Line

_CNTR_ROW = re.compile(r"\b([A-Z]{4}\d{7})\s*/\s*([A-Z0-9]+)\s+(\d{2})\s*'?\s*(HC|HQ|GP|DC|RF|OT|FR)[A-Z]?\b")
_LEGAL_END = r"\b(?:LTD|LIMITED|INC|CORPORATION|CORP|LLC|GMBH)\b\.?"


def is_plain_bl(text: str) -> bool:
    t = text.upper()
    return ("SAID TO CONTAIN" in t and re.search(r"SHIPPER.?S\s+LOAD", t) is not None
            and _CNTR_ROW.search(text) is not None and "[ SHIPPER ]" not in t)


def _name(lines):
    """A company name from the first lines of a block (wrapped names joined, cut after 'LTD.')."""
    from .extract import Field
    if not lines:
        return None
    spans = [l.spans[0] for l in lines[:3]]
    text = ""
    for s in spans:
        text = (text + " " + s.text.strip()).strip()
        m = re.search(_LEGAL_END, text)
        if m:
            break
    m = re.search(_LEGAL_END, text)
    name = text[:m.end()] if m else spans[0].text.strip()
    used = [s for s in spans if s.text.strip() and s.text.strip()[:6] in name]
    ln = Line(lines[0].page, lines[0].y, used or spans[:1])
    return Field(re.sub(r"\s+", " ", name).strip(), name, ln, 0, len(ln.text))


def extract(d):
    from .extract import CargoBlock, F, Field, _first, _search, _vessel
    from .util import num
    L = [l for l in d.lines if l.page == 0] or d.lines
    W = d.page_width
    first_cntr = next((l for l in L if _CNTR_ROW.search(l.text)), None)
    top_end = first_cntr.y if first_cntr else 1e9
    # B/L number: the code at the top right
    for l in L[:8]:
        for s in l.spans:
            t = s.text.strip()
            if s.bbox[0] > W * 0.6 and re.fullmatch(r"[A-Z]{3,}[A-Z0-9]*\d{4,}[A-Z0-9]*", t):
                ln = Line(l.page, l.y, [s])
                d.f["bl_no"] = Field(t, t, ln, 0, len(ln.text))
                break
        if d.f.get("bl_no"):
            break
    # left column name blocks, split where the line spacing opens up
    left = [l for l in L if l.y < top_end and l.spans[0].bbox[0] < W * 0.3]
    gaps = sorted(b.y - a.y for a, b in zip(left, left[1:]))
    step = gaps[len(gaps) // 3] if gaps else 20
    blocks, cur = [], []
    for l in left:
        if cur and l.y - cur[-1].y > step * 1.8:
            blocks.append(cur)
            cur = []
        cur.append(l)
    if cur:
        blocks.append(cur)
    names = [b for b in blocks if re.search(r"[A-Z]{3}", b[0].text) and not _CNTR_ROW.search(b[0].text)]
    if len(names) >= 3:
        d.f["shipper"], d.f["consignee"], d.f["notify"] = _name(names[0]), _name(names[1]), _name(names[2])
        after = names[2][-1].y
    else:
        after = 0
    # receipt / vessel + loading / discharge + delivery rows under the notify party
    rows = [l for l in L if after < l.y < top_end and not re.search(r"\bN/?M\b|SHIPPER.?S\s+LOAD", l.text)]
    col = lambda s: 0 if s.bbox[0] < W * 0.25 else 1 if s.bbox[0] < W * 0.5 else 2
    grid = [(l, {col(s): s for s in reversed(l.spans)}) for l in rows]
    k = next((i for i, (l, c) in enumerate(grid) if 0 in c and 1 in c), None)

    def cell(l, s, rx=r"^\s*([A-Z][A-Z .]*?[A-Z])\s*(?:,|$)"):
        t = s.text
        m = re.match(rx, t)
        ln = Line(l.page, l.y, [s])
        return Field(m[1], m[1], ln, m.start(1), m.end(1)) if m else None
    if k is not None:
        l, c = grid[k]
        v = c[0].text.strip()
        ln = Line(l.page, l.y, [c[0]])
        d.f["vessel"] = Field(_vessel(v), v, ln, 0, len(ln.text))
        d.f["pol"] = cell(l, c[1])
        if k > 0 and 1 in grid[k - 1][1]:
            d.f["receipt"] = cell(grid[k - 1][0], grid[k - 1][1][1])
        if k + 1 < len(grid):
            l2, c2 = grid[k + 1]
            if 0 in c2:
                d.f["pod"] = cell(l2, c2[0])
                m = re.search(r",\s*([A-Z][A-Z ]+?)\s*$", c2[0].text)
                if m:
                    ln = Line(l2.page, l2.y, [c2[0]])
                    d.f["dest_country"] = Field(m[1], m[1], ln, m.start(1), m.end(1))
            if 1 in c2:
                d.f["delivery"] = cell(l2, c2[1])
    d.lists["pod"] = [d.f["pod"]] if d.f.get("pod") else []
    # containers
    d.lists["cntr"] = []
    for l in L:
        for m in _CNTR_ROW.finditer(l.text):
            t = f"{m[3]}{m[4]}"
            d.lists["cntr"].append(Field((m[1], t), t, l, m.start(3), m.start(4) + len(m[4])))
    for _, l, m in _search(L, r"TOTAL\s*:\s*((\d+)\s*[X×xX]\s*(\d{2})\s*'?\s*([A-Z]{2}))"):
        v = f"{m[2]}X{m[3]}{m[4]}"
        d.f["cntr_summary"] = Field(v, m[1], l, m.start(1), m.end(1))
        d.f["containers"] = Field(int(m[2]), m[2], l, m.start(2), m.end(2))
        break
    if not d.f.get("containers") and d.lists["cntr"]:
        c0 = d.lists["cntr"][0]
        d.f["containers"] = Field(len(d.lists["cntr"]), str(len(d.lists["cntr"])), c0.line, c0.start, c0.end)
    # cartons + gross weight + measurement on one row; the description column starts beside the cartons
    goods_x = None
    for _, l, m in _search(L, rf"({NUM})\s+(?:CARTONS?|CTNS?|PACKAGES?|PKGS?)\b", 0):
        d.f["ctn"] = F(l, m, 1, num(m[1]))
        g = re.search(rf"({DEC})\s*KGS", l.text)
        c = re.search(rf"({DEC})\s*(?:CBM|M3)", l.text)
        d.f["gw"] = F(l, g, 1, num(g[1])) if g else None
        d.f["cbm"] = F(l, c, 1, num(c[1])) if c else None
        after_ctn = [s for s in l.spans if s.bbox[0] > l.spans_for(m.start(), m.end())[-1].bbox[2] + 1
                     and not re.search(r"KGS|CBM|M3|^\s*(CARTONS?|CTNS?)\s*$", s.text)]
        if after_ctn:
            goods_x = after_ctn[0].bbox[0]
        break
    desc = []
    if goods_x is not None and d.f.get("ctn"):
        start = d.f["ctn"].line
        for l in L[L.index(start):]:
            for s in l.spans:
                if abs(s.bbox[0] - goods_x) < 8 and s.text.strip():
                    desc.append((l, s))
    goods_parts, qty_seen = [], False
    for l, s in desc:
        t = s.text.strip()
        if re.match(r"\*{3}|TEL\b|ATTN|EMAIL", t):
            break
        m = re.match(rf"({NUM})\s*(?:CTNS?|CARTONS?)\s*=\s*({NUM})\s*(SETS?|PCS|PIECES?|UNITS?)\b", t)
        if m:
            ln = Line(l.page, l.y, [s])
            d.f["bl_qty_ctn"] = Field(num(m[1]), m[1], ln, m.start(1), m.end(1))
            d.f["bl_qty"] = Field(num(m[2]), m[2], ln, m.start(2), m.end(2))
            d.f["bl_unit"] = Field(m[3], m[3], ln, m.start(3), m.end(3))
            d.f["bl_qty_phrase"] = Field(t, t, ln, 0, len(t))
            qty_seen = True
            continue
        m = re.match(r"HS\s*CODE\s*:?\s*([\d.]+(?:\s*,\s*[\d.]+)*)", t, re.I)
        if m:
            codes = [c.strip() for c in m[1].split(",")]
            ln = Line(l.page, l.y, [s])
            d.f["hs"] = Field(codes[0], m[1], ln, m.start(1), m.start(1) + len(codes[0]))
            d.lists["hs_codes"] = [Field(c, c, ln, t.find(c), t.find(c) + len(c)) for c in codes]
            d.f["hs_all"] = Field(", ".join(codes), m[1], ln, m.start(1), m.end(1))
            continue
        m = re.match(rf"INVOICE NO\.?\s*:?\s*({DOC_ID})", t)
        if m:
            ln = Line(l.page, l.y, [s])
            d.f["invoice_no"] = Field(m[1], m[1], ln, m.start(1), m.end(1))
            continue
        if not qty_seen and not re.search(r"\d", t):
            goods_parts.append((l, s))
    if goods_parts:
        text = re.sub(r"\s+", " ", " ".join(s.text.strip() for _, s in goods_parts))
        ln = Line(goods_parts[0][0].page, goods_parts[0][0].y, [s for _, s in goods_parts])
        d.f["goods"] = Field(text, text, ln, 0, len(ln.text))
        d.f["goods_full"] = d.f["goods"]
    d.f["freight"] = _first(L, r"\bFREIGHT\s+(COLLECT|PREPAID)\b")
    d.lists["invoice_nos"] = [d.f["invoice_no"]] if d.f.get("invoice_no") else []
    d.lists["marks_models"] = []
    d.cargo_blocks = [CargoBlock(ctn=d.f["bl_qty_ctn"], qty=d.f.get("bl_qty"), unit=d.f.get("bl_unit"),
                                 goods=d.f.get("goods"), hs=d.f.get("hs"), invoice=d.f.get("invoice_no"))] \
        if d.f.get("bl_qty_ctn") else []
    whole = "\n".join(l.text for l in d.lines)
    absent = [k for k, rx in (("origin", r"MADE IN|\bORIGIN\b"), ("final_dest", r"FINAL DESTINATION"),
                              ("cntr_words", r"\(\s*\d+\s*\)\s*CONTAINER"))
              if not d.f.get(k) and not re.search(rx, whole, re.I)]
    if absent:
        d.f["absent"] = Field(", ".join(absent), "", d.lines[0], 0, 0)
