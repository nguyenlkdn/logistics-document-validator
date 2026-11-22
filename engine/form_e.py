"""Form E (ASEAN-China Free Trade Area certificate of origin), read into the same fields as a Form D.

The goods table is read COLUMN BY COLUMN: the box headings '5.item number', '6.Marks', '7.Number and type of
packages', '8.Origin criteria', '9.Gross weight … value (FOB)', '10.Number, date of invoices' give the columns'
left edges on every page. Box 7 is printed in a narrow column that cuts words anywhere ('SE-' / 'VEN', even a
figure: '(12' / '5)'); the pieces are joined back before reading. An item that starts at the bottom of a page goes
on at the top of the next page. The total ('TOTAL PACKED IN … (N) CARTONS ONLY') follows the last item in box 7.

Each value keeps its place: a value printed over several lines is boxed over all its pieces.
"""
import re

from .pdftext import Line

_HEADS = (("item", r"^5\.\s*item"), ("marks", r"^6\.\s*Marks"), ("desc", r"^7\.\s*Number"),
          ("crit", r"^8\.\s*Origin"), ("qty", r"^9\.\s*Gross"), ("inv", r"^10\.\s*Number"))
_MON = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[A-Z]*"
DATE_E = rf"(?:{_MON}\.?\s*\d{{1,2}}\s*,\s*\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})"
_PKG = r"(CTNS?|CARTONS?|PACKAGES?|CASES?|PALLETS?|BOX(?:ES)?)"
_LEGAL_END = r"\b(?:LTD|LIMITED|INC|CORPORATION|CORP|LLC|GMBH)\b\.?"     # where a company name ends


def is_form_e(text: str) -> bool:
    t = text.upper()
    return "FORM E" in t and "CERTIFICATE OF ORIGIN" in t and ("ASEAN-CHINA" in t or "ACFTA" in t)


class Piece:
    """Text joined from spans of several lines, each character knowing its span: a Field over any part of it is
    boxed over exactly the pieces it covers."""

    def __init__(self, spans_by_line):
        self.text, self.owner = "", []           # owner[i] = (line, span) of character i (None for joints)
        prev = None
        for ln, sp in spans_by_line:
            t = sp.text.strip()
            if not t:
                continue
            if prev is not None:
                # a word cut at the column edge ('SE-' / 'VEN'); a model's own hyphen ('MODEL NO: AB-X10-') stays
                if prev.endswith("-") and not re.search(r"MODEL\s*(?:NO)?\.?\s*:?\s*\S+-$", self.text[-40:]) \
                        and re.match(r"[A-Za-z]", t):
                    self.text, self.owner = self.text[:-1], self.owner[:-1]      # 'SE-' + 'VEN' -> 'SEVEN'
                elif re.search(r"[\d(]$", prev) and re.match(r"[\d)]", t):
                    pass                                                       # '(12' + '5)' -> '(125)'
                else:
                    self.text += " "
                    self.owner.append(None)
            self.text += t
            self.owner += [(ln, sp)] * len(t)
            prev = t

    def field(self, value, a, b):
        """A Field for characters a:b: its line holds the spans it covers (one box over all of them)."""
        from .extract import Field
        spans, first = [], None
        for o in self.owner[a:b]:
            if o is not None and o[1] not in spans:
                spans.append(o[1])
                first = first or o[0]
        if not spans:
            return Field(value, self.text[a:b], Line(0, 0.0), 0, 0)
        ln = Line(first.page, first.y, spans)
        return Field(value, self.text[a:b], ln, 0, len(ln.text))


def _borders(path, page, top, end):
    """x of the vertical rules that run down the goods table on a page (the column borders)."""
    import pymupdf
    xs = set()
    with pymupdf.open(path) as pdf:
        for dr in pdf[page].get_drawings():
            for it in dr["items"]:
                if it[0] == "l":
                    a, b = it[1], it[2]
                    if abs(a.x - b.x) < 1 and min(a.y, b.y) < top + 40 and max(a.y, b.y) > end - 40:
                        xs.add(round(a.x, 1))
                elif it[0] == "re":
                    r = it[1]
                    if r.width < 2 and r.y0 < top + 40 and r.y1 > end - 40:
                        xs.add(round(r.x0, 1))
    return sorted(xs)


def _cols(L, path=None):
    """Per page: the left edge of each goods-table column, and the y of the header / the end of the table."""
    pages = {}
    for l in L:
        for s in l.spans:
            for name, rx in _HEADS:
                if re.match(rx, s.text.strip(), re.I):
                    pages.setdefault(l.page, {})[name] = (s.bbox[0], l.y)
    out = {}
    for p, h in pages.items():
        if "desc" not in h or "item" not in h:
            continue
        top = max(y for _, y in h.values())
        end = min((l.y for l in L if l.page == p and l.y > top and re.search(r"11\.\s*Declaration", l.text)),
                  default=1e9)
        edges = sorted((x, n) for n, (x, _) in h.items())
        bs = _borders(path, p, top, end) if path else []
        if len(bs) >= len(edges):                  # a centred value may start left of its heading: use the rules
            edges = [(max((b for b in bs if b <= x + 2), default=x - 12), n) for x, n in edges]
        else:
            edges = [(x - 12, n) for x, n in edges]
        out[p] = dict(edges=edges, top=top, end=end)
    return out


def _column_of(x, edges):
    name = None
    for ex, n in edges:
        if x >= ex - 1:
            name = n
    return name


def _table(L, cols):
    """Rows of the goods table: [(line, {column: [span]})] in reading order over all pages."""
    rows = []
    for l in L:
        c = cols.get(l.page)
        if not c or not (c["top"] + 30 < l.y < c["end"]):          # below the header text, above box 11
            continue
        by = {}
        for s in l.spans:
            if not s.text.strip():
                continue
            by.setdefault(_column_of(s.bbox[0], c["edges"]), []).append(s)
        rows.append((l, by))
    return rows


def extract(d):
    """Form E goods table, totals and header boxes into the Form D fields (items, total_ctn, departure …)."""
    from .extract import NUMBER_WORDS, Field, F, _first, _vessel
    from .util import num, parse_date
    L = d.lines
    d.form = "E"
    # box 3: departure date, vessel, port of discharge; the route line names the port of loading
    for i, l in enumerate(L):
        if re.search(r"Departure date", l.text, re.I):
            for nl in L[i:i + 3]:
                m = re.search(rf"({DATE_E})", nl.text)
                if m:
                    d.f["departure"] = F(nl, m, 1, parse_date(m[1]))
                    break
            break
    d.f["vessel"] = _first(L, r"Vessel.s name(?:/Aircraft etc\.?)?\s*[:.]?\s*(\S.+?)(?:\s{2,}|$)", conv=_vessel)
    d.f["pod"] = _first(L, r"^\s*Port of Discharge\s+([A-Z][A-Z ]+?)(?=,|\s{2,}|$)")
    d.lists["pod"] = [d.f["pod"]] if d.f["pod"] else []
    d.f["route_pol"] = _first(L, r"\bFROM\s+([A-Z][A-Z ]+?)\s*,.*?\bTO\b", flags=0)
    d.f["co_no"] = _first(L, r"Reference No\.?\s*([A-Z0-9]{8,})")
    cols = _cols(L, d.path)
    rows = _table(L, cols)
    # items: an item number in column 5 starts an item; everything below it (also on the next page) belongs to it
    blocks, cur, tail = [], None, []
    for l, by in rows:
        nums = [s for s in by.get("item", []) if re.fullmatch(r"\d{1,3}", s.text.strip())]
        if nums:
            cur = dict(no=int(nums[0].text.strip()), no_line=l, rows=[])
            blocks.append(cur)
        if cur is not None:
            cur["rows"].append((l, by))
    items = []
    total_rows = []
    for b in blocks:
        desc = []
        for l, by in b["rows"]:
            for s in by.get("desc", []):
                desc.append((l, s))
        # the total and the third-party note follow the last item in box 7: not part of it
        cut = next((k for k, (l, s) in enumerate(desc) if re.match(r"\s*(TOTAL\b|\*{3})", s.text)), None)
        if cut is not None:
            total_rows += desc[cut:]
            desc = desc[:cut]
        p7 = Piece(desc)
        t7 = p7.text
        it = dict(no=b["no"], hs=None, hs_f=None, qty=None, inv_ref=None, inv_date=None, pkg_words=None,
                  pkg_fig=None, per_ctn=None, model=None, goods=None, goods_full=None)
        m = re.search(rf"^(.*?)\(\s*([\dOIlSB,]+)\s*\)\s*{_PKG}\b\s*(?:OF\s+)?(.*?)(?=\s+1\s*(?:CTNS?|CARTONS?)\s*=|\s+MODEL\b|\s+HS\s*CODE|$)", t7)
        words_f = None
        if m:
            tw = m[1].split()
            k0 = m.start(1)
            while tw and tw[0].split("-")[0] not in NUMBER_WORDS:      # words before the number are not the number
                k0 += len(tw[0]) + 1
                tw.pop(0)
            w = " ".join(tw)
            it["pkg_words"] = w or None
            if w:
                words_f = p7.field(w, k0, k0 + len(w))
            if re.fullmatch(r"[\d,]+", m[2]):
                it["pkg_fig"] = p7.field(num(m[2]), m.start(2), m.end(2))
            else:                                       # '(7S) CTNS': printed but not a number -> VALUE_UNREADABLE
                bad = p7.field(None, m.start(2), m.end(2))
                bad.status = "UNREADABLE"
                it["pkg_fig_unread"] = bad
            if m[4].strip():
                g = m[4].strip()
                it["goods"] = p7.field(g, m.start(4), m.start(4) + len(g))
                it["goods_full"] = it["goods"]
        m = re.search(r"1\s*(?:CTNS?|CARTONS?)\s*=\s*(\d+)\s*(?:SETS?|PCS|PIECES?|UNITS?)", t7, re.I)
        it["per_ctn"] = int(m[1]) if m else None
        model_f = None
        m = re.search(r"MODEL\s*(?:NO)?\.?\s*:?\s*([A-Z0-9][A-Za-z0-9\-()/.]*[A-Za-z0-9)])", t7)
        if m:
            it["model"] = m[1]
            model_f = p7.field(m[1], m.start(1), m.end(1))
        m = re.search(r"HS\s*CODE\s*:?\s*(\d{4}(?:\.?\d{2}){0,3})", t7)
        if m:
            it["hs"] = m[1]
            it["hs_f"] = p7.field(m[1], m.start(1), m.end(1))
        # box 9: quantity ('250SETS') and, for an RVC item, its FOB value ('USD:1234.50')
        q9 = Piece([(l, s) for l, by in b["rows"] for s in by.get("qty", [])])
        m = re.search(r"([\d,]+(?:\.\d+)?)\s*(SETS?|PCS|PIECES?|UNITS?)\b", q9.text)
        if m:
            it["qty"] = q9.field(num(m[1]), m.start(1), m.end(1))
            it["unit"] = m[2]
        m = re.search(r"(USD|US\$)\s*[:.]?\s*([\d,]+(?:\.\d+)?)", q9.text)
        it["fob"] = q9.field(num(m[2]), m.start(2), m.end(2)) if m else None
        # box 8: origin criterion ('"PE"', '"WO"', '40%')
        c8 = Piece([(l, s) for l, by in b["rows"] for s in by.get("crit", [])])
        it["criterion"] = c8.field(c8.text.strip('" '), 0, len(c8.text)) if c8.text else None
        # box 10: invoice number (wrapped: 'ABC1234' / '5') above its date
        inv = [(l, s) for l, by in b["rows"] for s in by.get("inv", [])]
        k = next((n for n, (l, s) in enumerate(inv) if re.search(DATE_E, s.text)), None)
        if inv:
            no_part = Piece(inv[:k] if k is not None else inv)
            no_part.text = no_part.text.replace(" ", "")
            no_part.owner = [o for o in no_part.owner if o is not None]
            if no_part.text:
                it["inv_ref"] = no_part.text
                it["inv_ref_f"] = no_part.field(no_part.text, 0, len(no_part.text))
            if k is not None:
                dl, ds = inv[k]
                dm = re.search(DATE_E, ds.text)
                dp = Piece([(dl, ds)])
                it["inv_date"] = dp.field(parse_date(dm[0]), 0, len(dp.text))
        if it["qty"] is None:
            continue                               # not an item row (a note in column 5)
        d.lists.setdefault("pkg_words_f", []).append(words_f)
        d.lists.setdefault("model_f", []).append(model_f)
        items.append(it)
    # box 10 is printed once for the items under it (often only beside item 1): it names their invoice too
    last = None
    for it in items:
        if it.get("inv_ref"):
            last = it
        elif last is not None:
            it["inv_ref"], it["inv_ref_f"], it["inv_date"] = last["inv_ref"], last.get("inv_ref_f"), last["inv_date"]
            it["inv_shared"] = True
    d.items = items
    # 'TOTAL PACKED IN ONE THOUSAND … (500) CARTONS ONLY.' and the third-party note under it
    pt = Piece(total_rows)
    m = re.search(r"THIRD-?\s*PARTY OPERATOR\s*:\s*(.+?)(?:\s\*{3}|$)", pt.text)
    if m:
        n = re.search(_LEGAL_END, m[1])
        name = m[1][:n.end()].strip() if n else m[1].strip()
        d.f["third_party"] = pt.field(name, m.start(1), m.start(1) + len(name))
    m = re.search(rf"TOTAL\s+(?:PACKED\s+IN\s+)?((?:[A-Z]+[\- ])*[A-Z]+)\s*\(\s*([\d,]+)\s*\)\s*{_PKG}", pt.text)
    if m:
        d.f["total_ctn"] = pt.field(num(m[2]), m.start(2), m.end(2))
        tw = m[1].split()
        k0 = m.start(1)
        while tw and tw[0].split("-")[0] not in NUMBER_WORDS:
            k0 += len(tw[0]) + 1
            tw.pop(0)
        w = " ".join(tw)
        d.f["total_ctn_words"] = pt.field(w, k0, k0 + len(w)) if w else None
    # Form E prints no quantity / value total: the item boxes are all there is (not 'not read')
    absent = [k for k in ("total_qty", "total_value") if not d.f.get(k)]
    if absent:
        d.f["absent"] = Field(", ".join(absent), "", L[0], 0, 0)


def extra(d):
    """Header boxes: exporter, consignee, origin / importing country, third-party invoicing, page numbers."""
    from .extract import Field, F, _search
    from .extract_net import _cur_field, _money_cur
    L = d.lines

    def block_after(label_rx, stop_rx):
        """The company name under a box label; a name wrapped onto the next line is read whole (up to 'LTD.')."""
        for i, l in enumerate(L):
            if re.search(label_rx, l.text, re.I):
                x0 = l.spans[0].bbox[0]
                got = []
                for nl in L[i + 1:i + 6]:
                    s = next((s for s in nl.spans if abs(s.bbox[0] - x0) < 15 and s.text.strip()), None)
                    if s is None or re.search(stop_rx, s.text, re.I):
                        if got:
                            break
                        continue
                    got.append((nl, s))
                    if len(got) == 3 or re.search(_LEGAL_END, " ".join(x[1].text for x in got)):
                        break
                if not got:
                    return None
                p = Piece(got)
                p.text = p.text.replace("- ", "-")
                m = re.search(_LEGAL_END, p.text)
                end = m.end() if m else len(Piece(got[:1]).text)
                return p.field(p.text[:end].strip(), 0, end)
        return None

    d.f["exporter"] = block_after(r"Products consigned from", r"^\s*country\)")
    d.f["consignee"] = block_after(r"Products consigned to", r"^\s*$")
    d.lists["invoices"] = [dict(no=it["inv_ref_f"], date=it["inv_date"]) for it in d.items
                           if it.get("inv_ref_f") and it.get("inv_date")]

    def word_after(label_rx):
        out = []
        for i, l, _m in _search(L, label_rx):
            for nl in L[i + 1:i + 4]:
                m = re.match(r"\s*([A-Z][A-Z ]+?[A-Z])\s*(?:\s{2,}|$)", nl.text)
                if m and not re.match(r"\s*\(", nl.text):
                    out.append(F(nl, m, 1))
                    break
        return out

    d.lists["origin"] = word_after(r"products were produced in\s*$")
    d.lists["import_country"] = word_after(r"products exported to\s*$")
    d.f["origin"] = d.lists["origin"][0] if d.lists["origin"] else None
    d.f["import_country"] = d.lists["import_country"][0] if d.lists["import_country"] else None
    d.lists["pages"] = [dict(n=int(m[1]), of=int(m[2]), f=F(l, m, 0))
                        for _, l, m in _search(L, r"\(\s*PAGE\s*(\d+)\s*OF\s*(\d+)\s*\)")]
    d.lists["currency"] = _money_cur(L)
    _cur_field(d)
    if not d.lists["currency"]:                   # no FOB value printed (no RVC item): no currency on the form
        a = d.f.get("absent")
        d.f["absent"] = Field(((a.value + ", ") if a else "") + "currency", "", L[0], 0, 0)


def _first_text(L, rx):
    from .extract import F, _search
    for _, l, m in _search(L, rx):
        return F(l, m, 1)
    return None
