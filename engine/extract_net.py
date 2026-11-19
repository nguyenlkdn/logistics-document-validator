"""Extra fields for the cross-document ("net") and self-consistency rules. Runs after the per-kind extractors in
extract.load() and only adds fields; nothing that the older rules use is changed.

Every field keeps its place in the PDF (Field), so findings can be boxed on the page.
"""
import re

from .extract import MARK_HEAD, MARK_TAIL, MODEL_RE, PO_RE, CargoBlock, Doc, F, Field, _after, _first, _search, column_models
from .grammar import CTN_UNIT, DATE_DMY, DEC, DEC2, DOC_ID, NUM, QTY_UNIT
from .util import num, parse_date

CURRENCIES = ("USD", "EUR", "JPY", "THB", "VND", "CNY", "SGD", "GBP")
_CUR_RX = re.compile(r"\b(" + "|".join(CURRENCIES) + r")\b|U\.?\s?S\.?\s+DOLLARS?", re.I)
_LABELS = re.compile(r"^\s*(\[|\d+\.\s|Reference No|ACCOUNTEE|CONSIGNEE|SHIP TO|Attn|Address|TEL\b)", re.I)


def _name_after(L, label_rx, skip_rx=None, max_ahead=3, flags=re.I):
    """Party name on the first line after a label line (or after the label on the same line)."""
    for i, l, m in _search(L, label_rx, flags):
        rest = l.text[m.end():].strip(" :\t")
        rest = re.split(r"\s{2,}", rest)[0].strip() if rest else ""
        if rest and not re.fullmatch(r"(DRAFT?|FORM D)", rest, re.I) and not rest.startswith("("):   # "(Consignee's name…)"
            k = l.text.find(rest, m.end())
            return Field(rest, rest, l, k, k + len(rest))
        for nl in L[i + 1:i + 1 + max_ahead]:
            t = nl.text
            if skip_rx and re.search(skip_rx, t, re.I):
                continue
            first = re.split(r"\s{2,}", t.strip())[0].strip()
            if not first or _LABELS.match(first):
                continue
            k = t.find(first)
            return Field(first, first, nl, k, k + len(first))
    return None


def _money_cur(L) -> list:
    """Currency codes written on the document (amount columns, totals, words 'U.S. Dollars')."""
    out = []
    for l in L:
        for m in _CUR_RX.finditer(l.text):
            code = (m[1] or "USD").upper()
            out.append(Field(code, m[0], l, m.start(), m.end()))
    return out


def _ttl_ci(l, m=None) -> dict:
    """Invoice TTL line -> {ctn, qty, amount} (fields present only when written on the line)."""
    t, out = l.text, {}
    for key, rx, conv in (("ctn", rf"({NUM})\s*CARTON\s*\(\s*S\s*\)", num), ("qty", rf"({NUM})\s*{QTY_UNIT}", num),
                          ("amount", rf"({DEC2})\s*(?:IN USD)?\s*$", num)):
        mm = re.search(rx, t)
        if mm:
            out[key] = F(l, mm, 1, conv(mm[1]))
    return out


_BRAND = r'("?[A-Z][A-Z0-9&.\-]*"?\s+BRAND)\s+$'
_LEGAL = r"(?:CO\.?,?\s*LTD\.?|COMPANY\s+LIMITED|LIMITED|INC\.?|CORP(?:ORATION)?\.?|PTE\.?\s*LTD\.?)"


def _goods_full(L, g: Field | None) -> Field | None:
    """Full goods description: the brand written before the product name ('"ACME" BRAND WASHING MACHINE'),
    on the same line or at the end of the line above."""
    if not g or not g.value:
        return None
    before = g.line.text[:g.start]
    m = re.search(_BRAND, before)
    if not m and not before.strip() and g.line in L:
        i = L.index(g.line)
        prev = L[i - 1].text if i else ""
        m2 = re.search(r'("?[A-Z][A-Z0-9&.\-]*"?)\s*$', prev)
        if re.match(r"\s*BRAND\b", g.line.text[:g.start] + g.line.text[g.start:]) and m2:
            return Field(f"{m2[1]} {g.line.text[g.start:g.end].strip()} ".strip(), g.raw, g.line, g.start, g.end)
    if not m:
        m = re.search(r'("?[A-Z][A-Z0-9&.\-]*"?)\s*$', before) if re.search(r"\bBRAND\s*$", before) else None
    if not m:
        return Field(g.value, g.raw, g.line, g.start, g.end)
    start = m.start(1)
    full = re.sub(r"\s+", " ", f"{g.line.text[start:g.start].strip()} {g.value}")
    return Field(full, g.line.text[start:g.end], g.line, start, g.end)


def _cur_field(d: Doc):
    cs = d.lists.get("currency", [])
    if cs:
        codes = sorted({c.value for c in cs})
        d.f["currency"] = Field(", ".join(codes), cs[0].raw, cs[0].line, cs[0].start, cs[0].end)


PL_HEADER = ("consignee", "shipper", "vessel", "pol", "pod", "sailing", "payment", "origin", "goods_full", "pos",
             "containers", "incoterm", "freight")


def _pl_header(d: Doc, pl: list):
    """The packing list repeats the invoice header: read it on its own, as pl_<field> (rule PL_HEADER, cross-check)."""
    from .extract import _extract_ci
    sub = Doc(d.path, "CI", pl, d.page_width, d.is_draft)
    _extract_ci(sub)
    extra_ci(sub, header_only=True)
    for k in PL_HEADER:
        if sub.f.get(k) and sub.f[k].value not in (None, "", []):
            d.f["pl_" + k] = sub.f[k]
    d.lists["pl_marks_models"] = sub.lists.get("marks_models", [])     # shipping marks printed on the packing list
    if sub.f.get("absent"):
        a = [x for x in sub.f["absent"].value.split(", ") if x in PL_HEADER]
        if a:
            prev = d.f["absent"].value.split(", ") if d.f.get("absent") else []
            d.f["absent"] = Field(", ".join(prev + ["pl_" + x for x in a]), "", d.lines[0], 0, 0)


def extra_ci(d: Doc, header_only: bool = False):
    L = d.lines
    pl_start = next((i for i, l in enumerate(L) if "PACKING LIST" in l.text.upper()), len(L))
    inv, pl = L[:pl_start], L[pl_start:]
    if header_only:                                # the packing-list part on its own: its header is all of it
        inv = L
    # every TTL line: the cover page repeats the attachment's totals
    d.lists["ci_ttls"] = [x for _, l, _m in _search(inv, r"^\s*(?:TTL|TOTAL)\b") for x in [_ttl_ci(l)] if x]
    ttls = []
    for _, l, _m in _search(pl, r"^\s*(?:TTL|TOTAL)\b"):
        mm = re.search(rf"({NUM})\s*{QTY_UNIT}(?:\s+({NUM})\s*CTNS)?\s+({DEC})\s+({DEC})\s+({DEC})\s*$", l.text)
        if not mm:
            continue
        row = dict(qty=F(l, mm, 1, num(mm[1])), nw=F(l, mm, 3, num(mm[3])), gw=F(l, mm, 4, num(mm[4])),
                   cbm=F(l, mm, 5, num(mm[5])))
        cm = re.search(rf"({NUM})\s*CARTON\s*\(\s*S\s*\)", l.text)
        if cm:
            row["ctn"] = F(l, cm, 1, num(cm[1]))
        elif mm[2]:
            row["ctn"] = F(l, mm, 2, num(mm[2]))
        ttls.append(row)
    d.lists["pl_ttls"] = ttls
    # line numbers "1. P/O NO.PR…" on invoice lines; P/O and number of the packing-list line above its figures
    for it in d.items:
        ln = it["qty"].line
        m = re.match(r"\s*(\d+)\.\s*P/?O", ln.text)
        it["no"] = int(m[1]) if m else None
    for p in d.pl_items:
        idx = pl.index(p["qty"].line)
        p["po"], p["no"] = None, None
        for back in pl[max(0, idx - 4):idx + 1][::-1]:
            m = re.match(r"\s*(\d+)\.\s*P/?O\s*NO\.?\s*(" + PO_RE + ")", back.text)
            if m:
                p["no"], p["po"] = int(m[1]), m[2]
                break
    d.f["eta"] = _first(L, rf"\bETA\s*:\s*({DATE_DMY})", conv=parse_date)
    d.f["origin"] = _first(L, r"COUNTRY OF ORIGIN\s*:?\s*([A-Za-z][A-Za-z ]*?)(?:\s{2,}|$)")
    d.f["payment"] = (_first(L, r"TERMS OF PAYMENT\s*:\s*(.+?)(?:\s{2,}|$)")
                      or _first(L, r"Payment Terms\s*:\s*(.+?)(?:\s{2,}|Sailing|$)"))
    # 'CONSIGNEE : NAME', 'CONSIGNEE NAME', 'CONSIGNEENAME' (no space or colon) and the name on the next line
    d.f["consignee"] = _name_after(inv or L, r"\b(?i:CONSIGNEE)\s*:|\bCONSIGNEE(?=\s*[A-Z][A-Z])", flags=0)
    d.lists["currency"] = _money_cur(inv)
    _cur_field(d)
    # P/O list on the cover ("P/O NO.A, B, C" without a line number)
    d.lists["cover_pos"] = [Field(sorted(set(re.findall(PO_RE, l.text))), l.text.strip(), l, 0, len(l.text))
                            for _, l, _m in _search(inv, r"^\s*P/O NO\.?\s*" + PO_RE) if not re.match(r"\s*\d+\.", l.text)][:1]
    # shipping marks on the invoice cover: models listed under SHIPPING MARK & NO.
    block, inside = [], False
    for l in inv:
        if re.search(r"SHIPPING MARK", l.text, re.I):
            inside = True
            continue
        if inside and (re.search(r"DETAILS AS PER|CO\.,? ?LTD|<", l.text) or re.match(r"\s*\d+\.", l.text)):
            break
        if inside:
            block.append(l)
    d.lists["marks_models"] = column_models(block)     # whole or split over two lines
    # header of every page: invoice no. and date (the invoice and the packing list repeat it)
    # seller / shipper: the company line signing the invoice (last company name that is not the buyer)
    buyer = re.sub(r"[^A-Z]", "", (d.f["consignee"].value if d.f.get("consignee") else "").upper())[:12]
    sig = [(l, m) for _, l, m in _search(inv, r"^\s*([A-Z][A-Za-z0-9&().,'\- ]*?" + _LEGAL + r")\s*$")
           if not buyer or not re.sub(r"[^A-Z]", "", m[1].upper()).startswith(buyer)]
    # a labelled shipper block ('SHIPPER : NAME' or the name on the next line) is the shipper; only without a
    # label the company signing the invoice is taken (a signature may share its lines with the shipping marks)
    lab = _name_after(inv or L, r"\bSHIPPER\s*:")
    if lab and re.search(_LEGAL + r"\s*$", lab.value):
        d.f["shipper"] = lab
    elif sig:
        l, m = sig[-1]
        d.f["shipper"] = F(l, m, 1)
    d.f["goods_full"] = _goods_full(inv or L, d.f.get("goods"))
    fob = d.lists.get("fob") or []
    if fob:
        d.f["incoterm"] = Field("FOB " + fob[0].value.upper(), fob[0].raw, fob[0].line, fob[0].start, fob[0].end)
    # fields this invoice layout does not print at all (no label anywhere): "not on this document", not "not read"
    whole = "\n".join(l.text for l in L)
    if not d.f.get("origin"):                      # origin only in the shipping marks: 'MADE IN THAILAND'
        d.f["origin"] = _first(inv or L, r"\bMADE IN\s+([A-Za-z][A-Za-z ]*?[A-Za-z])\s*(?:\s{2,}|$)", flags=0)
    d.f["freight"] = _first(inv or L, r"\bFREIGHT\s+(COLLECT|PREPAID)\b")
    absent = [k for k, rx in (("vessel", r"SHIPPED BY|VESSEL|\bVOY|\bPER\s+S\.?S\.?\b|\bM/?V\b"),
                              ("containers", r"CONTAINER|\bCNTR|\b\d+\s*X\s*\d{2}\s*'?\s*(?:HC|GP|DC|HQ)\b"),
                              ("incoterm", r"\b(?:FOB|FCA|EXW|CFR|CIF|CPT|CIP|DAP|DPU|DDP|INCOTERMS?)\b"),
                              ("freight", r"\bFREIGHT\b"),
                              ("origin", r"\bORIGIN\b|MADE IN"))
              if not d.f.get(k) and not re.search(rx, whole, re.I)]
    if not d.f.get("total_qty") and not any(re.search(rf"{NUM}\s*{QTY_UNIT}", l.text, re.I)
                                            for _, l, _m in _search(inv, r"^\s*(?:TTL|TOTAL)\b")):
        absent.append("total_qty")                   # the invoice part has no quantity total, only line quantities
    if absent:
        d.f["absent"] = Field(", ".join(absent), "", L[0], 0, 0)
    d.lists["headers"] = [dict(no=F(l, m, 1), date=F(l, m, 2, parse_date(m[2])))
                          for _, l, m in _search(L, rf"INVOICE NO\.?\s*:?\s*({DOC_ID})\s+(?:DATE\s*:\s*)?({DATE_DMY})")]
    if not header_only and 0 < pl_start < len(L):
        _pl_header(d, pl)


def extra_sc(d: Doc):
    L = d.lines
    d.f["seller"] = _first(L, r"The Seller\s*:\s*(.+?)\s*$")
    d.f["buyer"] = _first(L, r"The Buyer\s*:\s*(.+?)\s*$")
    d.f["origin"] = _first(L, r"COUNTRY OF ORIGIN\s+([A-Za-z][A-Za-z ]*?)\s*$")
    for i, l, _m in _search(L, r"^\s*NO\.?\s+DESCRIPTION\b"):            # goods heading under the table header
        for nl in L[i + 1:i + 3]:
            seg = re.split(r"\s{2,}", nl.text.strip())[0]           # 'ACME WASHING MACHINES   FOB PORT A'
            if re.fullmatch(r'[A-Z"][A-Z0-9" &/\-]*[A-Z]', seg) and not re.match(r"\s*\d", nl.text):
                k = nl.text.find(seg)
                d.f["goods_full"] = Field(seg, seg, nl, k, k + len(seg))
                break
        break
    fob = d.lists.get("fob") or []
    if fob:
        d.f["incoterm"] = Field("FOB " + fob[0].value.upper(), fob[0].raw, fob[0].line, fob[0].start, fob[0].end)
        d.f["fob_port"] = fob[0]                   # a contract names its loading port only in the Incoterm
    d.lists["currency"] = [c for c in _money_cur(L) if not re.search(r"A/C No", c.line.text, re.I)]   # bank account line
    _cur_field(d)


_CARGO = re.compile(rf"\s*({NUM})\s*{CTN_UNIT}\s*\(?\s*(?:({NUM})\s*(PCS|PIECES?|SETS?|UNITS?)\b)?\s*\)?\s*$")
_BL_INV = re.compile(rf"INVOICE NO\.?\s*:?\s*({DOC_ID})")
_BL_HS = re.compile(r"HS\s*CODE\s*:?\s*([\d.]+)", re.I)
_BL_GOODS = re.compile(r'^\s*("[^"]{6,}"(?:\s+BRAND\s+[A-Z][A-Z /&\-]*[A-Z])?|"?[A-Z][A-Z0-9&.\-]*"?\s+BRAND\s+[A-Z][A-Z /&\-]*[A-Z])\s*$')
_NOT_GOODS = re.compile(r"SHIPPER|SAID TO CONTAIN|LOAD|COUNT|SEAL|FREIGHT", re.I)


def _tails(line):
    """The line and every part of it that starts at a cell (a column) boundary: 'MARKS   500 CARTON(S) 500 PCS'
    -> the whole line, then '500 CARTON(S) 500 PCS' as a line of its own spans."""
    from .pdftext import Line
    cells = line.cells()
    for i in range(len(cells)):
        yield Line(line.page, line.y, [sp for c in cells[i:] for sp in c.spans])


def cargo_blocks(L) -> list:
    """B/L description column, read cell by cell so the shipping-mark column next to it does not matter:
    goods description, HS heading, 'n CARTON(S) m PCS', 'INVOICE NO. x' -> one CargoBlock per invoice."""
    blocks, cur, seen = [], {}, {}

    def close():
        if cur.get("ctn"):
            blocks.append(CargoBlock(**cur))
        cur.clear()
    for l in L:
        for t in _tails(l):
            m = _CARGO.match(t.text)
            if m:
                if cur.get("ctn"):
                    close()
                cur["ctn"] = F(t, m, 1, float(m[1].replace(",", "")))
                if m[2]:
                    cur["qty"], cur["unit"] = F(t, m, 2, float(m[2].replace(",", ""))), F(t, m, 3)
                break
            m = _BL_INV.search(t.text)
            if m and t.text.lstrip().upper().startswith("INVOICE"):
                cur["invoice"] = F(t, m, 1)
                seen.setdefault("invoice", cur["invoice"])
                if cur.get("ctn"):
                    close()
                break
            m = _BL_HS.search(t.text)
            if m and re.match(r"\s*#?\s*HS", t.text, re.I):
                if cur.get("ctn"):
                    close()
                cur["hs"] = F(t, m, 1)
                seen.setdefault("hs", cur["hs"])
                break
            m = _BL_GOODS.match(t.text)
            if m and not _NOT_GOODS.search(m[1]):
                if cur.get("ctn"):
                    close()
                cur.clear()
                cur["goods"] = F(t, m, 1)
                seen.setdefault("goods", cur["goods"])
                break
    close()
    if len(blocks) == 1:                         # one block: everything in the description column is its own
        for k, v in seen.items():
            if getattr(blocks[0], k) is None:
                setattr(blocks[0], k, v)
    return blocks


def extra_bl(d: Doc):
    L = d.lines
    d.f["shipper"] = _name_after(L, r"\[ Shipper \]")
    c = _name_after(L, r"\[ Consignee \]")
    if c:                                          # '0123456789#BUYER CO., LTD.': the tax id before '#' is not the name
        name = re.sub(r"^\d+\s*#\s*", "", c.value)
        name = re.sub(r"\s+DRAF?T?$", "", name).strip()
        k = c.line.text.find(name)
        c = Field(name, name, c.line, k, k + len(name)) if k >= 0 else Field(name, name, c.line, 0, 0)
    d.f["consignee"] = c
    pod_l = d.f.get("pod").line if d.f.get("pod") else None
    m = re.search(r"^[A-Z ]+,\s*([A-Z][A-Z ]+?)(?:\s{2,}|$)", pod_l.text) if pod_l else None
    d.f["dest_country"] = F(pod_l, m, 1) if m else None
    d.f["goods_full"] = _goods_full(L, d.f.get("goods"))
    d.f["freight"] = _first(L, r"\bFREIGHT\s+(COLLECT|PREPAID)\b")
    d.f["origin"] = _first(L, r"\bMADE IN\s+([A-Za-z][A-Za-z ]*?[A-Za-z])\s*(?:\s{2,}|$)", flags=0)    # in the shipping marks
    whole = "\n".join(l.text for l in L)
    absent = [k for k, rx in (("origin", r"MADE IN|\bORIGIN\b"), ("freight", r"\bFREIGHT\s+(?:COLLECT|PREPAID)"),
                              ("final_dest", r"FINAL DESTINATION\s*:"))
              if not d.f.get(k) and not re.search(rx, whole, re.I)]
    if absent:                                     # not printed on this B/L: "not on this document", not "not read"
        d.f["absent"] = Field(", ".join(absent), "", L[0], 0, 0)
    d.cargo_blocks = cargo_blocks(L)
    if not d.f.get("bl_qty"):                      # quantity per invoice, one block each: add them up
        rows = [b for b in d.cargo_blocks if b.qty]
        if rows:
            d.lists["bl_qty_rows"] = [b.qty for b in rows]
            ctns = [b.ctn for b in rows]
            total, total_ctn = sum(f.value for f in d.lists["bl_qty_rows"]), sum(f.value for f in ctns)
            b0 = rows[0]
            if len(rows) == 1:
                d.f["bl_qty"] = Field(total, b0.qty.raw, b0.qty.line, b0.qty.start, b0.qty.end)
                d.f["bl_qty_ctn"] = Field(total_ctn, b0.ctn.raw, b0.ctn.line, b0.ctn.start, b0.ctn.end)
                ph = b0.ctn.line
                d.f["bl_qty_phrase"] = Field(ph.text[b0.ctn.start:b0.unit.end], ph.text[b0.ctn.start:b0.unit.end], ph,
                                             b0.ctn.start, b0.unit.end)
            else:                                  # one field over all the quantities: the evidence box covers them
                from .pdftext import Line
                def over(fs):
                    spans = [sp for f in fs if f.page == b0.qty.page for sp in f.line.spans_for(f.start, f.end)]
                    return Line(b0.qty.page, b0.qty.line.y, spans)
                both, both_c = over(d.lists["bl_qty_rows"]), over(ctns)
                d.f["bl_qty"] = Field(total, f"{total:,.0f}", both, 0, len(both.text))
                d.f["bl_qty_ctn"] = Field(total_ctn, f"{total_ctn:,.0f}", both_c, 0, len(both_c.text))
            d.f["bl_unit"] = b0.unit
    # every invoice the B/L covers: one B/L can carry several invoices, one 'INVOICE NO.' line each
    d.lists["invoice_nos"] = [F(l, m, 1) for _, l, m in _search(L, rf"INVOICE NO\.?\s*:?\s*({DOC_ID})")]
    if len(d.lists["invoice_nos"]) > 1:            # cross-check shows them all
        f0 = d.lists["invoice_nos"][0]
        d.f["invoice_nos"] = Field(", ".join(f.value for f in d.lists["invoice_nos"]), f0.raw, f0.line, f0.start, f0.end)


_INV_HEAD = re.compile(r"^[A-Z]{2,}[A-Z0-9]*\d[A-Z0-9]*$")
_DATE = re.compile(rf"^{DATE_DMY}$")


def _co_invoices(L) -> list:
    """Box 10 of a Form D, per item: invoice no. above its date in one narrow column. A long number wraps:
    'ABCDEFGH1234' / '567' / '01/02/2026' -> ABCDEFGH1234567 (the pieces are centred, so: overlapping in x). -> [{"no": Field, "date": Field}]"""
    from .pdftext import Line
    out = []
    for i, l in enumerate(L):
        for head in l.spans:
            if not _INV_HEAD.match(head.text.strip()) or len(head.text.strip()) < 6:
                continue
            parts, date = [head], None
            for nl in L[i + 1:i + 4]:
                if nl.page != l.page:
                    break
                col = [s for s in nl.spans if s.bbox[0] < head.bbox[2] and s.bbox[2] > head.bbox[0]]   # same (centred) column
                if not col:
                    continue
                t = col[0].text.strip()
                if _DATE.match(t):
                    date = (nl, col[0])
                    break
                if re.fullmatch(r"[A-Z0-9]{1,8}", t) and len(parts) < 3:
                    parts.append(col[0])
                    continue
                break
            if not date:
                continue
            joined = Line(l.page, l.y, list(parts))         # one line of the pieces: its box covers all of them
            no = "".join(x.text.strip() for x in parts)
            dl = Line(date[0].page, date[0].y, [date[1]])
            out.append(dict(no=Field(no, no, joined, 0, len(joined.text)),
                            date=Field(parse_date(dl.text.strip()), dl.text.strip(), dl, 0, len(dl.text))))
    return out


_HY_HEAD = re.compile(r"^[A-Z][A-Za-z0-9]*-(?:[A-Za-z0-9]+-)*$")
_HY_TAIL = re.compile(r"^[A-Za-z0-9\-]*\([A-Za-z0-9]+\)[A-Za-z]*" + MARK_TAIL + r"$")


def _hyphen_split(page) -> list:
    """Form D box 6: a model split at a hyphen over two lines of one column ('EF-Z30-' above 'PQ(06)-MG')."""
    spans = [(sp["bbox"], sp["text"].strip()) for b in page.get_text("dict")["blocks"] for l in b.get("lines", [])
             for sp in l["spans"] if sp["text"].strip()]
    out = []
    for (b1, t1) in spans:
        if not _HY_HEAD.match(t1):
            continue
        below = [(b2, t2) for b2, t2 in spans if abs(b2[0] - b1[0]) < 5 and 0 < b2[1] - b1[1] < 16 and _HY_TAIL.match(t2)]
        if below:
            b2, t2 = min(below, key=lambda x: x[0][1])
            out.append((t1, t2, (min(b1[0], b2[0]), b1[1], max(b1[2], b2[2]), b2[3])))   # + the box over both lines
    return out


def extra_co(d: Doc):
    L = d.lines
    d.lists["invoices"] = _co_invoices(L)
    for it in d.items:                         # the item line holds the first piece of the number: give it the whole one
        e = next((e for e in d.lists["invoices"] if e["no"].line.spans[0] in it["qty"].line.spans), None)
        if e:
            it["inv_ref"], it["inv_ref_f"] = e["no"].value, e["no"]
    d.f["exporter"] = _name_after(L, r"Goods consigned from", skip_rx=r"Reference No")
    d.f["consignee"] = _name_after(L, r"Goods consigned to")
    d.lists["origin"] = [f for f in (_after(L[i:], r"goods were produced in", r"^\s*([A-Z][A-Z ]+?)(?:\s{2,}|$)")
                                     for i, l, _m in _search(L, r"goods were produced in")) if f]
    d.lists["import_country"] = [f for f in (_after(L[i:], r"^\s*exported to\s*$", r"^\s*([A-Z][A-Z ]+?)(?:\s{2,}|$)")
                                             for i, l, _m in _search(L, r"^\s*exported to\s*$")) if f]
    d.f["origin"] = d.lists["origin"][0] if d.lists["origin"] else None
    d.f["import_country"] = d.lists["import_country"][0] if d.lists["import_country"] else None
    d.lists["pages"] = [dict(n=int(m[1]), of=int(m[2]), f=F(l, m, 0)) for _, l, m in _search(L, r"Page\s*:\s*(\d+)\s*of\s*(\d+)")]
    d.lists["currency"] = _money_cur(L)
    _cur_field(d)
    # box 6 marks split after the colour code: 'EF-Z30(BK)' + 'VN' (extract.py reads the 'CD-Y20PE' + '(BM)VN' split)
    from .pdftext import Line
    have = {f.value for f in d.lists.get("marks_models", [])}
    pdf = __import__("pymupdf").open(d.path)
    for pno, pg in enumerate(pdf):
        t = pg.get_text()
        pairs = re.findall(r"(?m)^(" + MARK_HEAD + r"\([A-Za-z0-9]+\))\s*\n\s*([A-Z]{1,3})\s*$", t)
        pairs += [(a, "") for a in re.findall(r"(?m)^\s*(" + MARK_HEAD + r"\([A-Za-z0-9]+\)(?=[A-Za-z\-])[A-Za-z]{0,3}"
                                              + MARK_TAIL + r")\s*$", t)]          # ...(W1)VN, ...(06)-MG
        for a, b, *box in pairs + _hyphen_split(pg):   # 'EF-Z30-' / 'PQ(06)-MG': split at a hyphen, same column
            if a + b not in have:
                have.add(a + b)
                if box:                            # its place is known: box it there (not by searching the text)
                    from .pdftext import Span
                    ln = Line(pno, (box[0][1] + box[0][3]) / 2, [Span(a + b, box[0], "", 8.0, 0, 0, (box[0][0], box[0][3]))])
                    d.lists.setdefault("marks_models", []).append(Field(a + b, a + b, ln, 0, len(a + b)))
                else:
                    d.lists.setdefault("marks_models", []).append(Field(a + b, a, Line(pno, 0.0), 0, 0))
    pdf.close()


EXTRA = dict(CI=extra_ci, SC=extra_sc, BL=extra_bl, CO=extra_co)
