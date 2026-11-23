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


# a container written with slashes: 'ABCD1234567/SEAL/40'HC/…', 'ABCD1234567/40'HQ/SEAL/…', '…/FCL/FCL /40HQ/'
_CNTR_SLASH = re.compile(r"\b([A-Z]{4}\d{7})\s*/(?:[^/]*/){0,5}?\s*(\d{2})\s*'?\s*(HC|HQ|GP|DC|RF|OT|FR)[A-Z]?\s*(?=/|$)")
_QTY_PHRASE = re.compile(rf"({NUM})\s*(?:CTNS?|CARTONS?)\s*=\s*({NUM})\s*(SETS?|PCS|PIECES?|UNITS?)\b")
_STOP = re.compile(r"SAID\b|SHIPPER.?S\b|\bTO CONTAIN\b|^\s*(?:LOAD|COUNT|SEAL)\b|DESCRIPTION\b|^\s*CY\s*[/-]\s*CY")
_PKG = r"(?:CARTON\(S\)|CARTONS?|CTNS?|PACKAGES?|PKGS?)"


def is_slash_bl(text: str) -> bool:
    """The other plain layout: containers written with slashes, 'n CTNS=m SETS', CY-CY and the freight term."""
    t = text.upper()
    return (_CNTR_SLASH.search(t) is not None and _QTY_PHRASE.search(t) is not None
            and re.search(r"\bCY\s*[-/]\s*CY\b", t) is not None
            and re.search(r"\bFREIGHT\s+(?:PREPAID|COLLECT)\b", t) is not None and "[ SHIPPER ]" not in t)


def is_plain_bl(text: str) -> bool:
    if is_slash_bl(text):
        return not re.search(r"\bSHIPPER\b.{0,40}\bNAME\b", text, re.I)      # labelled boxes: engine/bl_box.py
    t = text.upper()
    return ("SAID TO CONTAIN" in t and re.search(r"SHIPPER.?S\s+LOAD", t) is not None
            and _CNTR_ROW.search(text) is not None and "[ SHIPPER ]" not in t)


def _name(lines):
    """A company name from the first lines of a block (wrapped names joined, cut after 'LTD.')."""
    from .extract import Field
    lines = [l for l in lines if not re.match(r"\s*(?:TAX|TEL|FAX|ATTN)\b", l.spans[0].text)]   # not the name
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


def number(L, W):
    """B/L number: the code at the top right."""
    from .extract import Field
    for l in L[:8]:
        for s in l.spans:
            t = s.text.strip()
            if s.bbox[0] > W * 0.6 and re.fullmatch(r"[A-Z]{3,}[A-Z0-9]*\d{4,}[A-Z0-9]*", t):
                ln = Line(l.page, l.y, [s])
                return Field(t, t, ln, 0, len(ln.text))
    return None


def _span_field(l, s, m, g, value):
    """Field of group g of a match made on one span's text (boxed on that span only)."""
    from .extract import Field
    return Field(value, m[g], Line(l.page, l.y, [s]), m.start(g), m.end(g))


def containers(d, L):
    """Container numbers, types, loads per container, count, summary ('2*40HC') and count in words."""
    from .extract import Field, _search
    from .util import num
    d.lists["cntr"], d.lists["cntr_load"], d.lists["cntr_load_parts"] = [], [], []
    cells = [c for l in L for c in l.cells()]      # pieces of one column joined (a row may be cut into several spans)
    for i, c in enumerate(cells):
        ln, t = c, c.text
        m = _CNTR_ROW.search(t) or _CNTR_SLASH.search(t)
        if not m:                                  # number and type far apart on the line
            full = next(l for l in L if l.page == c.page and l.y == c.y and c.spans[0] in l.spans)
            m = _CNTR_ROW.search(full.text) if c.spans[0] is full.spans[0] else None
            if not m:
                continue
            ln = full
        g = 3 if m.re is _CNTR_ROW else 2
        typ = f"{m[g]}{m[g + 1]}"
        if any(f.value[0] == m[1] for f in d.lists["cntr"]):
            continue
        d.lists["cntr"].append(Field((m[1], typ), typ, ln, m.start(g), m.end(g + 1)))
        # cartons / gross weight / volume on the same line, or on the line under it
        under = [x for x in cells[i + 1:i + 8] if x.page == c.page and abs(x.bbox[0] - c.bbox[0]) < 4
                 and 0 < x.y - c.y < 14 and not re.search(r"[A-Z]{4}\d{7}", x.text)]
        parts, printed = {}, set()
        for x in [c] + under[:1]:
            for k, unit in (("ctn", _PKG), ("gw", r"KGS?\b"), ("cbm", r"(?:CBM|M3)\b")):
                if re.search(rf"\w\s*{unit}", x.text):
                    printed.add(k)
                v = re.search(rf"(?<![\w,])(?<!\d\.)(\d[\d,]*(?:\.\d+)?)\s*{unit}", x.text)
                if v and k not in parts:
                    parts[k] = Field(num(v[1]), v[0], x, v.start(), v.end())
        if printed:
            v = [parts[k].value if parts.get(k) else None for k in ("ctn", "gw", "cbm")]
            f = parts.get("cbm") or next(iter(parts.values()), d.lists["cntr"][-1])
            d.lists["cntr_load"].append(Field((m[1], *v), f.raw, f.line, f.start, f.end))
            d.lists["cntr_load_parts"].append(dict(no=m[1], printed=printed,
                                                   **{k: parts.get(k) for k in ("ctn", "gw", "cbm")}))
    one = r"\d+\s*[X×x*]\s*\d{2}\s*'?\s*[A-Z]{2}"
    for _, l, m in _search(L, rf"({one}(?:\s*[+&,]\s*{one})*)", 0):
        v = ",".join(f"{a}X{b}{c}" for a, b, c in re.findall(r"(\d+)\s*[X×x*]\s*(\d{2})\s*'?\s*([A-Z]{2})", m[1]))
        d.f["cntr_summary"] = Field(v, m[1], l, m.start(1), m.end(1))
        n = sum(int(x) for x in re.findall(r"(\d+)X", v))
        d.f["containers"] = Field(n, m[1], l, m.start(1), m.end(1))
        break
    for _, l, m in _search(L, r"\bSAY\s+(?:TOTAL\s+)?([A-Z][A-Z\- ]*?)\s*\(\s*(\d+)\s*\)\s*CONTAINER", 0):
        d.f["cntr_words"] = Field(m[1], l.text[m.start(1):m.end(2) + 1], l, m.start(1), m.end(2) + 1)
        d.f["cntr_words_n"] = Field(int(m[2]), m[2], l, m.start(2), m.end(2))
        break
    else:                                          # 'SAY FIVE(2*20'GP,3*40'HQ) CONTAINERS ONLY': words + the mix
        for _, l, m in _search(L, rf"\bSAY\s+(?:TOTAL\s+)?([A-Z][A-Z\- ]*?)\s*\(({one}[^)]*)\)\s*CONTAINER", 0):
            n = sum(int(x) for x in re.findall(r"(\d+)\s*[X×x*]\s*\d{2}", m[2]))
            d.f["cntr_words"] = Field(m[1], m[1], l, m.start(1), m.end(1))
            d.f["cntr_words_n"] = Field(n, m[2], l, m.start(2), m.end(2))
            break
    for _, l, m in _search(L, r"\b(\d+)\s*CONTAINER\(S\)\s*/\s*PACKAGE", 0):
        d.f["containers"] = Field(int(m[1]), m[1], l, m.start(1), m.end(1))
        break
    if not d.f.get("containers") and d.lists["cntr"]:
        c0 = d.lists["cntr"][0]
        d.f["containers"] = Field(len(d.lists["cntr"]), str(len(d.lists["cntr"])), c0.line, c0.start, c0.end)


def hs_codes(d, l, s, t, off=0):
    """'HS CODE:851111,851122' / '851111 & 851122' / '851111 / 851122' read from one span (text t starts at off)."""
    from .extract import Field
    m = re.match(r"HS\s*CODE\s*:?\s*(\d[\d.]+(?:\s*[,&/]\s*\d[\d.]+)*)", t, re.I)
    if not m:
        return False
    ln = Line(l.page, l.y, [s])
    codes = [(x[0], off + m.start(1) + x.start()) for x in re.finditer(r"\d[\d.]+", m[1])]
    d.lists["hs_codes"] = [Field(c, c, ln, k, k + len(c)) for c, k in codes]
    d.f["hs"] = d.lists["hs_codes"][0]
    d.f["hs_all"] = Field(", ".join(c for c, _ in codes), m[1], ln, off + m.start(1), off + m.end(1))
    return True


def goods_column(d, L):
    """Goods name, quantity phrase, HS and invoice number from the description column ('n CTNS=m SETS' gives the
    column; the goods name is the lines above it, up to 'SAID TO CONTAIN' or an empty row)."""
    from .extract import Field
    from .util import num
    hit = next(((l, s, m) for l in L for s in l.spans for m in [_QTY_PHRASE.match(s.text.strip())] if m), None)
    if not hit:
        return
    ql, qs, _ = hit
    m = _QTY_PHRASE.search(qs.text)
    for k, g, v in (("bl_qty_ctn", 1, num(m[1])), ("bl_qty", 2, num(m[2])), ("bl_unit", 3, m[3])):
        d.f[k] = _span_field(ql, qs, m, g, v)
    d.f["bl_qty_phrase"] = _span_field(ql, qs, m, 0, m[0])
    col = [(l, s) for l in L if l.page == ql.page for s in l.spans if abs(s.bbox[0] - qs.bbox[0]) < 3 and s.text.strip()]
    k = next(i for i, (_, s) in enumerate(col) if s is qs)
    goods, y = [], ql.y
    for l, s in reversed(col[:k]):
        if y - l.y > 18 or _STOP.search(s.text.strip()):
            break
        goods.insert(0, (l, s))
        y = l.y
    if goods:
        text = re.sub(r"\s+", " ", " ".join(s.text.strip() for _, s in goods)).strip()
        ln = Line(goods[0][0].page, goods[0][0].y, [s for _, s in goods])
        d.f["goods"] = d.f["goods_full"] = Field(text, text, ln, 0, len(ln.text))
    for l, s in col[k + 1:]:
        t = s.text.strip()
        off = len(s.text) - len(s.text.lstrip())
        if re.match(r"\*{3}|TEL\b|ATTN|EMAIL", t):
            break
        if not d.f.get("hs") and hs_codes(d, l, s, t, off):
            continue
        x = re.match(rf"\s*INVOICE NO\.?\s*:?\s*({DOC_ID})", s.text)
        if x:
            d.f["invoice_no"] = _span_field(l, s, x, 1, x[1])


def weights(d, L, W):
    """Total cartons (number, unit beside or under it), gross weight and volume (right-hand columns, same block)."""
    from .util import num
    cells = [(l, s) for l in L if l.page == 0 for s in l.spans]
    for l, s in cells:
        m = re.match(rf"\s*({NUM})\s*({_PKG})?\s*$", s.text)
        if not m or not W * 0.1 < s.bbox[0] < W * 0.5 or _CNTR_SLASH.search(l.text):
            continue
        near = lambda b, a: -2 < a.y - l.y < 20 and -25 < b.bbox[0] - s.bbox[0] < 60
        if not m[2] and not any(re.match(rf"\s*{_PKG}\s*$", b.text) and near(b, a) for a, b in cells):
            continue
        right = sorted(((b.bbox[0], a, b, x) for a, b in cells if abs(a.y - l.y) < 22 and b.bbox[0] > W * 0.55
                        for x in [re.match(rf"\s*({NUM})\s*(?:KGS?|CBM|M3)?\s*$", b.text)] if x and "." in x[1]),
                       key=lambda t: t[0])
        if len(right) < 2:
            continue
        d.f["ctn"] = _span_field(l, s, m, 1, num(m[1]))
        for key, (_, a, b, x) in (("gw", right[0]), ("cbm", right[-1])):
            d.f[key] = _span_field(a, b, x, 1, num(x[1]))
        return


def finish(d, L):
    from .extract import CargoBlock, Field, _first
    d.f["freight"] = d.f.get("freight") or _first(L, r"\bFREIGHT\s+(COLLECT|PREPAID)\b")
    d.lists["invoice_nos"] = [d.f["invoice_no"]] if d.f.get("invoice_no") else []
    d.lists.setdefault("pod", [d.f["pod"]] if d.f.get("pod") else [])
    d.lists["marks_models"] = []
    d.cargo_blocks = [CargoBlock(ctn=d.f["bl_qty_ctn"], qty=d.f.get("bl_qty"), unit=d.f.get("bl_unit"),
                                 goods=d.f.get("goods"), hs=d.f.get("hs"), invoice=d.f.get("invoice_no"))] \
        if d.f.get("bl_qty_ctn") else []
    whole = "\n".join(l.text for l in L)
    absent = [k for k, rx in (("origin", r"MADE IN|(?<!COUNTRY OF )\bORIGIN\b(?! OF GOODS)"), ("final_dest", r"FINAL DESTINATION"))
              if not d.f.get(k) and not d.lists.get(k) and not re.search(rx, whole, re.I)]
    if absent:
        d.f["absent"] = Field(", ".join(absent), "", d.lines[0], 0, 0)


def extract(d):
    from .extract import CargoBlock, F, Field, _first, _search, _vessel
    from .util import num
    L = [l for l in d.lines if l.page == 0] or d.lines
    W = d.page_width
    first_cntr = next((l for l in L if _CNTR_ROW.search(l.text) or _CNTR_SLASH.search(l.text)), None)
    top_end = first_cntr.y if first_cntr else 1e9
    d.f["bl_no"] = number(L, W)
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
        if re.search(r"[A-Z]{2}", v):
            d.f["vessel"] = Field(_vessel(v), v, ln, 0, len(ln.text))
        else:                                      # '/' only: the vessel box is empty
            d.f["blank:vessel"] = Field("VESSEL / VOY. NO.", v, ln, 0, len(ln.text))
        d.f["pol"] = cell(l, c[1])
        if k > 0 and 1 in grid[k - 1][1]:
            d.f["receipt"] = cell(grid[k - 1][0], grid[k - 1][1][1])
        for j in range(k + 1, min(k + 3, len(grid))):        # discharge and delivery may sit a few points apart
            l2, c2 = grid[j]
            if 0 in c2 and not d.f.get("pod"):
                d.f["pod"] = cell(l2, c2[0])
                m = re.search(r",\s*([A-Z][A-Z ]+?)\s*$", c2[0].text)
                nl = grid[j + 1] if j + 1 < len(grid) else None
                if m:
                    ln = Line(l2.page, l2.y, [c2[0]])
                    d.f["dest_country"] = Field(m[1], m[1], ln, m.start(1), m.end(1))
                elif nl and c2[0].text.strip().endswith(",") and 0 in nl[1]:      # the country wraps to the next line
                    t = nl[1][0].text.strip()
                    if re.fullmatch(r"[A-Z][A-Z ]+", t):
                        ln = Line(nl[0].page, nl[0].y, [nl[1][0]])
                        d.f["dest_country"] = Field(t, t, ln, 0, len(ln.text))
            if 1 in c2 and not d.f.get("delivery"):
                d.f["delivery"] = cell(l2, c2[1])
    d.lists["pod"] = [d.f["pod"]] if d.f.get("pod") else []
    if is_slash_bl("\n".join(l.text for l in d.lines)):
        containers(d, d.lines)
        goods_column(d, d.lines)
        weights(d, d.lines, W)
        if d.f.get("blank:vessel"):
            finish(d, d.lines)
            a = d.f.get("absent")
            d.f["absent"] = Field((a.value + ", " if a else "") + "vessel", "", d.lines[0], 0, 0)
            return
        finish(d, d.lines)
        return
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
        if hs_codes(d, l, s, t, len(s.text) - len(s.text.lstrip())):
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
    if not d.f.get("ctn") and not d.f.get("bl_qty"):   # number and 'CARTONS' on two lines: read by the description column
        goods_column(d, L)
        weights(d, L, W)
    d.f["freight"] = _first(L, r"\bFREIGHT\s+(COLLECT|PREPAID)\b")
    d.lists["invoice_nos"] = [d.f["invoice_no"]] if d.f.get("invoice_no") else []
    d.lists["marks_models"] = []
    d.cargo_blocks = [CargoBlock(ctn=d.f["bl_qty_ctn"], qty=d.f.get("bl_qty"), unit=d.f.get("bl_unit"),
                                 goods=d.f.get("goods"), hs=d.f.get("hs"), invoice=d.f.get("invoice_no"))] \
        if d.f.get("bl_qty_ctn") else []
    whole = "\n".join(l.text for l in d.lines)
    absent = [k for k, rx in (("origin", r"MADE IN|\bORIGIN\b"), ("final_dest", r"FINAL DESTINATION"))
              if not d.f.get(k) and not re.search(rx, whole, re.I)]
    if absent:
        d.f["absent"] = Field(", ".join(absent), "", d.lines[0], 0, 0)
