"""Classify logistics PDFs and extract fields (each field remembers where it sits in the PDF)."""
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .grammar import CTN_UNIT, DATE_DMY, DEC, DEC2, DOC_ID, NUM, QTY_UNIT, SAILING
from .pdftext import Line, doc_lines
from .util import num, parse_date

# a hyphenated suffix after the colour code belongs to the model: EF-Z30-PQ(06)-MG (not EF-Z30-PQ(06))
MODEL_TAIL = r"(?:-[A-Z0-9]+)*"
MARK_TAIL = r"(?:-[A-Za-z0-9]+)*"
MODEL_RE = r"\b[A-Z][A-Z0-9]*-[A-Z0-9\-]+\([A-Z0-9]+\)[A-Z]*" + MODEL_TAIL   # AB-X10(W1)VN, CD-Y20PE(BM)VN, EF-Z30(06)-MG
# A model in the shipping marks: lowercase letters accepted after the first letter, so a typo such as
# "AB-xX10(W1)VN" is read and reported as a wrong model instead of being skipped (no model read = nothing checked).
MARK_RE = r"\b[A-Z][A-Za-z0-9]*-[A-Za-z0-9\-]+\([A-Za-z0-9]+\)[A-Za-z]*" + MARK_TAIL
MARK_HEAD = r"[A-Z][A-Za-z0-9]*-[A-Za-z0-9\-]+"               # the part before the colour code
PO_RE = r"PR\d{12}"


@dataclass
class Field:
    value: object
    raw: str
    line: Line
    start: int
    end: int
    status: str = "READ"          # engine.checks.FieldStatus: READ | UNREADABLE (reader) | SUSPECT (engine/plausibility.py)
    why: str = ""                 # SUSPECT: the plausibility rule (S1 / S3)

    @property
    def page(self):
        return self.line.page


_RAW = object()


def F(line: Line, m: re.Match, group=1, value=_RAW) -> Field:
    """The matched text as a Field. value: what it means (a number, a date …); without it the text itself.
    value=None means "printed but not understood" (e.g. the date '21-NOV-2O26'): the field stays empty and the
    VALUE_UNREADABLE rule reports it, instead of a text standing in for a date."""
    raw = m.group(group)
    if value is None:                                       # printed but not understood: the reader says so
        return Field(None, raw, line, m.start(group), m.end(group), "UNREADABLE")
    return Field(raw if value is _RAW else value, raw, line, m.start(group), m.end(group))


@dataclass
class CargoBlock:
    """One cargo block of a B/L description column: goods / HS heading / cartons + quantity / invoice no.
    A B/L that carries several invoices prints one block per invoice (LDV 2.5, P3). Canonical: rules use this."""
    ctn: Field
    qty: Field | None = None
    unit: Field | None = None
    goods: Field | None = None
    hs: Field | None = None
    invoice: Field | None = None


@dataclass
class Package:
    """A carton (or carton range) of a packing list and the lines packed in it (LDV 2.5, P4). G.W. and CBM belong to
    the package when it holds several lines that print them once; a line without them inherits nothing (not zero)."""
    rng: tuple | None
    ctn: int | None
    gw: Field | None
    cbm: Field | None
    lines: list                   # indexes into Doc.pl_items


@dataclass
class ItemId:
    """What identifies a goods line (LDV 2.5, P4): a finished-goods model or a part number, plus the goods type
    from the description (config "goods_categories")."""
    value: str | None
    kind: str                     # model | part_no | none
    category: str                 # finished | part | label | packaging | other
    field: Field | None = None


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
    cargo_blocks: list = field(default_factory=list)   # B/L: [CargoBlock]
    packages: list = field(default_factory=list)       # packing list: [Package] when lines share a carton
    suspect_lines: int = 0                             # P5 S2: goods rows not read -> line sums are SUSPECT
    item_ids: list = field(default_factory=list)       # [ItemId] parallel to items
    pl_item_ids: list = field(default_factory=list)    # [ItemId] parallel to pl_items

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
        return F(l, m, group, conv(m.group(group)) if conv else _RAW)
    return None


def _after(lines, label_pattern, value_pattern, group=1, conv=None):
    """Value on the first line after a label line."""
    for i, l, _ in _search(lines, label_pattern):
        for nl in lines[i + 1:i + 3]:
            m = re.search(value_pattern, nl.text, re.I)
            if m:
                return F(nl, m, group, conv(m.group(group)) if conv else _RAW)
    return None


def column_models(lines: list) -> list:
    """Models listed one per line in a shipping-marks column, as Fields. A model may be written whole
    ('CD-Y20PE(BM)VN') or split over two lines, before the colour code ('CD-Y20PE' / '(BM)VN') or after it
    ('EF-Z30(BK)' / 'VN')."""
    out, skip = [], False
    for i, l in enumerate(lines):
        if skip:
            skip = False
            continue
        t = l.text
        m = re.match(r"\s*(" + MARK_RE[2:] + r")\s*$", t)
        nxt = lines[i + 1].text if i + 1 < len(lines) else ""
        if m:
            tail = re.fullmatch(r"\s*([A-Z]{1,3})\s*", nxt) if m[1].endswith(")") else None
            out.append(Field(m[1] + (tail[1] if tail else ""), m[1], l, m.start(1), m.end(1)))
            skip = bool(tail)
            continue
        m = re.match(r"\s*(" + MARK_HEAD + r")\s*$", t)
        tail = re.fullmatch(r"\s*(\([A-Za-z0-9]+\)[A-Za-z]*" + MARK_TAIL + r")\s*", nxt)
        if m and tail:
            out.append(Field(m[1] + tail[1], m[1], l, m.start(1), m.end(1)))
            skip = True
    return out


def _model_near(lines, i, span=3, backward=False):
    after, before = lines[i + 1:i + 1 + span], lines[max(0, i - span):i][::-1]
    for l in [lines[i]] + (before + after if backward else after + before):
        m = re.search(MODEL_RE, l.text)
        if m:
            return m.group(0)
    return None


def _fob_all(lines):
    out = []
    for _, l, m in _search(lines, r"\bFOB ([A-Z][A-Z ]*?[A-Z])(?=\s{2,}|\s*$| IN USD|\s*,\s*[A-Z])", 0):
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
    d.f["invoice_no"] = _first(L, rf"INVOICE NO\.?\s*:?\s*({DOC_ID})")
    d.f["invoice_date"] = (_first(L, rf"\bDATE\s*:\s*({DATE_DMY})", conv=parse_date)
                           or _first(L, r"Invoice Date:\s*(\S+)", conv=parse_date)
                           # the date printed right after the invoice number, without a label
                           or _first(L, rf"INVOICE NO\.?\s*:?\s*{DOC_ID}\s{{2,}}({DATE_DMY})\s*$", conv=parse_date))
    d.f["vessel"] = _first(L, r"SHIPPED BY\s*:\s*(.+?)(?:\s{2,}|$)", conv=_vessel)
    d.f["pol"] = (_first(L, r"Port of Loading\s*:\s*([A-Za-z ]+)") or _first(L, r"FROM\s*:\s*([A-Z ]+?)(?:\s{2,}|$)"))
    d.f["pod"] = (_first(L, r"Port of Discharge\s*:\s*([A-Z ]+?)(?=,|\s{2,}|$)")
                  or _first(L, r"\bTO\s*:\s*([A-Z ]+?)(?:\s{2,}|$)"))
    d.lists["pod"] = [F(l, m, 1) for _, l, m in _search(L, r"Port of Discharge\s*:\s*([A-Z ]+?)(?=,|\s{2,}|$)")]
    d.f["sailing"] = (_first(L, rf"{SAILING}\s*:\s*(\d.+?)(?:\s{{2,}}|$)", conv=parse_date)
                      or _after(L, SAILING, rf"^\s*({DATE_DMY})", conv=parse_date))
    d.f["containers"] = _first(L, r"TOTAL CONTAINER\s*:\s*(\d+)\s*x", conv=int)
    for _, l, m in _search(L, r"TOTAL CONTAINER\s*:\s*((?:\d+\s*[xX]\s*\d{2}\s*'?\s*[A-Z]{2}[\s+,&]*)+)"):
        d.lists["cntr_types"] = [F(l, m, 1)]
        n = sum(int(k) for k in re.findall(r"(\d+)\s*[xX]\s*\d{2}", m.group(1)))   # 1x40HQ,1x20GP = 2
        d.f["containers"] = F(l, m, 1, value=n)
        d.f["containers"].raw = d.f["containers"].raw.strip(" ,&+")
        break
    d.f["goods"] = _first(L, r'"?TOSHIBA"?\s*BRAND\s+([A-Z][A-Z ]*?[A-Z])\s*(?:\s{2,}|$)')
    pos = set()
    for _, l, m in _search(L, PO_RE, 0):
        pos.update(re.findall(PO_RE, l.text))
    d.f["pos"] = Field(sorted(pos), "", L[0], 0, 0)
    d.lists["fob"] = _fob_all(L)

    item_rx = rf"({NUM})\s*{QTY_UNIT}\s{{2,}}({DEC2})\s{{2,}}({DEC2})\s*$"
    hits = list(_search(inv, item_rx))
    for n, (i, l, m) in enumerate(hits):
        po = re.search(PO_RE, l.text)
        desc = None                                 # '"ACME" BRAND RICE COOKER 1.8L(AB)SERIES' under the line
        for nl in inv[i + 1:min(i + 4, hits[n + 1][0] if n + 1 < len(hits) else len(inv))]:
            dm = re.search(r"\bBRAND\s+(.+?)\s*$", nl.text)
            if dm:
                desc = F(nl, dm, 1); break
        d.items.append(dict(model=_model_near(inv, i), qty=F(l, m, 1, num(m[1])), price=F(l, m, 2, num(m[2])),
                            amount=F(l, m, 3, num(m[3])), po=po.group(0) if po else None, desc=desc))
    for _, l, m in _search(inv, rf"^(?:TTL|TOTAL)\b.*?(?:USD\s*)?({DEC2})\s*$"):
        d.f["total_amount"] = F(l, m, 1, num(m[1]))
    for _, l, m in _search(inv, rf"^(?:TTL|TOTAL)\b.*?({NUM})\s*{QTY_UNIT}"):     # '357.00 PCS': all of it
        d.f["total_qty"] = F(l, m, 1, num(m[1]))
    words = [l.text for l in inv if re.search(r"\bSAY\b", l.text, re.I)]
    if words:
        i = inv.index(next(l for l in inv if l.text in words))
        d.f["amount_words"] = Field(" ".join(x.text for x in inv[i:i + 2]), "", inv[i], 0, 0)

    pl_rx = rf"({NUM})\s*{QTY_UNIT}(?:\s+({NUM})\s*CTNS)?\s+({DEC})\s+({DEC})\s+({DEC})\s*$"
    for i, l, m in _search(pl, pl_rx):
        nums = dict(qty=F(l, m, 1, num(m[1])), nw=F(l, m, 3, num(m[3])), gw=F(l, m, 4, num(m[4])),
                    cbm=F(l, m, 5, num(m[5])))
        ctn_m = re.search(rf"({NUM})\s*CARTON\s*\(\s*S\s*\)", l.text)
        if re.match(r"\s*(TTL|TOTAL)", l.text, re.I) or l.text.split()[0].upper().startswith(("TTL", "TOTAL")):
            ctn = F(l, ctn_m, 1, num(ctn_m[1])) if ctn_m else (F(l, m, 2, num(m[2])) if m[2] else None)
            d.f.update({f"pl_total_{k}": v for k, v in nums.items()}, pl_total_ctn=ctn)
            continue
        rng = re.search(r"CARTON\s*(?:/\s*)?(?:NO\.?\s*)?(\d+)\s*-\s*(\d+)", l.text)
        ctns = (int(rng[2]) - int(rng[1]) + 1) if rng else (num(m[2]) if m[2] else None)
        ctn_f = F(l, rng, 0, ctns) if rng else (F(l, m, 2, ctns) if m[2] else None)
        desc = None
        for pl_line in pl[max(0, i - 4):i][::-1]:
            dm = re.search(r"\bBRAND\s+(.+?)\s*$", pl_line.text)
            if dm:
                desc = F(pl_line, dm, 1); break
        d.pl_items.append(dict(model=_model_near(pl, i, backward=True), ctn=ctns, ctn_f=ctn_f, desc=desc,
                               rng=(int(rng[1]), int(rng[2])) if rng else None, **nums))
    _shared_cartons(d, pl, pl_rx)
    if not d.f.get("goods"):                       # no 'BRAND' line: the quoted goods description of the invoice
        src = inv or L                             # the packing-list part read on its own has no invoice part
        first = next((it["qty"].line for it in d.items + d.pl_items if it["qty"].line in src), None)
        head = src[:src.index(first)] if first is not None else src
        d.f["goods"] = _first(head, r'^\s*"([A-Z][^"]{5,})"', flags=0)
    d.item_ids = [item_id(L, it) for it in d.items]
    d.pl_item_ids = [item_id(L, it) for it in d.pl_items]


_PARTIAL = rf"({NUM})\s*{QTY_UNIT}\s+({NUM})\s*$"          # 'CARTON LABEL   6 PCS   0.006': quantity + N.W. only
_PART_NO = re.compile(r"^\s*([A-Z0-9]{6,}@[A-Z]{1,4}|\d{10,}[A-Z0-9]*)\s*$")


def _shared_cartons(d: Doc, pl: list, pl_rx: str):
    """Lines packed in the carton of the full row above them: they print quantity and N.W. only, the carton's G.W.
    and CBM are printed once on the full row. They become packing-list lines of a Package that holds G.W. / CBM;
    a line never gets a G.W. or CBM of its own (missing is not zero)."""
    heads = {id(it["qty"].line): k for k, it in enumerate(d.pl_items)}
    extra, cur = {}, None
    for i, l in enumerate(pl):
        if id(l) in heads:
            cur = heads[id(l)]
            continue
        # a TTL row does not close the carton: a layout may print it on every page and go on with the same carton
        if cur is None or re.search(pl_rx, l.text) or re.match(r"\s*(TTL|TOTAL)\b", l.text, re.I):
            continue
        m = re.search(_PARTIAL, l.text, re.I)
        if m:
            extra.setdefault(cur, []).append(dict(model=_model_near(pl, i), ctn=None, ctn_f=None, desc=None, rng=None,
                                                  qty=F(l, m, 1, num(m[1])), nw=F(l, m, 2, num(m[2])), gw=None,
                                                  cbm=None))
    if not extra:
        return
    items = []
    for k, it in enumerate(d.pl_items):
        if k in extra:
            pk = Package(it["rng"], it["ctn"], it["gw"], it["cbm"], [])
            d.packages.append(pk)
            it = dict(it, gw=None, cbm=None, package=len(d.packages) - 1)
            pk.lines.append(len(items))
            items.append(it)
            for e in extra[k]:
                pk.lines.append(len(items))
                items.append(dict(e, package=len(d.packages) - 1))
        else:
            items.append(it)
    d.pl_items = items


def item_id(L: list, it: dict) -> ItemId:
    """A goods line's identity: its model, or else the part number printed on the line below (e.g. '…@AB'), and the
    goods type from its description (config "goods_categories")."""
    from .rules import CONFIG
    line = it["qty"].line
    desc = re.sub(r"^\s*\d{1,3}\s{2,}", "", line.text[:it["qty"].start]).strip()
    cats = CONFIG.get("goods_categories", {})
    cat = next((c for c, words in cats.items() if any(re.search(rf"\b{re.escape(w)}\b", desc, re.I) for w in words)),
               None)
    model = it.get("model")
    if model:
        return ItemId(model if isinstance(model, str) else getattr(model, "value", None), "model", cat or "finished")
    k = L.index(line) if line in L else -1
    for nl in L[k + 1:k + 3] if k >= 0 else []:
        m = _PART_NO.match(nl.text)
        if m:
            return ItemId(m[1], "part_no", cat or "part", F(nl, m, 1))
    return ItemId(None, "none", cat or "other")

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
    rx = rf"^(\d+)\s{{2,}}(\S+)\s{{2,}}({NUM})\s{{2,}}(SETS?|PCS)\s{{2,}}({NUM})\s{{2,}}({DEC2})\s*$"
    for _, l, m in _search(L, rx, 0):
        d.items.append(dict(no=F(l, m, 1, int(m[1])), model=m[2], qty=F(l, m, 3, num(m[3])),
                            price=F(l, m, 5, num(m[5])), amount=F(l, m, 6, num(m[6]))))
    d.f["total_amount"] = _first(L, rf"^TOTAL\s*:.*?({DEC2})\s*$", conv=num)
    d.f["total_qty"] = _first(L, rf"^TOTAL\s*:\s*({NUM})", conv=num)
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
    for _, l, m in _search(L, rf"(\d+)\s*CONTAINER\(S\).*?\s({DEC})\s+({DEC})\s*$"):
        d.f["containers"] = F(l, m, 1, int(m[1]))
        d.f["gw"] = F(l, m, 2, num(m[2]))
        d.f["cbm"] = F(l, m, 3, num(m[3]))
        break
    # total cartons of the said-to-contain box: not '1,250 CARTONS (1,250 SETS)' in the goods description and not
    # an attach-sheet row ('... // 950 CARTONS // ...'), whichever comes first in the layout
    d.f["ctn"] = (_first([l for l in L if "//" not in l.text], rf"({NUM})\s*CARTONS\b(?!\s*\()", conv=num)
                  or _first(L, rf"({NUM})\s*CARTONS\b", conv=num))
    d.f["invoice_no"] = _first(L, rf"INVOICE NO\.?\s*:?\s*({DOC_ID})")
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
    load_rx = (rf"([A-Z]{{4}}\d{{7}})\s*//\s*\S+\s*//\s*(({NUM})\s*CARTONS?)\s*//"
               rf"\s*(({NUM})\s*KGS)\s*//\s*(({NUM})\s*CBM)")
    d.lists["cntr_load"], d.lists["cntr_load_parts"] = [], []
    for _, l, m in _search(L, load_rx, 0):         # one attach-sheet row: container // seal // cartons // KGS // CBM
        d.lists["cntr_load"].append(Field((m[1], num(m[3]), num(m[5]), num(m[7])), m[6], l, m.start(6), m.end(6)))
        d.lists["cntr_load_parts"].append(dict(no=m[1], ctn=F(l, m, 2, num(m[3])), gw=F(l, m, 4, num(m[5])),
                                               cbm=F(l, m, 6, num(m[7]))))   # each figure boxed on its own
    marks, inside = [], False
    for l in L:
        if re.search(r"SHIPPING MARK", l.text):
            inside = True
            continue
        if inside and re.search(r"FINAL DESTINATION|AS PER ATTACHED|FREIGHT|\[ Total number", l.text):
            break
        if inside:
            m = re.match(r"\s*(" + MARK_RE[2:] + r")", l.text)
            if m:
                marks.append(F(l, m, 1))
    d.lists["marks_models"] = marks
    g = _first(L, r'"?TOSHIBA"?\s*BRAND\s+([A-Z][A-Z ]*?[A-Z])\s*(?:\s{2,}|$)')
    if g:                                       # a word split over two lines ("HOT PO" + "T"): read it whole
        nxt = L[L.index(g.line) + 1] if L.index(g.line) + 1 < len(L) else None
        if nxt and re.fullmatch(r"\s*[A-Z]{1,3}\s*", nxt.text) and g.end == len(g.line.text.rstrip()):
            g = Field(g.value + nxt.text.strip(), g.raw, g.line, g.start, g.end)
    d.f["goods"] = g
    for _, l, m in _search(L, rf"({NUM})\s*CARTONS?\s*\(\s*({NUM})\s*([A-Z]+)\s*\)", 0):
        d.f["bl_qty"] = F(l, m, 2, num(m[2]))
        d.f["bl_unit"] = F(l, m, 3)
        d.f["bl_qty_ctn"] = F(l, m, 1, num(m[1]))             # '1,250 CARTONS (1,250 SETS)': the cartons too
        d.f["bl_qty_phrase"] = F(l, m, 0)
        break
    # the label in capitals, the value as written ('Hcm, VIETNAM' is Ho Chi Minh City, not "not read")
    d.f["final_dest"] = _first(L, r"FINAL DESTINATION\s*:\s*([A-Za-z][A-Za-z .]*?)\s*(?:,|$)", flags=0)
    d.f["delivery"] = _after(L, r"\[ Place of Delivery \]", r"\s{2,}([A-Z][A-Z ]*?)(?=,|\s{2,}|$)")


def _extract_co(d: Doc):
    L = d.lines
    d.f["departure"] = _after(L, r"Departure date", rf"^({DATE_DMY})", conv=parse_date)
    d.f["vessel"] = _after(L, r"Vessel.s name", r"^(.+?)(?:\s{2,}|$)", conv=_vessel)
    d.f["pod"] = _after(L, r"^Port of Discharge", r"^([A-Z ]+?)(?=,|\s{2,}|$)")
    d.lists["pod"] = [f for _, l, m in _search(L, r"^Port of Discharge") for f in
                      [_after(L[L.index(l):], r"^Port of Discharge", r"^([A-Z ]+?)(?=,|\s{2,}|$)")] if f]
    rx = rf"^(\d+)\s{{2,}}.*?HS\. CODE\. ([\d.]+).*?\s({NUM}) (SET|PIECE|PCS)S?\s{{2,}}([A-Z0-9]+)"
    hits = list(_search(L, rx, 0))
    for n, (i, l, m) in enumerate(hits):
        date_f = None
        for nl in L[i + 1:i + 4]:
            dm = re.search(rf"({DATE_DMY})\s*$", nl.text)
            if dm:
                date_f = F(nl, dm, 1, parse_date(dm[1])); break
        end = hits[n + 1][0] if n + 1 < len(hits) else len(L)
        block = [x for x in L[i:end] if x.page == l.page]
        stop = next((k for k, x in enumerate(block) if k and re.match(r"\s*TOTAL\s*:", x.text)), len(block))
        d.items.append(dict(no=int(m[1]), hs=m[2], hs_f=F(l, m, 2, m[2]), qty=F(l, m, 3, num(m[3])), inv_ref=m[5], inv_date=date_f,
                            **_co_item_details(block[:stop])))
    tot_rx = rf"TOTAL\s*:\s*((?:[A-Z]+[\- ])*[A-Z]+)\s*\(({NUM})\)\s*"
    hits = [(l, m) for _, l, m in _search(L, tot_rx + "CARTON")]
    hits += [(l, m) for i, l, m in _search(L, tot_rx + "$")                  # '... (1,250)' / 'CARTON***' below
             if i + 1 < len(L) and re.match(r"\s*CARTON", L[i + 1].text)]
    for l, m in hits:
        d.f["total_ctn"] = F(l, m, 2, num(m[2]))
        tw = m[1].split()
        while tw and tw[0].split("-")[0] not in NUMBER_WORDS:
            tw.pop(0)
        d.f["total_ctn_words"] = Field(" ".join(tw), " ".join(tw), l, m.end(1) - len(" ".join(tw)), m.end(1)) if tw else None
        break
    # the totals keep the line they are printed on (their box on the page); the joined text is the fallback for a
    # total whose figure is split over lines
    joined = " ".join(l.text for l in L)
    d.f["total_value"] = _first(L, rf"\(({NUM})\)\s*USD", conv=num, flags=0)
    if d.f["total_value"] is None:
        m = re.search(rf"\(({NUM})\)\s*USD", joined)
        d.f["total_value"] = Field(num(m[1]), m[1], L[0], 0, 0) if m else None
    d.f["total_qty"] = _first(L, rf"TOTAL\s*:\s*[A-Z\- ]+\(({NUM})\)\s*(?:SET|PIECE|PCS)", conv=num, flags=0)
    for _, l, m in _search(L, tot_rx + r"(?:SET|PIECE|PCS)", 0):   # the quantity total in words ('TWO HUNDRED …')
        tw = m[1].split()
        while tw and tw[0].split("-")[0] not in NUMBER_WORDS:
            tw.pop(0)
        if tw:
            w = " ".join(tw)
            d.lists["total_qty_words"] = [Field(w, w, l, m.end(1) - len(w), m.end(1))]
        break
    if d.f["total_qty"] is None:
        m = re.search(rf"TOTAL : [A-Z\- ]+\(({NUM})\) (?:SET|PIECE|PCS)", joined)
        d.f["total_qty"] = Field(num(m[1]), m[1], L[0], 0, 0) if m else None


NUMBER_WORDS = set("ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE THIRTEEN FOURTEEN FIFTEEN "
                   "SIXTEEN SEVENTEEN EIGHTEEN NINETEEN TWENTY THIRTY FORTY FIFTY SIXTY SEVENTY EIGHTY NINETY "
                   "HUNDRED THOUSAND MILLION".split())
PKG_RE = rf"((?:[A-Z]+[\- ])*[A-Z]+)\s*\(\s*({NUM})\s*\)\s*(?:CARTON|CASE|PALLET|PACKAGE|BOX)"   # '( 500 )': pieces joined


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
        fig_rx = r"\(\s*(" + re.escape(m[2]) + r")\s*\)\s*(?:CARTON|CASE|PALLET|PACKAGE|BOX)"
        for x in block:
            fm = re.search(fig_rx, x.text)
            if fm:
                out["pkg_fig"] = F(x, fm, 1, num(fm[1])); break
    m = re.search(r"1\s*CARTON\s*=\s*(\d+)\s*(?:SET|PCS|PIECE)", col, re.I)
    out["per_ctn"] = int(m[1]) if m else None
    # 'AB-X10(W1)VN', also when the pieces were joined with a space ('AB-X10 (W1)VN') or a letter is mistyped
    # a model wrapped after a hyphen ('MODEL: EF-Z30-' / 'PQ(06)-MG') is one model
    mcol = re.sub(r"(MODEL\s*:\s*\S*-)\s+(?=[A-Za-z0-9(])", r"\1", col)
    m = re.search(r"MODEL\s*:\s*(" + MARK_HEAD + r")\s*(\([A-Za-z0-9]+\)[A-Za-z]*" + MARK_TAIL + r")", mcol)
    out["model"] = m[1] + m[2] if m else None
    m = re.search(r"\bBRAND\s+(.+?)\s*(?:\(\s*1\s*CARTON|MODEL\s*:|$)", col)
    if m:
        goods = m[1].strip()
        pk = re.search(r"\s(?:(?:" + "|".join(sorted(NUMBER_WORDS)) + r")[\- ]?)+\s*\(" + NUM + r"\)\s*(?:CARTON|CASE|PALLET|PACKAGE|BOX)",
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
                                   for a, b in re.findall(r"(?m)^(" + MARK_HEAD + r")\s*\n\s*(\([A-Za-z0-9]+\)[A-Za-z]*" + MARK_TAIL + r")\s*$",
                                                          pg.get_text())]
    d.lists["unparsed"] = _unparsed_rows(d)
    from .extract_net import EXTRA                   # extra fields for the cross-document / self-check rules
    EXTRA[kind](d)
    from .plausibility import mark                   # P5: readings with a detectable defect are SUSPECT
    mark(d)
    return d


ROW_RE = re.compile(rf"{NUM}\s*(?:SETS?\s*\(\s*S\s*\)|SETS?|PCS|PIECES?)\b.*\d\.\d{{2,3}}\s*$", re.I)


def _unparsed_rows(d: Doc) -> list:
    """Lines that look like goods rows (qty + unit … money/weight) but no item rule consumed them."""
    if d.kind not in ("CI", "SC"):
        return []
    used = {id(it["qty"].line) for it in d.items + d.pl_items}
    return [l for l in d.lines if ROW_RE.search(l.text) and id(l) not in used
            and not re.match(r"\s*(TTL|TOTAL)\b", l.text, re.I)]
