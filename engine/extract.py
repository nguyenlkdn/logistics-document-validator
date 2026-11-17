"""Classify logistics PDFs and extract fields (each field remembers where it sits in the PDF)."""
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .pdftext import Line, doc_lines
from .util import num, parse_date

MODEL_RE = r"\b[A-Z][A-Z0-9]*-[A-Z0-9\-]+\([A-Z0-9]+\)[A-Z]*"   # e.g. PLK-45SF(WT)VN, MM2-MG20PE(BM)VN
PO_RE = r"PR\d{12}"


@dataclass
class Field:
    value: object
    raw: str
    line: Line
    start: int
    end: int

    @property
    def page(self):
        return self.line.page


def F(line: Line, m: re.Match, group=1, value=None) -> Field:
    raw = m.group(group)
    return Field(raw if value is None else value, raw, line, m.start(group), m.end(group))


@dataclass
class Doc:
    path: Path
    kind: str                       # CI (invoice+PL), SC, BL, CO
    lines: list
    page_width: float
    is_draft: bool
    f: dict = field(default_factory=dict)        # scalar fields -> Field
    items: list = field(default_factory=list)    # invoice / SC / CO lines
    pl_items: list = field(default_factory=list)
    lists: dict = field(default_factory=dict)    # multi-occurrence fields -> [Field]

    @property
    def name(self):
        return self.path.name


def classify(text: str) -> str | None:
    t = text.upper()
    if "SALES CONTRACT" in t:
        return "SC"
    if "FORM D" in t and "CERTIFICATE OF ORIGIN" in t:
        return "CO"
    if "[ SHIPPER ]" in t or "BILL OF LADING" in t:
        return "BL"
    if "COMMERCIAL INVOICE" in t or "PACKING LIST" in t:
        return "CI"
    return None


def _search(lines, pattern, flags=re.I):
    rx = re.compile(pattern, flags)
    for i, l in enumerate(lines):
        m = rx.search(l.text)
        if m:
            yield i, l, m


def _first(lines, pattern, group=1, conv=None, flags=re.I):
    for _, l, m in _search(lines, pattern, flags):
        return F(l, m, group, conv(m.group(group)) if conv else None)
    return None


def _after(lines, label_pattern, value_pattern, group=1, conv=None):
    """Value on the first line after a label line."""
    for i, l, _ in _search(lines, label_pattern):
        for nl in lines[i + 1:i + 3]:
            m = re.search(value_pattern, nl.text, re.I)
            if m:
                return F(nl, m, group, conv(m.group(group)) if conv else None)
    return None


def _model_near(lines, i, span=3, backward=False):
    after, before = lines[i + 1:i + 1 + span], lines[max(0, i - span):i][::-1]
    for l in [lines[i]] + (before + after if backward else after + before):
        m = re.search(MODEL_RE, l.text)
        if m:
            return m.group(0)
    return None


def _fob_all(lines):
    out = []
    for _, l, m in _search(lines, r"\bFOB ([A-Z][A-Z ]*?[A-Z])(?=\s{2,}|\s*$| IN USD)", 0):
        out.append(F(l, m, 1))
    return out


def _vessel(raw: str):
    """(vessel name, voyage). The separator is only a writing style: Form D needs 'V.', the B/L often uses '/', so
    'ABC STAR V.0123-045A' = 'ABC STAR/ 0123-045A' = 'ABC STAR / V. 0123-045A' = 'ABC STAR VOY. 0123-045A'
    = 'ABC STAR 0123-045A' (a last word with a digit is the voyage)."""
    t = re.sub(r"[\s,.;]+$", "", raw.strip().upper())
    m = (re.match(r"(.+?)\s*(?:/\s*)?(?:\bV(?:OY(?:AGE)?)?\.?\s*(?:NO\.?)?\s*)(\d[\w\-]*)$", t)      # V. / V / VOY. / VOYAGE NO.
         or re.match(r"(.+?)\s*/\s*(\w[\w\-]*)$", t)                                              # NAME / VOY
         or re.match(r"(.+?[A-Z])\s+(\d[\w\-]*)$", t))                                            # NAME VOY
    if not m:
        return (t, "")
    name = re.sub(r"[\s/,]+$", "", m[1]).strip()
    return (re.sub(r"\s+", " ", name), m[2])


# ---------------------------------------------------------------- per kind
def _extract_ci(d: Doc):
    L = d.lines
    pl_start = next((i for i, l in enumerate(L) if "PACKING LIST" in l.text.upper()), len(L))
    inv, pl = L[:pl_start], L[pl_start:]
    d.f["invoice_no"] = _first(L, r"INVOICE NO\.?:?\s*([A-Z0-9]{8,})")
    d.f["invoice_date"] = (_first(L, r"\bDATE\s*:\s*(\d{1,2}/\d{1,2}/\d{4})", conv=parse_date)
                           or _first(L, r"Invoice Date:\s*(\S+)", conv=parse_date))
    d.f["vessel"] = _first(L, r"SHIPPED BY\s*:\s*(.+?)(?:\s{2,}|$)", conv=_vessel)
    d.f["pol"] = (_first(L, r"Port of Loading\s*:\s*([A-Za-z ]+)") or _first(L, r"FROM\s*:\s*([A-Z ]+?)(?:\s{2,}|$)"))
    d.f["pod"] = (_first(L, r"Port of Discharge\s*:\s*([A-Z ]+?)(?=,|\s{2,}|$)")
                  or _first(L, r"\bTO\s*:\s*([A-Z ]+?)(?:\s{2,}|$)"))
    d.lists["pod"] = [F(l, m, 1) for _, l, m in _search(L, r"Port of Discharge\s*:\s*([A-Z ]+?)(?=,|\s{2,}|$)")]
    d.f["sailing"] = (_first(L, r"Sailing On Or About\s*:\s*(\d.+?)(?:\s{2,}|$)", conv=parse_date)
                      or _after(L, r"SAILING ON OR ABOUT", r"^\s*(\d{1,2}/\d{1,2}/\d{4})", conv=parse_date))
    d.f["containers"] = _first(L, r"TOTAL CONTAINER\s*:\s*(\d+)\s*x", conv=int)
    for _, l, m in _search(L, r"TOTAL CONTAINER\s*:\s*((?:\d+\s*[xX]\s*\d{2}\s*'?\s*[A-Z]{2}[\s+,&]*)+)"):
        d.lists["cntr_types"] = [F(l, m, 1)]
        break
    d.f["goods"] = _first(L, r'"?TOSHIBA"?\s*BRAND\s+([A-Z][A-Z ]*?[A-Z])\s*(?:\s{2,}|$)')
    pos = set()
    for _, l, m in _search(L, PO_RE, 0):
        pos.update(re.findall(PO_RE, l.text))
    d.f["pos"] = Field(sorted(pos), "", L[0], 0, 0)
    d.lists["fob"] = _fob_all(L)

    item_rx = r"([\d,]+)\s*(?:SET\(S\)|PCS|SETS)\s{2,}([\d,]+\.\d{2})\s{2,}([\d,]+\.\d{2})\s*$"
    for i, l, m in _search(inv, item_rx):
        po = re.search(PO_RE, l.text)
        d.items.append(dict(model=_model_near(inv, i), qty=F(l, m, 1, num(m[1])), price=F(l, m, 2, num(m[2])),
                            amount=F(l, m, 3, num(m[3])), po=po.group(0) if po else None))
    for _, l, m in _search(inv, r"^(?:TTL|TOTAL)\b.*?(?:USD\s*)?([\d,]+\.\d{2})\s*$"):
        d.f["total_amount"] = F(l, m, 1, num(m[1]))
    for _, l, m in _search(inv, r"^(?:TTL|TOTAL)\b.*?([\d,]+)\s*(?:SET\(S\)|PCS)"):
        d.f["total_qty"] = F(l, m, 1, num(m[1]))
    words = [l.text for l in inv if re.search(r"\bSAY\b", l.text, re.I)]
    if words:
        i = inv.index(next(l for l in inv if l.text in words))
        d.f["amount_words"] = Field(" ".join(x.text for x in inv[i:i + 2]), "", inv[i], 0, 0)

    pl_rx = (r"([\d,]+)\s*(?:SET\(S\)|PCS)(?:\s+([\d,]+)\s*CTNS)?\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s*$")
    for i, l, m in _search(pl, pl_rx):
        nums = dict(qty=F(l, m, 1, num(m[1])), nw=F(l, m, 3, num(m[3])), gw=F(l, m, 4, num(m[4])),
                    cbm=F(l, m, 5, num(m[5])))
        ctn_m = re.search(r"([\d,]+)\s*CARTON\(S\)", l.text)
        if re.match(r"\s*(TTL|TOTAL)", l.text, re.I) or l.text.split()[0].upper().startswith(("TTL", "TOTAL")):
            ctn = F(l, ctn_m, 1, num(ctn_m[1])) if ctn_m else (F(l, m, 2, num(m[2])) if m[2] else None)
            d.f.update({f"pl_total_{k}": v for k, v in nums.items()}, pl_total_ctn=ctn)
            continue
        rng = re.search(r"CARTON\s*(\d+)\s*-\s*(\d+)", l.text)
        ctns = (int(rng[2]) - int(rng[1]) + 1) if rng else (num(m[2]) if m[2] else None)
        ctn_f = F(l, rng, 0, ctns) if rng else (F(l, m, 2, ctns) if m[2] else None)
        desc = None
        for pl_line in pl[max(0, i - 4):i][::-1]:
            dm = re.search(r"\bBRAND\s+(.+?)\s*$", pl_line.text)
            if dm:
                desc = F(pl_line, dm, 1); break
        d.pl_items.append(dict(model=_model_near(pl, i, backward=True), ctn=ctns, ctn_f=ctn_f, desc=desc,
                               rng=(int(rng[1]), int(rng[2])) if rng else None, **nums))


def _extract_sc(d: Doc):
    L = d.lines
    d.f["sc_no"] = _first(L, r"No\.\s*:\s*(.+?)(?:\s{2,}|$)")
    if d.f["sc_no"]:
        d.f["pos"] = Field(sorted(set(re.findall(PO_RE, d.f["sc_no"].raw))), "", L[0], 0, 0)
        ln = d.f["sc_no"].line
        dm = re.search(r"\s{2,}(\S.*\d{4})\s*$", ln.text)
        d.f["sc_date"] = F(ln, dm, 1, parse_date(dm[1])) if dm else None
    d.lists["fob"] = _fob_all(L)
    d.f["shipment_by"] = _first(L, r"SHIPMENT\s+By\s+(\S+)", conv=parse_date)
    d.f["payment"] = _first(L, r"PAYMENT\s+(By .+?)\s+for full", flags=re.I)
    rx = rf"^(\d+)\s{{2,}}(\S+)\s{{2,}}([\d,]+)\s{{2,}}(SETS?|PCS)\s{{2,}}([\d,.]+)\s{{2,}}([\d,]+\.\d{{2}})\s*$"
    for _, l, m in _search(L, rx, 0):
        d.items.append(dict(no=F(l, m, 1, int(m[1])), model=m[2], qty=F(l, m, 3, num(m[3])),
                            price=F(l, m, 5, num(m[5])), amount=F(l, m, 6, num(m[6]))))
    d.f["total_amount"] = _first(L, r"^TOTAL\s*:.*?([\d,]+\.\d{2})\s*$", conv=num)
    d.f["total_qty"] = _first(L, r"^TOTAL\s*:\s*([\d,]+)", conv=num)
    d.f["amount_words"] = _first(L, r"^Say\s*:\s*(.+)$")
    docs, on = [], False
    for l in L:
        if re.search(r"DOCUMENTS REQUIRED", l.text, re.I):
            on = True; continue
        if on and re.match(r"\s*8\.", l.text):
            break
        if on:
            docs.append(l.text)
    d.f["docs_required"] = Field(" | ".join(docs), "", L[0], 0, 0)


def _extract_bl(d: Doc):
    L = d.lines
    d.f["bl_no"] = _first(L[:12], r"\b([A-Z]{4}[A-Z0-9]*\d{6,})\b", flags=0)
    v = _after(L, r"\[ Vessel \]\s+\[ Voy", r"^(.+?)\s{2,}(.+?)\s*$")
    if v:
        d.f["vessel"] = Field(_vessel(v.raw), v.raw, v.line, v.start, v.end)
        m = re.search(r"\s{2,}([A-Z ]+?)(?=,|\s*$)", v.line.text)
        d.f["pol"] = F(v.line, m, 1) if m else None
    d.f["pod"] = _after(L, r"\[ Port of Discharge \]", r"^([A-Z ]+?)(?=,|\s{2,})")
    d.lists["pod"] = [d.f["pod"]] if d.f["pod"] else []
    for _, l, m in _search(L, r"(\d+)\s*CONTAINER\(S\).*?\s([\d,]+\.\d{3})\s+([\d,]+\.\d{3})\s*$"):
        d.f["containers"] = F(l, m, 1, int(m[1]))
        d.f["gw"] = F(l, m, 2, num(m[2]))
        d.f["cbm"] = F(l, m, 3, num(m[3]))
        break
    d.f["ctn"] = _first(L, r"\b([\d,]+)\s*CARTONS\b", conv=num)
    d.f["invoice_no"] = _first(L, r"INVOICE NO\.?\s*([A-Z0-9]{8,})")
    d.f["hs"] = _first(L, r"HS CODE:?\s*([\d.]+)")
    _extract_bl_cargo(d)


def _extract_bl_cargo(d: Doc):
    """Containers (number / seal / type), summary like 3X40'HC, total in words, attach-sheet loads,
    shipping-mark models, goods description, final destination, place of delivery."""
    L = d.lines
    rx = r"\b([A-Z]{4}\d{7})\s*/\s*([A-Z0-9]+)\s*/\s*(\d{2}[A-Z]{2})\b"
    d.lists["cntr"] = [Field((m[1], m[3]), m[3], l, m.start(3), m.end(3))      # value = (container no., type)
                       for _, l, _m in _search(L, rx, 0) for m in [re.search(rx, l.text)]]
    d.f["cntr_summary"] = _first(L, r"\b(\d+\s*X\s*\d{2}\s*'?\s*[A-Z]{2}(?:\s*[+&,]\s*\d+\s*X\s*\d{2}\s*'?\s*[A-Z]{2})*)\b", flags=0)
    for _, l, m in _search(L, r"^\s*((?:[A-Z]+[\- ])*[A-Z]+)\s*\((\d+)\)\s*CONTAINER\(S\)\s*ONLY", 0):
        d.f["cntr_words"] = Field(m[1], l.text[m.start(1):m.end(2) + 1], l, m.start(1), m.end(2) + 1)
        d.f["cntr_words_n"] = F(l, m, 2, int(m[2]))
        break
    d.lists["cntr_load"] = [Field((m[1], num(m[2]), num(m[3]), num(m[5])), m[4], l, m.start(4), m.end(4))
                            for _, l, m in _search(L, r"([A-Z]{4}\d{7})\s*//\s*\S+\s*//\s*([\d,]+)\s*CARTONS?\s*//"
                                                      r"\s*([\d,.]+)\s*KGS\s*//\s*(([\d,.]+)\s*CBM)", 0)]
    marks, inside = [], False
    for l in L:
        if re.search(r"SHIPPING MARK", l.text):
            inside = True
            continue
        if inside and re.search(r"FINAL DESTINATION|AS PER ATTACHED|FREIGHT|\[ Total number", l.text):
            break
        if inside:
            m = re.match(r"\s*(" + MODEL_RE[2:] + r")", l.text)
            if m:
                marks.append(F(l, m, 1))
    d.lists["marks_models"] = marks
    g = _first(L, r'"?TOSHIBA"?\s*BRAND\s+([A-Z][A-Z ]*?[A-Z])\s*(?:\s{2,}|$)')
    if g:                                       # a word split over two lines ("HOT PO" + "T"): read it whole
        nxt = L[L.index(g.line) + 1] if L.index(g.line) + 1 < len(L) else None
        if nxt and re.fullmatch(r"\s*[A-Z]{1,3}\s*", nxt.text) and g.end == len(g.line.text.rstrip()):
            g = Field(g.value + nxt.text.strip(), g.raw, g.line, g.start, g.end)
    d.f["goods"] = g
    for _, l, m in _search(L, r"[\d,]+\s*CARTONS?\s*\(\s*([\d,]+)\s*([A-Z]+)\s*\)", 0):
        d.f["bl_qty"] = F(l, m, 1, num(m[1]))
        d.f["bl_unit"] = F(l, m, 2)
        break
    d.f["final_dest"] = _first(L, r"FINAL DESTINATION\s*:\s*([A-Z][A-Z .]*?)\s*(?:,|$)", flags=0)
    d.f["delivery"] = _after(L, r"\[ Place of Delivery \]", r"\s{2,}([A-Z][A-Z ]*?)(?=,|\s{2,}|$)")


def _extract_co(d: Doc):
    L = d.lines
    d.f["departure"] = _after(L, r"Departure date", r"^(\d{1,2}/\d{1,2}/\d{4})", conv=parse_date)
    d.f["vessel"] = _after(L, r"Vessel.s name", r"^(.+?)(?:\s{2,}|$)", conv=_vessel)
    d.f["pod"] = _after(L, r"^Port of Discharge", r"^([A-Z ]+?)(?=,|\s{2,}|$)")
    d.lists["pod"] = [f for _, l, m in _search(L, r"^Port of Discharge") for f in
                      [_after(L[L.index(l):], r"^Port of Discharge", r"^([A-Z ]+?)(?=,|\s{2,}|$)")] if f]
    rx = r"^(\d+)\s{2,}.*?HS\. CODE\. ([\d.]+).*?\s([\d,]+) (SET|PIECE|PCS)S?\s{2,}([A-Z0-9]+)"
    hits = list(_search(L, rx, 0))
    for n, (i, l, m) in enumerate(hits):
        date_f = None
        for nl in L[i + 1:i + 4]:
            dm = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s*$", nl.text)
            if dm:
                date_f = F(nl, dm, 1, parse_date(dm[1])); break
        end = hits[n + 1][0] if n + 1 < len(hits) else len(L)
        block = [x for x in L[i:end] if x.page == l.page]
        stop = next((k for k, x in enumerate(block) if k and re.match(r"\s*TOTAL\s*:", x.text)), len(block))
        d.items.append(dict(no=int(m[1]), hs=m[2], hs_f=F(l, m, 2, m[2]), qty=F(l, m, 3, num(m[3])), inv_ref=m[5], inv_date=date_f,
                            **_co_item_details(block[:stop])))
    for _, l, m in _search(L, r"TOTAL\s*:\s*((?:[A-Z]+[\- ])*[A-Z]+)\s*\(([\d,]+)\)\s*CARTON"):
        d.f["total_ctn"] = F(l, m, 2, num(m[2]))
        tw = m[1].split()
        while tw and tw[0].split("-")[0] not in NUMBER_WORDS:
            tw.pop(0)
        d.f["total_ctn_words"] = Field(" ".join(tw), " ".join(tw), l, m.end(1) - len(" ".join(tw)), m.end(1)) if tw else None
        break
    joined = " ".join(l.text for l in L)
    m = re.search(r"\(([\d,.]+)\)\s*USD", joined)
    d.f["total_value"] = Field(num(m[1]), m[1], L[0], 0, 0) if m else None
    m = re.search(r"TOTAL : [A-Z\- ]+\(([\d,]+)\) (?:SET|PIECE|PCS)", joined)
    d.f["total_qty"] = Field(num(m[1]), m[1], L[0], 0, 0) if m else None


NUMBER_WORDS = set("ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE THIRTEEN FOURTEEN FIFTEEN "
                   "SIXTEEN SEVENTEEN EIGHTEEN NINETEEN TWENTY THIRTY FORTY FIFTY SIXTY SEVENTY EIGHTY NINETY "
                   "HUNDRED THOUSAND MILLION".split())
PKG_RE = r"((?:[A-Z]+[\- ])*[A-Z]+)\s*\(([\d,]+)\)\s*(?:CARTON|CASE|PALLET|PACKAGE|BOX)"


def _co_item_details(block: list) -> dict:
    """Box 7 of one Form D item: packages (words + figures), sets per carton, model, goods name."""
    out = dict(pkg_words=None, pkg_fig=None, per_ctn=None, model=None, goods=None)
    if not block:
        return out
    head = block[0]
    hs = next((s for s in head.spans if "HS. CODE" in s.text), None)
    if hs is None:
        return out
    x0 = hs.bbox[0] - 3
    x1 = min((s.bbox[0] for s in head.spans if s.bbox[0] > hs.bbox[2] + 3), default=1e9) - 3
    col = " ".join(s.text.strip() for x in block for s in x.spans if x0 <= s.bbox[0] < x1)
    col = re.sub(r"\s+", " ", col)
    m = re.search(PKG_RE, col)
    if m:
        toks = m[1].split()
        while toks and toks[0].split("-")[0] not in NUMBER_WORDS:   # drop 'BRAND WASHING MACHINE' etc.
            toks.pop(0)
        out["pkg_words"] = " ".join(toks) or None
        fig_rx = r"\((" + re.escape(m[2]) + r")\)\s*(?:CARTON|CASE|PALLET|PACKAGE|BOX)"
        for x in block:
            fm = re.search(fig_rx, x.text)
            if fm:
                out["pkg_fig"] = F(x, fm, 1, num(fm[1])); break
    m = re.search(r"1\s*CARTON\s*=\s*(\d+)\s*(?:SET|PCS|PIECE)", col, re.I)
    out["per_ctn"] = int(m[1]) if m else None
    m = re.search(r"MODEL\s*:\s*(" + MODEL_RE[2:] + ")", col)
    out["model"] = m[1] if m else None
    m = re.search(r"\bBRAND\s+(.+?)\s*(?:\(\s*1\s*CARTON|MODEL\s*:|$)", col)
    if m:
        goods = m[1].strip()
        pk = re.search(r"\s(?:(?:" + "|".join(sorted(NUMBER_WORDS)) + r")[\- ]?)+\s*\([\d,]+\)\s*(?:CARTON|CASE|PALLET|PACKAGE|BOX)",
                       " " + goods)
        if pk:                                # the package count of box 7 follows the name in the column text
            goods = goods[:max(pk.start() - 1, 0)].strip() or goods
        loc = None
        for x in block:                       # box the line holding the end of the goods name
            tail = goods.split()[-1]
            k = x.text.find(goods) if goods in x.text else x.text.find(tail) if re.search(rf"\b{re.escape(tail)}\b", x.text) else -1
            if k >= 0:
                ln = len(goods) if goods in x.text else len(tail)
                loc = Field(goods, x.text[k:k + ln], x, k, k + ln)
        out["goods"] = loc or Field(goods, goods, head, 0, 0)
        # full description with the brand: '... CARTON(S) OF "ACME" BRAND ELECTRIC KETTLE' (any line wrapping)
        b = re.search(r'("?[A-Z][A-Z0-9&.\-]*"?)\s+BRAND\s+' + re.escape(goods), col)
        full = f"{b[1]} BRAND {goods}" if b else goods
        out["goods_full"] = Field(full, out["goods"].raw, out["goods"].line, out["goods"].start, out["goods"].end)
    return out


EXTRACTORS = dict(CI=_extract_ci, SC=_extract_sc, BL=_extract_bl, CO=_extract_co)


def load(path: Path, kind: str | None = None) -> Doc | None:
    """Read and extract one PDF. kind: type chosen by the user (overrides the automatic classification)."""
    pdf = pymupdf.open(path)
    lines = doc_lines(pdf)
    full = "\n".join(l.text for l in lines)
    kind = kind if kind in EXTRACTORS else classify(full)
    if not kind:
        return None
    raw_all = "\n".join(p.get_text() for p in pdf)   # includes rotated text, e.g. a diagonal DRAFT watermark
    is_draft = bool(re.search(r"\bDRAFT\b", full + "\n" + raw_all, re.I) or "draft" in path.name.lower())
    d = Doc(path, kind, lines, pdf[0].rect.width, is_draft)
    EXTRACTORS[kind](d)
    if kind == "CO":                                # box 6 marks: model on one line, colour code "(BK)" on the next
        d.lists["marks_models"] = [Field(a + b, a, Line(pno, 0.0), 0, 0) for pno, pg in enumerate(pdf)
                                   for a, b in re.findall(r"(?m)^([A-Z][A-Z0-9]*-[A-Z0-9\-]+)\s*\n\s*(\([A-Z0-9]+\)[A-Z]*)\s*$",
                                                          pg.get_text())]
    d.lists["unparsed"] = _unparsed_rows(d)
    from .extract_net import EXTRA                   # extra fields for the cross-document / self-check rules
    EXTRA[kind](d)
    return d


ROW_RE = re.compile(r"[\d,]+\s*(?:SET\(S\)|SETS?|PCS|PIECES?)\b.*\d\.\d{2,3}\s*$", re.I)


def _unparsed_rows(d: Doc) -> list:
    """Lines that look like goods rows (qty + unit … money/weight) but no item rule consumed them."""
    if d.kind not in ("CI", "SC"):
        return []
    used = {id(it["qty"].line) for it in d.items + d.pl_items}
    return [l for l in d.lines if ROW_RE.search(l.text) and id(l) not in used
            and not re.match(r"\s*(TTL|TOTAL)\b", l.text, re.I)]
