"""Extra fields for the cross-document ("net") and self-consistency rules. Runs after the per-kind extractors in
extract.load() and only adds fields; nothing that the older rules use is changed.

Every field keeps its place in the PDF (Field), so findings can be boxed on the page.
"""
import re

from .extract import MODEL_RE, PO_RE, Doc, F, Field, _after, _first, _search
from .util import num, parse_date

CURRENCIES = ("USD", "EUR", "JPY", "THB", "VND", "CNY", "SGD", "GBP")
_CUR_RX = re.compile(r"\b(" + "|".join(CURRENCIES) + r")\b|U\.?\s?S\.?\s+DOLLARS?", re.I)
_LABELS = re.compile(r"^\s*(\[|\d+\.\s|Reference No|ACCOUNTEE|CONSIGNEE|SHIP TO|Attn|Address|TEL\b)", re.I)


def _name_after(L, label_rx, skip_rx=None, max_ahead=3):
    """Party name on the first line after a label line (or after the label on the same line)."""
    for i, l, m in _search(L, label_rx):
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
    for key, rx, conv in (("ctn", r"([\d,]+)\s*CARTON\(S\)", num), ("qty", r"([\d,]+)\s*(?:SET\(S\)|SETS?|PCS)\b", num),
                          ("amount", r"([\d,]+\.\d{2})\s*(?:IN USD)?\s*$", num)):
        mm = re.search(rx, t)
        if mm:
            out[key] = F(l, mm, 1, conv(mm[1]))
    return out


def _cur_field(d: Doc):
    cs = d.lists.get("currency", [])
    if cs:
        codes = sorted({c.value for c in cs})
        d.f["currency"] = Field(", ".join(codes), cs[0].raw, cs[0].line, cs[0].start, cs[0].end)


def extra_ci(d: Doc):
    L = d.lines
    pl_start = next((i for i, l in enumerate(L) if "PACKING LIST" in l.text.upper()), len(L))
    inv, pl = L[:pl_start], L[pl_start:]
    # every TTL line: the cover page repeats the attachment's totals
    d.lists["ci_ttls"] = [x for _, l, _m in _search(inv, r"^\s*(?:TTL|TOTAL)\b") for x in [_ttl_ci(l)] if x]
    ttls = []
    for _, l, _m in _search(pl, r"^\s*(?:TTL|TOTAL)\b"):
        mm = re.search(r"([\d,]+)\s*(?:SET\(S\)|PCS)(?:\s+([\d,]+)\s*CTNS)?\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s*$",
                       l.text)
        if not mm:
            continue
        row = dict(qty=F(l, mm, 1, num(mm[1])), nw=F(l, mm, 3, num(mm[3])), gw=F(l, mm, 4, num(mm[4])),
                   cbm=F(l, mm, 5, num(mm[5])))
        cm = re.search(r"([\d,]+)\s*CARTON\(S\)", l.text)
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
    d.f["eta"] = _first(L, r"\bETA\s*:\s*(\d{1,2}/\d{1,2}/\d{4})", conv=parse_date)
    d.f["origin"] = _first(L, r"COUNTRY OF ORIGIN\s*:?\s*([A-Za-z][A-Za-z ]*?)(?:\s{2,}|$)")
    d.f["payment"] = (_first(L, r"TERMS OF PAYMENT\s*:\s*(.+?)(?:\s{2,}|$)")
                      or _first(L, r"Payment Terms\s*:\s*(.+?)(?:\s{2,}|Sailing|$)"))
    d.f["consignee"] = _name_after(inv or L, r"\bCONSIGNEE\s*:")
    d.lists["currency"] = _money_cur(inv)
    _cur_field(d)
    # P/O list on the cover ("P/O NO.A, B, C" without a line number)
    d.lists["cover_pos"] = [Field(sorted(set(re.findall(PO_RE, l.text))), l.text.strip(), l, 0, len(l.text))
                            for _, l, _m in _search(inv, r"^\s*P/O NO\.?\s*" + PO_RE) if not re.match(r"\s*\d+\.", l.text)][:1]
    # shipping marks on the invoice cover: models listed under SHIPPING MARK & NO.
    marks, inside = [], False
    for l in inv:
        if re.search(r"SHIPPING MARK", l.text, re.I):
            inside = True
            continue
        if inside and (re.search(r"DETAILS AS PER|CO\.,? ?LTD|<", l.text) or re.match(r"\s*\d+\.", l.text)):
            break
        if inside:
            m = re.match(r"\s*(" + MODEL_RE[2:] + r")\s*$", l.text)
            if m:
                marks.append(F(l, m, 1))
    d.lists["marks_models"] = marks
    # header of every page: invoice no. and date (the invoice and the packing list repeat it)
    d.lists["headers"] = [dict(no=F(l, m, 1), date=F(l, m, 2, parse_date(m[2])))
                          for _, l, m in _search(L, r"INVOICE NO\.?\s*([A-Z0-9]{8,})\s+DATE\s*:\s*(\d{1,2}/\d{1,2}/\d{4})")]


def extra_sc(d: Doc):
    L = d.lines
    d.f["seller"] = _first(L, r"The Seller\s*:\s*(.+?)\s*$")
    d.f["buyer"] = _first(L, r"The Buyer\s*:\s*(.+?)\s*$")
    d.f["origin"] = _first(L, r"COUNTRY OF ORIGIN\s+([A-Za-z][A-Za-z ]*?)\s*$")
    d.lists["currency"] = [c for c in _money_cur(L) if not re.search(r"A/C No", c.line.text, re.I)]   # bank account line
    _cur_field(d)


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
    # every invoice the B/L covers: one B/L can carry several invoices, one 'INVOICE NO.' line each
    d.lists["invoice_nos"] = [F(l, m, 1) for _, l, m in _search(L, r"INVOICE NO\.?\s*([A-Z0-9]{8,})")]
    if len(d.lists["invoice_nos"]) > 1:            # cross-check shows them all
        f0 = d.lists["invoice_nos"][0]
        d.f["invoice_nos"] = Field(", ".join(f.value for f in d.lists["invoice_nos"]), f0.raw, f0.line, f0.start, f0.end)


_INV_HEAD = re.compile(r"^[A-Z]{2,}[A-Z0-9]*\d[A-Z0-9]*$")
_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


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
    # box 6 marks split after the colour code: 'ER-SM20(W1)' + 'VN' (extract.py reads the 'MM2-MG20PE' + '(BM)VN' split)
    from .pdftext import Line
    have = {f.value for f in d.lists.get("marks_models", [])}
    pdf = __import__("pymupdf").open(d.path)
    for pno, pg in enumerate(pdf):
        for a, b in re.findall(r"(?m)^([A-Z][A-Z0-9]*-[A-Z0-9\-]+\([A-Z0-9]+\))\s*\n\s*([A-Z]{1,3})\s*$", pg.get_text()):
            if a + b not in have:
                have.add(a + b)
                d.lists.setdefault("marks_models", []).append(Field(a + b, a, Line(pno, 0.0), 0, 0))
    pdf.close()


EXTRA = dict(CI=extra_ci, SC=extra_sc, BL=extra_bl, CO=extra_co)
