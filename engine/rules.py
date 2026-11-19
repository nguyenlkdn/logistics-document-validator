"""Validation rules (report only). Each finding records where the wrong / reference values sit in the PDFs."""
import difflib
import json
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import master
from .checks import CheckStatus, Group, Run, begin, current_run, has_text
from .extract import Doc, Field
from .util import fmt_like, number_to_words, words_to_number

SEVERITY = ["ERROR", "WARNING", "MINOR", "INFO"]
CONFIG = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text(encoding="utf-8"))


_REFS = re.compile(r"@\w+(?: / @\w+)*")


def _label_refs(v, lang: str):
    """A parameter "@qty" (or several: "@qty / @po") names fields: show their labels in that language."""
    if not (isinstance(v, str) and _REFS.fullmatch(v)):
        return v
    labels = CONFIG["labels"]
    return " / ".join(labels[r[1:]][lang] if r[1:] in labels else r[1:] for r in v.split(" / "))


@dataclass
class Loc:
    doc: Doc
    page: int | None          # None → search whole document for `text`
    clip: tuple | None        # bbox to search in / draw
    text: str | None          # exact text to box (None → box the clip)
    role: str = "wrong"       # wrong (red) | ref (green)


@dataclass
class Finding:
    key: str                  # message key in config.json
    severity: str
    docs: list                # docs[0] = the document holding the value to check
    params: dict = field(default_factory=dict)
    current: str = ""
    suggested: str = ""
    locs: list = field(default_factory=list)
    evidence: list = field(default_factory=list)   # filled by evidence.py
    check: str = field(default="", compare=False, repr=False)   # id of the check that produced it (engine/checks.py)
    suspect: str = field(default="", compare=False, repr=False)  # P5: built on a possibly misread value (S1 / S2 / S3)

    def text(self, lang: str) -> str:
        p = {k: _label_refs(v, lang) for k, v in self.params.items()}
        t = CONFIG["messages"][self.key][lang].format(**p)
        return t[:1].upper() + t[1:]

    def note(self, lang: str) -> str:
        return CONFIG["messages"][self.key].get(f"note_{lang}", "")

    @property
    def doc_names(self):
        return [d.name for d in self.docs]

    @property
    def page(self):
        for l in self.locs:
            if l.role == "wrong" and l.page is not None:
                return l.page + 1
        return None


# ----------------------------------------------------------------------------- location helpers
def at(doc: Doc, f: Field | None, role="wrong") -> list:
    if f is None:
        return []
    spans = f.line.spans_for(f.start, f.end) if f.end > f.start else []
    if spans:
        clip = (min(s.bbox[0] for s in spans), min(s.bbox[1] for s in spans),
                max(s.bbox[2] for s in spans), max(s.bbox[3] for s in spans))
        return [Loc(doc, f.page, clip, f.raw, role)]
    return [Loc(doc, None, None, f.raw, role)] if f.raw else []


@dataclass
class Calc:
    """A total worked out from the item lines (not read from a TTL row). refs = the line fields it adds up."""
    value: float
    raw: str
    refs: list


_at_field = at


def at(doc: Doc, f, role="wrong") -> list:
    if isinstance(f, Calc):
        return [x for r in f.refs for x in _at_field(doc, r, role)]
    return _at_field(doc, f, role)


def _units(ci: Doc) -> list[dict]:
    """The packing list's packed units: a carton (range) holding several lines (Package) counts once, with its own
    G.W. / CBM / cartons; every other line is its own unit (old layouts: one line = one unit, nothing changes)."""
    out, seen = [], set()
    for it in ci.pl_items:
        k = it.get("package")
        if k is None:
            out.append(dict(rng=it.get("rng"), ctn=it.get("ctn"), ctn_f=it.get("ctn_f"), gw=it.get("gw"), cbm=it.get("cbm"),
                            nw=it.get("nw"), label=it.get("model") or ""))
        elif k not in seen:
            seen.add(k)
            pk = ci.packages[k]
            lines = [ci.pl_items[i] for i in pk.lines]
            nws = [x.get("nw") for x in lines]
            nw = Calc(round(sum(f.value for f in nws), 3), "", nws) if all(isinstance(f, Field) for f in nws) else None
            head = lines[0]
            out.append(dict(rng=pk.rng, ctn=pk.ctn, ctn_f=head.get("ctn_f"), gw=pk.gw, cbm=pk.cbm, nw=nw,
                            label=f"CARTON {pk.rng[0]}-{pk.rng[1]}" if pk.rng else ""))
    return out


def _pl_values(ci: Doc, k: str) -> list:
    """What adds up to the packing-list total of k: the lines for qty / nw, the packed units for gw / cbm."""
    if k in ("gw", "cbm") and ci.packages:
        return [u[k] for u in _units(ci)]
    return [it.get(k) for it in ci.pl_items]


def _lines_agree(ci: Doc) -> bool:
    """The packing-list lines tell the whole story: as many lines as the invoice, the same total quantity, and
    carton ranges running 1, 2, 3 … with no gap or overlap. Otherwise a line is missing or misprinted (LINE_COUNT,
    CI_PL_QTY, PL_LINE, PL_RANGE_* report it) and the line sum is not the truth either."""
    pl, inv = ci.pl_items, ci.items
    if not pl or (inv and len(inv) != len(pl)):
        return False
    q = [it.get("qty") for it in pl]
    if any(not isinstance(x, Field) or x.value is None for x in q):
        return False
    if inv and not _close(sum(x.value for x in q), sum(_v(it.get("qty")) or 0 for it in inv)):
        return False
    rngs = [u.get("rng") for u in _units(ci)]
    if any(rngs):
        expect = 1
        for r in rngs:
            if not r or r[0] != expect:
                return False
            expect = r[1] + 1
    return True


def true_total(ci: Doc | None, k: str):
    """The total of an invoice / packing list as its item lines add up, not the printed TTL: a TTL row can be
    wrong (TTL 504 cartons under the one line CARTON 1-500, all other documents 500). The printed TTL is itself
    checked against the lines (TOTAL_QTY, TOTAL_AMOUNT, PL_TOTAL, PL_RANGE_TOTAL); the other documents and the
    other TTL rows are compared with what the lines say.
    k: qty / amount (invoice lines; amount = the printed line amounts, qty x price is LINE_AMOUNT's job),
    pl_qty / ctn / nw / gw / cbm (packing-list lines, only when they agree with the invoice: _lines_agree).
    Lines not all readable or not consistent: the printed total."""
    if not ci:
        return None
    if k in ("qty", "amount"):
        printed = ci.f.get(f"total_{k}") or (ci.f.get("pl_total_qty") if k == "qty" else None)
        rows = ci.items
        vals = refs = [it.get(k) for it in rows]
    else:
        pk = "qty" if k == "pl_qty" else k
        printed = ci.f.get(f"pl_total_{pk}")
        rows = (_units(ci) if (k in ("gw", "cbm", "ctn") and ci.packages) else ci.pl_items) if _lines_agree(ci) else []
        if k in ("nw", "gw") and any(_v(u.get("gw")) is not None and _v(u.get("nw")) is not None
                                     and u["gw"].value < u["nw"].value - 0.0005 for u in _units(ci)):
            rows = []                               # a unit's own weights are wrong (PL_GW_NW): its sum is no truth
        if k == "ctn":
            vals, refs = [it.get("ctn") for it in rows], [it.get("ctn_f") for it in rows]
        else:
            vals = refs = [it.get(pk) for it in rows]
    nums = [v.value if isinstance(v, Field) else v for v in vals]
    if not rows or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in nums):
        return printed
    s = round(sum(nums), 3)
    if printed and _close(printed.value, s, 0.0005):
        return printed                              # the TTL agrees with the lines: point at the TTL
    raw = fmt_like(s, printed.raw) if printed else f"{s:,.3f}".rstrip("0").rstrip(".")
    return Calc(s, raw, [r for r in refs if isinstance(r, Field)])


def at_line(doc: Doc, line, role="wrong") -> list:
    return [Loc(doc, line.page, line.bbox, None, role)]


def _v(f):
    return f.value if isinstance(f, (Field, Calc)) else None


def _close(a, b, tol=0.005):
    return a is not None and b is not None and abs(a - b) <= tol


def _canon_port(name: str):
    n = re.sub(r"\s+", " ", (name or "").upper()).strip()
    for canon, aliases in CONFIG["ports"].items():
        if n == canon or n in aliases:
            return canon
    return None


# ----------------------------------------------------------------------------- rules
def r_line_math(docs, out):
    for d in docs:
        if d.kind not in ("CI", "SC"):
            continue
        k = d.kind.lower()
        ck = begin(f"LINE_MATH.{k}", out, d)
        ck.need_items(d)
        for it in d.items:
            ck.compared()
            exp = round(it["qty"].value * it["price"].value, 2)
            if not _close(exp, it["amount"].value):
                ck.add(Finding("LINE_AMOUNT", "ERROR", [d], dict(model=it["model"]), it["amount"].raw,
                               fmt_like(exp, it["amount"].raw),
                               at(d, it["amount"]) + at(d, it["qty"], "ref") + at(d, it["price"], "ref")))
        ck.end()
        tot = d.f.get("total_amount")
        ck = begin(f"TOTAL_AMOUNT.{k}", out, d)
        ck.need(d, "total_amount", absent_ok=True)
        ck.need_items(d)
        if tot and d.items:
            ck.compared()
            exp = round(sum(it["qty"].value * it["price"].value for it in d.items), 2)
            if not _close(exp, tot.value):
                ck.add(Finding("TOTAL_AMOUNT", "ERROR", [d], {}, tot.raw, fmt_like(exp, tot.raw), at(d, tot)))
        ck.end()
        tq = d.f.get("total_qty")
        ck = begin(f"TOTAL_QTY.{k}", out, d)
        ck.need(d, "total_qty", absent_ok=True)
        ck.need_items(d)
        if tq and d.items:
            ck.compared()
            exp = sum(it["qty"].value for it in d.items)
            if not _close(exp, tq.value):
                ck.add(Finding("TOTAL_QTY", "ERROR", [d], {}, tq.raw, fmt_like(exp, tq.raw), at(d, tq)))
        ck.end()


def r_pl_sums(docs, out):
    for d in docs:
        if d.kind != "CI":
            continue
        if not d.pl_items:
            for cid in ("PL_TOTAL.qty", "PL_TOTAL.nw", "PL_TOTAL.gw", "PL_TOTAL.cbm", "PL_TOTAL.ctn", "CI_PL_QTY"):
                ck = begin(cid, out, d)
                ck.need_items(d, "pl_items")
                ck.end()
            continue
        for k in ("qty", "nw", "gw", "cbm"):
            ck = begin(f"PL_TOTAL.{k}", out, d)
            ck.need_items(d, "pl_items")
            ck.need(d, f"pl_total_{k}", absent_ok=True)
            tot = d.f.get(f"pl_total_{k}")
            vals = _pl_values(d, k)                  # gw / cbm of a shared carton: once, from the carton
            exp = round(sum(f.value for f in vals if isinstance(f, (Field, Calc))), 3)
            for f in vals:
                if not isinstance(f, (Field, Calc)):
                    ck._input(d, f"pl_items[{k}]", "NOT_FOUND")
            if tot:
                ck.compared()
            if tot and not _close(exp, tot.value):
                ck.add(Finding("PL_TOTAL", "ERROR", [d], dict(label=f"@{k}"), tot.raw, fmt_like(exp, tot.raw),
                               at(d, tot)))
            ck.end()
        ck = begin("PL_TOTAL.ctn", out, d)
        ck.need_items(d, "pl_items")
        ctn = d.f.get("pl_total_ctn")
        units = _units(d)
        if any(u.get("rng") for u in units):
            ck.na(evidence="carton_ranges", by="PL_RANGE_TOTAL")
        else:
            ck.need(d, "pl_total_ctn", absent_ok=True)
            for u in units:
                if not u.get("ctn"):
                    ck._input(d, "pl_items[ctn]", "NOT_FOUND")
        if ctn and all(u["ctn"] for u in units) and not any(u.get("rng") for u in units):
            ck.compared()
            exp = sum(u["ctn"] for u in units)
            if not _close(exp, ctn.value):
                ck.add(Finding("PL_TOTAL", "ERROR", [d], dict(label="@ctn"), ctn.raw, fmt_like(exp, ctn.raw),
                               at(d, ctn)))
        ck.end()
        ck = begin("CI_PL_QTY", out, d)
        ck.need_items(d, "pl_items")
        ck.need_items(d)
        if d.items:
            ck.compared()
            ci_q = sum(it["qty"].value for it in d.items)
            pl_q = sum(it["qty"].value for it in d.pl_items)
            if not _close(ci_q, pl_q):
                ck.add(Finding("CI_PL_QTY", "ERROR", [d], {}, f"{pl_q:,.0f}", f"{ci_q:,.0f}",
                               at(d, d.f.get("pl_total_qty")) + at(d, d.f.get("total_qty"), "ref")))
        ck.end()


def r_bl_vs_pl(ci, bl, out):
    if not (ci and bl):
        return
    for k in ("gw", "cbm", "ctn"):
        ck = begin(f"BL_VS_PL.{k}", out)
        b, p = bl.f.get(k), true_total(ci, k)
        ck.need(bl, k)
        ck.need_total_val(ci, k, p)
        if b and p:
            ck.compared()
        if b and p and not _close(b.value, p.value, 0.0005):
            rows = [x["ctn" if k == "ctn" else k] for x in bl.lists.get("cntr_load_parts", [])]
            agree = rows and _close(sum(r.value for r in rows), p.value, 0.0005)   # the B/L attach sheet agrees with the PL
            ck.add(Finding("BL_VS_PL", "ERROR", [bl, ci], dict(label=f"@{k}"), b.raw, fmt_like(p.value, b.raw),
                           at(bl, b) + at(ci, p, "ref") + ([x for r in rows for x in at(bl, r, "ref")] if agree else [])))
        ck.end()
    ck = begin("CONTAINERS", out)
    c1, c2 = bl.f.get("containers"), ci.f.get("containers")
    ck.need(bl, "containers")
    ck.need(ci, "containers", absent_ok=True)
    if c1 and c2:
        ck.compared()
    if c1 and c2 and c1.value != c2.value:
        ck.add(Finding("CONTAINERS", "ERROR", [bl, ci], {}, str(c1.value), str(c2.value),
                       at(bl, c1) + at(ci, c2, "ref")))
    ck.end()
    ck = begin("INVOICE_REF", out)
    b, c = bl.f.get("invoice_no"), ci.f.get("invoice_no")
    ck.need(bl, "invoice_no")
    ck.need(ci, "invoice_no")
    listed = [f.value for f in bl.lists.get("invoice_nos", [])]          # a B/L can name several invoices
    if b and c:
        ck.compared()
    if b and c and b.value != c.value and c.value not in listed:
        ck.add(Finding("INVOICE_REF", "ERROR", [bl, ci], {}, b.raw, c.value, at(bl, b) + at(ci, c, "ref")))
    ck.end()


def r_incoterm(docs, ci, bl, out):
    src = (bl, bl.f.get("pol")) if bl and bl.f.get("pol") else ((ci, ci.f.get("pol")) if ci else (None, None))
    pol = src[1].value.upper().strip() if src[1] else None
    for d in docs:
        ck = begin("INCOTERM_PORT", out, d)
        fobs = d.lists.get("fob", [])
        if not fobs:                               # 'FOB' + a place printed but not read -> NOT_RUN, else not on it
            ck.need_list(d, "fob", trace=r"\bFOB\s+[A-Z]{2,}")
            ck.end()
            continue
        ck.need_list(d, "fob")
        if pol is None:
            ck.need(bl or ci, "pol")
            ck.end()
            continue
        good = [f for f in fobs if pol.startswith(f.value.upper().strip())]
        for f in fobs:
            ck.compared()
            place = f.value.upper().strip()
            if not pol.startswith(place):
                fob_box = lambda fld, role: [Loc(l.doc, l.page, l.clip, "FOB " + fld.raw, role) for l in at(d, fld, role)]
                same = [g for g in good if g.page == f.page]
                ref = fob_box((same or good)[0], "ref") if good else at(src[0], src[1], "ref")
                ck.add(Finding("INCOTERM", "ERROR", [d], dict(place=place, pol=pol), f"FOB {place}",
                               f"FOB {pol}", fob_box(f, "wrong") + ref))
        ck.end()


def r_po_coverage(scs, ci, out):
    if not (ci and scs):
        return
    ck = begin("SC_PO_COVERAGE", out)
    ck.need(ci, "pos", trace=r"(?i)\bP/?O\b|PURCHASE ORDER")    # an empty list is not "all P/O covered"
    for s in scs:
        ck.need(s, "pos")
    inv_pos = set(ci.f["pos"].value)
    sc_pos = set().union(*[set(s.f["pos"].value) for s in scs if s.f.get("pos")])
    if inv_pos and sc_pos:
        ck.compared()
    missing, extra = sorted(inv_pos - sc_pos), sorted(sc_pos - inv_pos)
    sc_raw = ", ".join(s.f["sc_no"].raw for s in scs if s.f.get("sc_no"))
    if missing:
        typo = None
        for s in scs:
            for tok in re.findall(r"[A-Z0-9]{8,}", s.f["sc_no"].raw if s.f.get("sc_no") else ""):
                for po in missing:
                    if tok not in sc_pos and difflib.SequenceMatcher(None, tok, po).ratio() >= 0.85:
                        typo = (tok, po)
        ref = []
        for l in ci.lines:
            if all(p in l.text for p in missing):
                ref = at_line(ci, l, "ref"); break
        wrong = [x for s in scs for x in at(s, s.f.get("sc_no"))]
        if typo:
            ck.add(Finding("SC_PO_TYPO", "ERROR", list(scs) + [ci], dict(sc=typo[0], po=typo[1]),
                           sc_raw, sc_raw.replace(typo[0], typo[1]), wrong + ref))
        else:
            ck.add(Finding("SC_PO_MISSING", "ERROR", list(scs) + [ci], dict(missing=", ".join(missing)),
                           sc_raw, ", ".join(sorted(sc_pos | set(missing))), wrong + ref))
    if extra:
        ck.add(Finding("SC_PO_EXTRA", "WARNING", list(scs), dict(extra=", ".join(extra)), ", ".join(extra), "",
                       [x for s in scs for x in at(s, s.f.get("sc_no"))]))
    ck.end()


def r_sc_vs_ci(scs, ci, out):
    if not (ci and scs):
        return
    ck = begin("SC_VS_CI", out)
    ck.need_items(ci)
    for s in scs:
        ck.need_items(s)
    if ci.items and any(s.items for s in scs):     # two empty lists are not "the same goods"
        ck.compared()
    key = lambda it: (it["model"], it["qty"].value, round(it["price"].value, 2))
    a = Counter(key(it) for it in ci.items)
    b = Counter(key(it) for s in scs for it in s.items)
    if a != b:
        fmt = lambda c: "; ".join(f"{m} {q:,.0f} @ {p}" for m, q, p in sorted(c.elements()))
        locs = [x for s in scs for it in s.items if key(it) in (b - a) for x in at_line(s, it["qty"].line)]
        ck.add(Finding("SC_VS_CI", "ERROR", list(scs) + [ci], {}, fmt(b - a), fmt(a - b), locs))
    ck.end()
    for s in scs:
        ck = begin("SC_NUMBERING", out, s)
        ck.need_items(s)
        nums = [it["no"] for it in s.items]
        if nums:
            ck.compared()
        if [n.value for n in nums] != list(range(1, len(nums) + 1)):
            ck.add(Finding("SC_NUMBERING", "MINOR", [s], {}, ",".join(n.raw for n in nums),
                           ",".join(str(i) for i in range(1, len(nums) + 1)),
                           [x for i, n in enumerate(nums, 1) if n.value != i for x in at(s, n)]))
        ck.end()


def r_dates(scs, ci, co, out):
    sail_f = ci.f.get("sailing") if ci else None
    sail = _v(sail_f)
    ck = begin("DEPARTURE_DATE", out)
    ck.need(co, "departure")
    ck.need(ci, "sailing")
    if co and sail and co.f.get("departure"):
        ck.compared()
    if co and sail and co.f.get("departure") and co.f["departure"].value != sail:
        f = co.f["departure"]
        ck.add(Finding("DEPARTURE_DATE", "ERROR", [co, ci], {}, f.raw, f"{sail:%d/%m/%Y}",
                       at(co, f) + at(ci, sail_f, "ref")))
    ck.end()
    inv_f = ci.f.get("invoice_date") if ci else None
    inv_date = _v(inv_f)
    ck = begin("CO_INVOICE_DATE", out)
    ck.need(ci, "invoice_date")
    ck.need_items(co)
    if co and inv_date:
        for it in co.items:
            f = it.get("inv_date")
            ck.need_item(co, it, "inv_date")
            if f:
                ck.compared()
            if f and f.value != inv_date:
                ck.add(Finding("CO_INVOICE_DATE", "ERROR", [co, ci], dict(no=it["no"]), f.raw,
                               f"{inv_date:%d/%m/%Y}", at(co, f) + at(ci, inv_f, "ref")))
    ck.end()
    ck_ship, ck_scd = begin("SHIPMENT_DATE", out), begin("SC_DATE", out)
    for s in scs:
        by_f = s.f.get("shipment_by")
        by = _v(by_f)
        ck_ship.need(s, "shipment_by")
        ck_ship.need(ci, "sailing")
        if by and sail:
            ck_ship.compared()
            if sail > by:
                ck_ship.add(Finding("SHIPMENT_LATE", "ERROR", [s], {}, f"{by:%d-%b-%Y}", f"≥ {sail:%d-%b-%Y}",
                                    at(s, by_f) + at(ci, sail_f, "ref")))
            elif (by - sail).days < CONFIG["shipment_slack_days"]:
                ck_ship.add(Finding("SHIPMENT_SLACK", "WARNING", [s], dict(days=(by - sail).days),
                                    f"{by:%d-%b-%Y} / {sail:%d-%b-%Y}", "", at(s, by_f) + at(ci, sail_f, "ref")))
        scd_f = s.f.get("sc_date")
        scd = _v(scd_f)
        ck_scd.need(s, "sc_date")
        ck_scd.need(ci, "invoice_date")
        if scd and inv_date:
            ck_scd.compared()
        if scd and inv_date and scd > inv_date:
            ck_scd.add(Finding("SC_DATE", "WARNING", [s], {}, f"{scd:%d/%m/%Y}", f"≤ {inv_date:%d/%m/%Y}",
                               at(s, scd_f) + at(ci, inv_f, "ref")))
    ck_ship.end()
    ck_scd.end()


def r_vessel(ci, bl, co, out):
    ref = bl.f.get("vessel") if bl else None
    cks = (begin("VESSEL.ci", out), begin("VESSEL.co", out))
    for ck in cks:
        ck.need(bl, "vessel")
    if ref:
        for ck, d in zip(cks, (ci, co)):
            f = d.f.get("vessel") if d else None
            ck.need(d, "vessel", absent_ok=True)
            if f:
                ck.compared()
            if f and f.value != ref.value:
                ck.add(Finding("VESSEL", "ERROR", [d, bl], {}, f.raw, f"{ref.value[0]} V.{ref.value[1]}",
                               at(d, f) + at(bl, ref, "ref")))
    for ck in cks:
        ck.end()


def r_co(ci, co, bl, out):
    if not (ci and co):
        return
    inv_no = _v(ci.f.get("invoice_no"))
    ck_q, ck_n = begin("CO_QTY", out), begin("CO_INVOICE_NO", out)
    for ck in (ck_q, ck_n):
        ck.need_items(co)
        ck.need_items(ci)
        if len(co.items) != len(ci.items):           # zip() pairs only the first lines: the rest is not compared
            ck.not_run("items_not_comparable", by="CO_ITEMS", n=len(co.items), m=len(ci.items))
    ck_n.need(ci, "invoice_no")
    for it, ci_it in zip(co.items, ci.items):
        ck_q.compared()
        if not _close(it["qty"].value, ci_it["qty"].value):
            ck_q.add(Finding("CO_QTY", "ERROR", [co, ci], dict(no=it["no"]), it["qty"].raw,
                             fmt_like(ci_it["qty"].value, it["qty"].raw),
                             at(co, it["qty"]) + at(ci, ci_it["qty"], "ref")))
        full = it.get("inv_ref_f")                 # whole number read from box 10 (it can wrap onto the next line)
        if inv_no:
            ck_n.compared()
        if inv_no and (it["inv_ref"] != inv_no if full else not inv_no.startswith(it["inv_ref"])):
            ck_n.add(Finding("CO_INVOICE_NO", "ERROR", [co, ci], dict(no=it["no"]), it["inv_ref"], inv_no,
                             at(co, full) + at(ci, ci.f.get("invoice_no"), "ref") if full else at_line(co, it["qty"].line)))
    ck_q.end()
    ck_n.end()
    ck = begin("CO_ITEMS", out)
    ck.need_items(co)
    ck.need_items(ci)
    ck.compared()
    if len(co.items) != len(ci.items):            # the whole item table is wrong (owner, 2026-11-19): box it at once
        locs = _co_table(co) or [x for it in co.items for x in (at(co, it.get("hs_f")) or at_line(co, it["qty"].line))]
        locs += [x for it in ci.items for x in at_line(ci, it["qty"].line, "ref")]
        ck.add(Finding("CO_ITEMS", "ERROR", [co, ci], _items_diff(co, ci), _item_list(co), _item_list(ci), locs))
    ck.end()
    for k, ci_k in (("total_value", "amount"), ("total_qty", "qty")):
        ck = begin("CO_TOTAL.value" if k == "total_value" else "CO_TOTAL.qty", out)
        a, b = co.f.get(k), true_total(ci, ci_k)
        bv = b.value if b else None
        ck.need(co, k)
        ck.need_total_val(ci, ci_k, b)
        if a and bv is not None:
            ck.compared()
        words = (co.lists.get("total_qty_words") or [None])[0] if k == "total_qty" else None
        wv = words_to_number(words.value) if words else None
        ph = _phrase(words, a) if a else None
        if a and bv is not None and not _close(a.value, bv) and ph is not None and wv is not None and not _close(wv, bv):
            # words and figure both wrong: one finding over the whole phrase (owner, 2026-11-19)
            want = f"{_words_like(bv, words.value)} ({fmt_like(bv, a.raw)})"
            ck.add(Finding("CO_TOTAL", "ERROR", [co, ci], dict(label="@total_qty_phrase", src="@src_invoice"), ph.raw,
                           want, at(co, ph) + at(ci, b, "ref")))
        elif (k == "total_value" and a and bv is not None and not _close(a.value, bv) and co.lists.get("total_value_words")
              and (vw := words_to_number(" ".join(p.value for p in co.lists["total_value_words"]))) is not None
              and not _close(vw, bv)):
            # the amount in words and in figures both wrong (words over 1-2 lines): one finding over the whole phrase
            parts = co.lists["total_value_words"]
            words = " ".join(p.value for p in parts)
            last = parts[-1]
            t = last.line.text
            end = a.end + (1 if t[a.end:a.end + 1] == ")" else 0)
            tail = Field(t[last.start:end], t[last.start:end], last.line, last.start, end) if last.line is a.line else None
            boxes = [x for p in parts[:-1] for x in at(co, p)] + (at(co, tail) if tail else at(co, last) + at(co, a))
            ck.add(Finding("CO_TOTAL", "ERROR", [co, ci], dict(label="@total_value_phrase", src="@src_invoice"),
                           f"{words} ({a.raw})", f"{_amount_words(bv, a.raw, words)} ({fmt_like(bv, a.raw)})",
                           boxes + at(ci, b, "ref")))
        elif a and bv is not None and not _close(a.value, bv):
            ck.add(Finding("CO_TOTAL", "ERROR", [co, ci], dict(label=f"@{k}", src="@src_invoice"), a.raw,
                           f"{bv:,.2f}".rstrip("0").rstrip("."),
                           at(co, a) + at(ci, b, "ref")))
        ck.end()
    # Box 9 showing quantity (SET / PCS) instead of a per-item FOB value is normal practice, not a finding:
    # only the values themselves are checked (CO_QTY per item, CO_TOTAL for the totals).


_BL_QTY_TRACE = r"(?i)\b\d[\d,]*\s*(?:PCS|SETS?|PIECES?|UNITS?)\b"     # a quantity printed anywhere on the B/L


def _words_like(n, sample: str) -> str:
    """n in words, written like sample ('NINETY FOUR' without a hyphen gives 'NINETY EIGHT')."""
    w = number_to_words(n)
    return w if "-" in (sample or "") else w.replace("-", " ")


_DIGIT_WORDS = "ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE".split()


def _amount_words(v: float, sample_raw: str, sample_words: str) -> str:
    """1234.5 -> 'ONE THOUSAND TWO HUNDRED THIRTY FOUR POINT FIVE ZERO' (Form D style: decimals digit by digit,
    as many decimals as the printed figure, no hyphen if the document writes none)."""
    dec = len(sample_raw.split(".")[1]) if "." in sample_raw else 0
    whole, frac = f"{v:.{dec}f}".split(".") if dec else (f"{v:.0f}", "")
    w = _words_like(int(whole), sample_words)
    return w + (" POINT " + " ".join(_DIGIT_WORDS[int(c)] for c in frac) if frac else "")


def _phrase(words: Field, fig: Field) -> Field | None:
    """'NINETY FIVE (95)' as one Field when the words and the figure are on one line."""
    if words is None or fig is None or words.line is not fig.line or words.end > fig.start:
        return None
    t = words.line.text
    end = fig.end + (1 if t[fig.end:fig.end + 1] == ")" else 0)
    return Field(t[words.start:end], t[words.start:end], words.line, words.start, end)


def _model_of(it) -> str:
    m = it.get("model")
    return (m.value if isinstance(m, Field) else m) or "?"


def _item_list(d) -> str:
    """'2 items: AB-X10(W1)VN 100, CD-Y20(W1)VN 200' (model and quantity of each line)."""
    rows = [f"{_model_of(it)} {fmt_like(it['qty'].value, it['qty'].raw)}" for it in d.items]
    return f"{len(rows)}: " + ", ".join(rows)


def _items_diff(co, ci) -> dict:
    """Models on the invoice that the Form D does not list, and models on the Form D that the invoice does not have."""
    fd = [master.key(_model_of(it)) for it in co.items]
    inv = [master.key(_model_of(it)) for it in ci.items]
    show = {master.key(_model_of(it)): _model_of(it) for it in list(ci.items) + list(co.items)}
    missing = [show[k] for k in dict.fromkeys(inv) if k not in fd]
    extra = [show[k] for k in dict.fromkeys(fd) if k not in inv]
    parts = dict(en=[], vi=[])
    if missing:
        parts["en"].append("missing on Form D: " + ", ".join(missing))
        parts["vi"].append("C/O thiếu: " + ", ".join(missing))
    if extra:
        parts["en"].append("not on the invoice: " + ", ".join(extra))
        parts["vi"].append("không có trên hóa đơn: " + ", ".join(extra))
    return dict(diff_en=(" — " + "; ".join(parts["en"])) if parts["en"] else "",
                diff_vi=(" — " + "; ".join(parts["vi"])) if parts["vi"] else "")


def _co_table(co) -> list:
    """The Form D item table (boxes 5-10) on each page with items: from the first item line down to the TOTAL lines."""
    out = []
    for pg in sorted({it["qty"].line.page for it in co.items}):
        first = min((it["qty"].line for it in co.items if it["qty"].line.page == pg), key=lambda l: l.y)
        lines = [l for l in co.lines if l.page == pg and l.y >= first.y - 1]
        stop = next((l for l in lines if re.match(r"\s*TOTAL\s*:", l.text)), None)
        rows = [l for l in lines if stop is None or l.y < stop.y - 1] or [first]
        x0, y0 = min(l.bbox[0] for l in rows), min(l.bbox[1] for l in rows)
        x1, y1 = max(l.bbox[2] for l in rows), max(l.bbox[3] for l in rows)
        y1 = min(y1 + 1, stop.bbox[1] - 0.5) if stop is not None else y1 + 1   # never into the TOTAL lines
        out.append(Loc(co, pg, (x0 - 2, y0 - 1, x1 + 2, y1), None, "wrong"))
    return out


# Form D item details: not checked one by one when the item table itself is wrong (CO_ITEMS FAIL, owner 2026-11-19)
CO_DETAIL = ("CO_QTY", "CO_INVOICE_NO", "CO_INVOICE_DATE", "CO_MODEL", "CO_HS", "CO_PKG", "CO_GOODS_DESC",
             "CO_MARKS_MODEL", "CO_SUM", "CO_NUMBERING")
CO_DETAIL_KEYS = ("CO_QTY", "CO_INVOICE_NO", "CO_INVOICE_DATE", "CO_MODEL", "CO_HS_MASTER", "HS_CODE", "BL_HS_CODE",
                  "CO_PKG_COUNT", "CO_SET_PER_CTN", "PL_SET_PER_CTN", "CO_GOODS_DESC", "CO_MARKS_MODEL", "CO_SUM",
                  "CO_NUMBERING")


def _co_items_gate(out: list, docs: list):
    """CO_ITEMS failed: the Form D item table does not match the invoice lines, so its item-by-item findings would
    suggest nothing useful. They are withdrawn and their checks become NOT_RUN blocked_by CO_ITEMS; the Form D header
    and TOTAL lines are still checked."""
    cos = {id(f.docs[0]) for f in out if f.key == "CO_ITEMS"}
    if not cos:
        return
    out[:] = [f for f in out if not (id(f.docs[0]) in cos and f.key in CO_DETAIL_KEYS)
              and not (f.key == "MARKS_MISSING" and id(f.docs[0]) in cos)]
    run = current_run()
    if run is not None and run.group is not None:
        run.override(set(CO_DETAIL), CheckStatus.NOT_RUN, "blocked_by", dict(by="CO_ITEMS"), group_id=run.group.id)


def _bl_qty(bl, refs, qty, qty_locs, ctn, ctn_locs, out, ck_q=None, ck_c=None, qty_src=(), ctn_src=()):
    """'1,251 CARTONS (1,251 SETS)' in the B/L description: the sets against the invoice total quantity and the
    cartons against the packing-list total cartons. Both wrong: one finding over the whole phrase.
    ck_q / ck_c: the BL_CARGO_QTY / BL_CARGO_CTN checks; *_src: [(invoice, true_total value)] for their records."""
    ck_q, ck_c = ck_q or begin("BL_CARGO_QTY", out), ck_c or begin("BL_CARGO_CTN", out)
    q, c, ph = bl.f.get("bl_qty"), bl.f.get("bl_qty_ctn"), bl.f.get("bl_qty_phrase")
    ck_q.need(bl, "bl_qty", trace=_BL_QTY_TRACE)
    ck_c.need(bl, "bl_qty_ctn", trace=_BL_QTY_TRACE)
    for ci, v in qty_src:
        ck_q.need_total_val(ci, "qty", v)
    for ci, v in ctn_src:
        ck_c.need_total_val(ci, "ctn", v)
    if q and qty is not None:
        ck_q.compared()
    if c and ctn is not None:
        ck_c.compared()
    bad_q = bool(q and qty is not None and not _close(q.value, qty))
    bad_c = bool(c and ctn is not None and not _close(c.value, ctn))
    if bad_q and bad_c and ph and ph.line is q.line is c.line:
        t = ph.line.text
        want = (t[ph.start:c.start] + fmt_like(ctn, c.raw) + t[c.end:q.start] + fmt_like(qty, q.raw) + t[q.end:ph.end])
        f = Finding("BL_DESC_QTY", "ERROR", [bl] + refs, {}, ph.raw.strip(), want.strip(), at(bl, ph) + ctn_locs + qty_locs)
        ck_q.add(f)
        ck_c.link(f)
        ck_q.end()
        ck_c.end()
        return
    if bad_q:
        ck_q.add(Finding("BL_QTY", "ERROR", [bl] + refs, {}, q.raw, fmt_like(qty, q.raw), at(bl, q) + qty_locs))
    if bad_c:
        ck_c.add(Finding("BL_DESC_CTN", "ERROR", [bl] + refs, {}, c.raw, fmt_like(ctn, c.raw), at(bl, c) + ctn_locs))
    ck_q.end()
    ck_c.end()


def _all_parts(ci) -> bool:
    """Every goods line of the invoice is identified by a part number (no finished-goods model)."""
    ids = getattr(ci, "item_ids", None) if ci else None
    return bool(ids) and len(ids) == len(ci.items) and all(i.kind == "part_no" for i in ids)


def r_hs(ci, co, bl, out):
    """HS codes. With the HS master list (company Excel) the master is the reference and the document that
    differs is blamed: each Form D item, the B/L heading, and invoice models missing from the list.
    Models not in the master fall back to Form D vs B/L."""
    sval = lambda x: x.value if isinstance(x, Field) else x
    hs_bl_f = bl.f.get("hs") if bl else None
    blk = _bl_block(bl, ci)                       # several invoices on the B/L: the HS heading of this invoice's block
    if blk is not None and blk.hs:
        hs_bl_f = blk.hs
    hs_bl = master.digits(_v(hs_bl_f))
    have = master.load() is not None
    known = {}                                            # invoice model -> master HS
    parts = _all_parts(ci)
    ck = begin("HS_MASTER", out)
    if parts:                                             # every line is a part (part number), not a finished model
        ck.na(evidence="items_are_parts")
    elif ck.master(have) and ci:
        ck.need_items(ci)
    if have and ci and not parts:
        for it in ci.items:
            m = sval(it.get("model"))
            ck.need_item(ci, it, "model")
            if not m or m in known:
                continue
            hs = master.hs_for(m)
            known[m] = hs
            if hs is None:                                # master data, not a reading problem: NOT_RUN + the WARNING
                ck.not_run("master_data_missing", what="model")
                line = next((l for l in ci.lines if m in l.text), None)
                ck.add(Finding("HS_MASTER_MISSING", "WARNING", [ci], dict(model=m), m, "",
                               [Loc(ci, line.page if line else None, None, m)]))
            else:
                ck.compared()
    ck.end()
    ck = begin("CO_HS", out)
    ck.need_items(co)
    off = []                                              # Form D items not under the B/L heading (no master)
    for it in (co.items if co else []):
        m = sval(it.get("model"))
        ref = master.hs_for(m) if (have and m) else None
        loc = at(co, it.get("hs_f")) or at_line(co, it["qty"].line)
        if ref:
            ck.compared()
            if master.digits(it["hs"]) != ref:
                ck.add(Finding("CO_HS_MASTER", "ERROR", [co], dict(no=it["no"], model=m, ref=master.fmt(ref)),
                               it["hs"], master.fmt(ref), loc))
        elif hs_bl:
            ck.compared()
            if not master.digits(it["hs"]).startswith(hs_bl):
                off.append((it, loc))
        else:                                             # no master entry and no B/L heading: nothing to compare with
            if not have or m:
                ck.master(False) if not have else ck.not_run("master_data_missing", what="model")
            ck.need(bl, "hs")
    heads = {master.digits(it["hs"])[:len(hs_bl)] for it, _ in off}
    if len(off) >= 2 and len(off) == len(co.items) and len(heads) == 1:
        # every Form D item agrees with the others and none is under the B/L heading: the B/L is the odd one out
        hs = off[0][0]["hs"]
        ck.add(Finding("BL_HS_CODE", "ERROR", [bl, co], dict(hs=_v(hs_bl_f), ref=hs), _v(hs_bl_f),
                       master.digits(hs)[:len(hs_bl)], at(bl, hs_bl_f) + [l for _, loc in off for l in
                                                                        [replace(x, role="ref") for x in loc]]))
    else:
        for it, loc in off:
            ck.add(Finding("HS_CODE", "ERROR", [co, bl], dict(no=it["no"], hs=it["hs"], hs_bl=_v(hs_bl_f)), it["hs"],
                           _v(hs_bl_f) + "…", loc + at(bl, hs_bl_f, "ref")))
    ck.end()
    ck = begin("BL_HS", out)
    if parts:                                             # the B/L heading of a parts block: no finished-goods master
        ck.na(evidence="items_are_parts")
    ck.need(bl, "hs")
    refs = [h for h in known.values() if h]
    if ck.master(have) and hs_bl and not refs:
        ck.not_run("master_data_missing", what="model")
    if hs_bl and refs:
        ck.compared()
    if hs_bl and refs and not any(h.startswith(hs_bl) for h in refs):
        heads = Counter(h[:len(hs_bl)] for h in refs)
        ck.add(Finding("BL_HS_MASTER", "ERROR", [bl], dict(hs=_v(hs_bl_f), ref=", ".join(sorted(heads))),
                       _v(hs_bl_f), heads.most_common(1)[0][0], at(bl, hs_bl_f)))
    ck.end()


CNTR_CBM = {("20", "DC"): 33.2, ("40", "DC"): 67.7, ("40", "HC"): 76.3}   # usable volume, m3 (approx.)


def _cntr(t: str) -> tuple:
    """'40HQ' / "40'HC" / '20GP' -> ('40', 'HC') / ('20', 'DC')."""
    m = re.search(r"(\d{2})\s*'?\s*([A-Z]{2})", t.upper())
    if not m:
        return None
    kind = {"HQ": "HC", "GP": "DC", "ST": "DC"}.get(m[2], m[2])
    return m[1], kind


def _cntr_mix(text: str) -> Counter:
    """'3x40HQ' / "1X20'DC + 2X40'HC" -> Counter({('40','HC'): 3, ...})."""
    return Counter({_cntr(t): int(n) for n, t in re.findall(r"(\d+)\s*[xX]\s*(\d{2}\s*'?\s*[A-Z]{2})", text or "")})


_CNTR_NO = r"\b[A-Z]{4}\d{7}\b"                      # a container number printed on the B/L


def r_containers(ci, bl, out):
    """B/L container block: count in words and figures, each container's type vs the summary / invoice,
    volume per container vs its type, and the attach sheet adding up to the B/L totals."""
    if not bl:
        return
    lines = bl.lists.get("cntr", [])
    n_lines = len(lines)
    fig = bl.f.get("containers")
    ref_n = n_lines or (fig.value if fig else None)
    w, wn = bl.f.get("cntr_words"), bl.f.get("cntr_words_n")
    ck = begin("CNTR_WORDS", out, bl)
    ck.need(bl, "cntr_words", trace=r"\(\s*\d+\s*\)\s*CONTAINER")
    if not ref_n:
        ck.need_list(bl, "cntr", trace=_CNTR_NO)
        ck.need(bl, "containers")
    if w and ref_n:
        ck.compared()
        words_n = words_to_number(w.value)
        if words_n != ref_n or wn.value != ref_n:
            ck.add(Finding("CNTR_WORDS", "ERROR", [bl], dict(n=ref_n), w.raw,
                           f"{number_to_words(ref_n).upper()} ({ref_n})", at(bl, w)))
    ck.end()
    ck = begin("CNTR_COUNT", out, bl)
    ck.need(bl, "containers")
    ck.need_list(bl, "cntr", trace=_CNTR_NO)
    if fig and n_lines:
        ck.compared()
    if fig and n_lines and fig.value != n_lines:
        ck.add(Finding("CNTR_COUNT", "ERROR", [bl], dict(n=n_lines), str(fig.value), str(n_lines), at(bl, fig)))
    ck.end()
    ci_types = ci.lists.get("cntr_types", []) if ci else []
    summ = bl.f.get("cntr_summary")
    expect = _cntr_mix(ci_types[0].value) if ci_types else _cntr_mix(summ.value if summ else "")
    expect_txt = (ci_types[0].value if ci_types else summ.value if summ else "")
    src = "@invoice" if ci_types else "@bl_summary"
    loads = {x.value[0]: x for x in bl.lists.get("cntr_load", [])}
    ck = begin("CNTR_TYPE", out)
    ck.need_list(bl, "cntr", trace=_CNTR_NO)
    if not expect:
        ck.need_list(ci, "cntr_types", trace=r"(?i)TOTAL CONTAINER")
        ck.need(bl, "cntr_summary", trace=r"\d+\s*X\s*\d{2}")
    if expect and lines:
        ck.compared()
        have = Counter(_cntr(x.value[1]) for x in lines)
        extra = have - expect                         # types the B/L lists more often than expected
        missing = expect - have
        for x in lines:
            t = _cntr(x.value[1])
            if extra.get(t, 0) > 0:
                extra[t] -= 1
                sug = next(iter(missing.elements()), None)
                if sug:
                    missing[sug] -= 1
                ld = loads.get(x.value[0])
                cap = CNTR_CBM.get(t)
                over = bool(ld and cap and ld.value[3] > cap)
                ck.add(Finding("CNTR_TYPE_CBM" if over else "CNTR_TYPE", "ERROR", [bl] + ([ci] if ci_types else []),
                               dict(no=x.value[0], ref=expect_txt, src=src, cbm=f"{ld.value[3]:,.2f}" if ld else "",
                                    cap=f"{cap:g}" if cap else "", size=t[0]), x.value[1],
                               (sug[0] + sug[1]) if sug else "", at(bl, x) + (at(ci, ci_types[0], "ref") if ci_types else [])))
    ck.end()
    ck = begin("CNTR_SUMMARY", out)
    ck.need(bl, "cntr_summary", trace=r"\d+\s*X\s*\d{2}")
    ck.need_list(ci, "cntr_types", absent_ok=True, trace=r"(?i)TOTAL CONTAINER")
    if summ and ci_types:
        ck.compared()
    if summ and ci_types and _cntr_mix(summ.value) != expect:
        ck.add(Finding("CNTR_SUMMARY", "ERROR", [bl, ci], dict(ref=expect_txt), summ.value, expect_txt,
                       at(bl, summ) + at(ci, ci_types[0], "ref")))
    ck.end()
    flagged = {f.params.get("no") for f in out if f.key in ("CNTR_TYPE", "CNTR_TYPE_CBM")}
    ck = begin("CNTR_CAPACITY", out, bl)
    ck.need_list(bl, "cntr", trace=_CNTR_NO)
    ck.need_list(bl, "cntr_load", trace=r"//")
    for x in lines:                                   # a container that cannot hold what the attach sheet says
        t, ld = _cntr(x.value[1]), loads.get(x.value[0])
        cap = CNTR_CBM.get(t)
        if ld and cap:
            ck.compared()
        if ld and cap and ld.value[3] > cap and x.value[0] not in flagged:
            ck.add(Finding("CNTR_CAPACITY", "WARNING", [bl], dict(no=x.value[0], type=x.value[1], cbm=f"{ld.value[3]:,.2f}",
                                                                    cap=f"{cap:g}"), x.value[1], "", at(bl, x) + at(bl, ld, "ref")))
    if loads and lines and not ck.n_compared:
        ck.not_run("items_not_comparable", what="container_type")   # no known capacity for these container types
    ck.end()
    parts = {x["no"]: x for x in bl.lists.get("cntr_load_parts", [])}
    ck = begin("CNTR_ATTACH_SUM", out, bl)
    ck.need_list(bl, "cntr_load", trace=r"//")
    if loads:
        for k, i, label in (("ctn", 1, "@ctn"), ("gw", 2, "@gw"), ("cbm", 3, "@cbm")):
            tot = bl.f.get(k)
            ck.need(bl, k)
            s_ = sum(x.value[i] for x in loads.values())
            if tot:
                ck.compared()
            if not tot or _close(s_, tot.value, 0.0005):      # printed to the last decimal: a 0.01 change counts
                continue
            pl = true_total(ci, k) if ci else None
            if pl and _close(s_, pl.value, 0.0005) and not _close(tot.value, pl.value, 0.0005):
                ck.blocked("BL_VS_PL")
                continue                              # the rows agree with the packing list: the B/L total is the wrong
                                                      # one, and BL_VS_PL already says so
            rows = [x for no, ld in loads.items() for x in at(bl, parts[no][k] if no in parts else ld)]
            ck.add(Finding("CNTR_ATTACH_SUM", "ERROR", [bl], dict(label=label), f"{s_:,.2f}".rstrip("0").rstrip("."),
                           tot.raw, at(bl, tot, "ref") + rows))
    ck.end()


# a line starting with a model-like token: how shipping marks list models (one per line). A model in a goods
# description ('MODEL: AB-X10(W1)') does not count.
_MODEL_TRACE = r"^\s*[A-Z][A-Za-z0-9]*-[A-Za-z0-9\-]+\([A-Za-z0-9]+\)"


def _bl_block(bl, ci):
    """The cargo block of invoice ci on a B/L that prints one block per invoice (2 or more blocks); else None."""
    if not (bl and ci) or len(bl.cargo_blocks) < 2:
        return None
    no = re.sub(r"[^A-Z0-9]", "", str(_v(ci.f.get("invoice_no")) or "").upper())
    return next((b for b in bl.cargo_blocks if b.invoice and no
                 and re.sub(r"[^A-Z0-9]", "", str(b.invoice.value).upper()) == no), None)


def _block_goods(f: Field | None) -> Field | None:
    """'"ACME" BRAND RICE COOKER' -> RICE COOKER; '"SPARE PARTS OF RICE COOKER"' -> SPARE PARTS OF RICE COOKER."""
    if not f:
        return None
    t = str(f.value)
    m = re.search(r"\bBRAND\s+(.+)$", t)
    return Field((m[1] if m else t).strip(' "'), f.raw, f.line, f.start, f.end)


def r_bl_blocks(cis, bl, out):
    """A B/L that carries several invoices prints one cargo block each: each block's cartons and quantity against
    its own invoice (the B/L totals against the sum are BL_VS_PL / BL_CARGO_*)."""
    ck = begin("BL_CARGO_BLOCK", out)
    blocks = bl.cargo_blocks if bl else []
    if len(blocks) < 2:
        ck.na(evidence="one_cargo_block", by="BL_CARGO_QTY")
        ck.end()
        return
    ck._input(bl, "cargo_blocks", "READ")
    by_no = {re.sub(r"[^A-Z0-9]", "", str(_v(c.f.get("invoice_no")) or "").upper()): c for c in cis}
    for b in blocks:
        if not b.invoice:
            ck.not_run("items_not_comparable", what="cargo_block_without_invoice")
            continue
        c = by_no.get(re.sub(r"[^A-Z0-9]", "", str(b.invoice.value).upper()))
        if c is None:
            continue                              # an invoice that is not in the package: BL_INVOICE_EXTRA
        for k, f in (("qty", b.qty), ("ctn", b.ctn)):
            ref = true_total(c, k)
            ck.need_total_val(c, k, ref)
            if f is None:
                ck._input(bl, f"cargo_blocks[{k}]", "NOT_FOUND")
                continue
            if ref is None:
                continue
            ck.compared()
            if not _close(f.value, ref.value):
                ck.add(Finding("BL_BLOCK", "ERROR", [bl, c], dict(label=f"@{k}", inv=b.invoice.value), f.raw,
                               fmt_like(ref.value, f.raw), at(bl, f) + at(c, ref, "ref")))
    ck.end()


_MARKS_KEYS = {"BL": ("BL_MARKS_MODEL", "BL_MARKS_MODEL"), "CO": ("CO_MARKS_MODEL", "CO_MARKS_MODEL"),
               "CI": ("CI_MARKS_MODEL", None)}


def _marks_none_gate(out: list):
    """MARKS_NONE: a document's shipping marks list none of the invoice models. The whole block is one ERROR; the
    per-model findings on the same document (each 'model not on the invoice') are withdrawn."""
    hit = {id(f.docs[0]): f.docs[0].kind for f in out if f.key == "MARKS_NONE"}
    if not hit:
        return
    drop = {(d, _MARKS_KEYS[k][0]) for d, k in hit.items() if k in _MARKS_KEYS}
    out[:] = [f for f in out if (id(f.docs[0]), f.key) not in drop and not (
        f.key == "PL_MARKS_MODEL" and hit.get(id(f.docs[0])) == "CI")]
    checks = {_MARKS_KEYS[k][1] for k in hit.values() if k in _MARKS_KEYS and _MARKS_KEYS[k][1]}
    run = current_run()
    if checks and run is not None and run.group is not None:
        run.override(checks, CheckStatus.NOT_RUN, "blocked_by", dict(by="MARKS"), group_id=run.group.id)


def _block_explains(out: list):
    """Owner decision 2026-11-19: when a B/L block finding (BL_BLOCK) names the invoice whose block is wrong, the
    B/L total of the same figure (BL_QTY / BL_DESC_CTN / BL_DESC_QTY) is the same error: report it once."""
    blk = {f.params.get("label") for f in out if f.key == "BL_BLOCK"}
    if not blk:
        return
    drop = {k for k, lab in (("BL_QTY", "@qty"), ("BL_DESC_CTN", "@ctn")) if lab in blk}
    if "@qty" in blk or "@ctn" in blk:
        drop.add("BL_DESC_QTY")
    out[:] = [f for f in out if f.key not in drop]
    run = current_run()
    if run is not None:
        ids = ({"BL_CARGO_QTY"} if "@qty" in blk else set()) | ({"BL_CARGO_CTN"} if "@ctn" in blk else set())
        run.override(ids, CheckStatus.NOT_RUN, "blocked_by", dict(by="BL_CARGO_BLOCK"))


def r_bl_cargo(ci, co, bl, out):
    """B/L shipping marks, goods description and final destination against the invoice."""
    if not (ci and bl):
        return
    models = [m for m in {it.get("model") for it in ci.items} | {p.get("model") for p in ci.pl_items} if m]
    ck = begin("BL_MARKS_MODEL", out)
    ck.need_list(bl, "marks_models", trace=_MODEL_TRACE)     # marks not written as models ('BRAND/ABCD'): not applicable
    if bl.lists.get("marks_models"):
        for it in ci.items:
            ck.need_item(ci, it, "model")
    for f in bl.lists.get("marks_models", []):
        ck.compared()
        if f.value not in models:
            near = difflib.get_close_matches(f.value, models, n=1, cutoff=0.75)
            ck.add(Finding("BL_MARKS_MODEL", "ERROR" if near else "WARNING", [bl, ci], dict(model=f.value),
                           f.value, near[0] if near else "", at(bl, f)))
    ck.end()
    u = bl.f.get("bl_unit")
    ci_qty, ci_ctn = true_total(ci, "qty"), true_total(ci, "ctn")
    _bl_qty(bl, [ci], ci_qty and ci_qty.value, at(ci, ci_qty, "ref"), ci_ctn and ci_ctn.value, at(ci, ci_ctn, "ref"), out,
            qty_src=[(ci, ci_qty)], ctn_src=[(ci, ci_ctn)])
    unit_of = lambda t: {"SETS": "SET", "SET": "SET", "PCS": "PCS", "PC": "PCS", "PIECE": "PCS", "PIECES": "PCS",
                         "UNIT": "UNIT", "UNITS": "UNIT"}.get((t or "").upper())
    ci_unit = unit_of(_first_unit(ci))
    ck = begin("BL_UNIT", out)
    ck.need(bl, "bl_unit", trace=_BL_QTY_TRACE)
    ck.need_value(ci, "unit", ci_unit)
    if u and ci_unit and unit_of(u.value):
        ck.compared()
    elif u and ci_unit:
        ck.not_run("items_not_comparable", what="unit")
    if u and ci_unit and unit_of(u.value) and unit_of(u.value) != ci_unit:
        ck.add(Finding("BL_UNIT", "MINOR", [bl, ci], dict(unit=ci_unit), u.value, ci_unit + "S" if ci_unit == "SET" else ci_unit,
                       at(bl, u)))
    ck.end()
    g, cg = bl.f.get("goods"), ci.f.get("goods")
    blk = _bl_block(bl, ci)                       # several invoices on the B/L: the description of this invoice's block
    if blk is not None:
        g = _block_goods(blk.goods)
    ck = begin("BL_GOODS_DESC", out)
    if blk is not None:
        ck._input(bl, "cargo_blocks[goods]", "READ" if g else "NOT_FOUND")
    else:
        ck.need(bl, "goods")
    ck.need(ci, "goods")
    if g and cg:
        ck.compared()
    if g and cg and _norm_words(g.value) != _norm_words(cg.value):
        ck.add(Finding("BL_GOODS_DESC", "ERROR", [bl, ci], {}, g.value, cg.value, at(bl, g) + at(ci, cg, "ref")))
    ck.end()
    fd = bl.f.get("final_dest")
    ck = begin("BL_DESTINATION", out, bl)
    ck.need(bl, "final_dest", absent_ok=True)
    if fd:
        ref_f = bl.f.get("delivery") or bl.f.get("pod") or ci.f.get("pod")
        a, b = _city(fd.value), _city(ref_f.value) if ref_f else None
        if not ref_f:
            ck.need(bl, "delivery")
        if a and b:
            ck.compared()
        elif ref_f:
            ck.not_run("master_data_missing", what="city_list")      # place not in config "cities"
        if a and b and a != b:
            sug = (ci.f.get("pod") or ref_f).value
            ck.add(Finding("BL_DESTINATION", "ERROR", [bl], dict(dest=fd.value, ref=b), fd.value, sug,
                           at(bl, fd) + at(bl, ref_f, "ref")))
    ck.end()


def r_co_marks(ci, co, out):
    """Form D box 6 shipping marks: every model must be an invoice model."""
    if not (ci and co):
        return
    models = [m for m in {it.get("model") for it in ci.items} | {p.get("model") for p in ci.pl_items} if m]
    ck = begin("CO_MARKS_MODEL", out)
    ck.need_list(co, "marks_models", trace=_MODEL_TRACE)
    if co.lists.get("marks_models"):
        for it in ci.items:
            ck.need_item(ci, it, "model")
    for f in co.lists.get("marks_models", []):
        ck.compared()
        if f.value not in models:
            near = difflib.get_close_matches(f.value, models, n=1, cutoff=0.75)
            ck.add(Finding("CO_MARKS_MODEL", "ERROR" if near else "WARNING", [co, ci], dict(model=f.value),
                           f.value, near[0] if near else "", [Loc(co, f.line.page, None, f.raw)]))
    ck.end()


def _first_unit(doc) -> str | None:
    """Unit used for quantities on a document: SET / PCS / ... (first one written after a number)."""
    for l in doc.lines:
        m = re.search(r"\b[\d,]+\s*(SETS?|PCS|PIECES?|UNITS?)\b", l.text)
        if m:
            return m[1]
    return None


def _norm_words(t: str) -> str:
    return re.sub(r"[^A-Z]", "", (t or "").upper())


def _city(place: str) -> str | None:
    """Port / place name -> its city group from config "cities" (e.g. CAT LAI -> HO CHI MINH CITY)."""
    p = _norm_words(place)
    for city, names in CONFIG.get("cities", {}).items():
        if p in {_norm_words(n) for n in [city] + names}:
            return city
    return None


def _pairs(ci, co) -> list:
    """[(form_d_item, pl_item)]: same position when both list one line per PO, else a unique model match."""
    if not (ci and co):
        return []
    by_model = Counter(p.get("model") for p in ci.pl_items)
    same_order = len(co.items) == len(ci.pl_items)
    out = []
    for n, it in enumerate(co.items):
        p = ci.pl_items[n] if same_order else None
        if p and it.get("model") and p.get("model") and p["model"] != it["model"]:
            p = None
        if p is None and it.get("model") and by_model[it["model"]] == 1:
            p = next(x for x in ci.pl_items if x.get("model") == it["model"])
        if p is not None:
            out.append((it, p))
    return out


def _whole(x):
    return int(round(x)) if x is not None and abs(x - round(x)) < 1e-6 else None


def _true_ctn(it, p):
    """Cartons implied by quantity ÷ sets per carton (Form D '1 CARTON = N SET'), if that is a whole number."""
    per = it.get("per_ctn") if it else None
    return _whole(p["qty"].value / per) if per else None


def _fmt(x):
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def r_pl_ranges(ci, co, out):
    """Packing-list carton ranges run on (1-250, 251-700, …); each range holds quantity ÷ sets-per-carton cartons;
    the last carton number = total cartons."""
    if not ci:
        return
    items = [p for p in ci.pl_items if p.get("rng")]
    ck, ck_t = begin("PL_RANGES", out, ci), begin("PL_RANGE_TOTAL", out, ci)
    if not items:                                 # no 'CARTON n-m' printed: not applicable; printed but not read: NOT_RUN
        for c in (ck, ck_t):
            if has_text(ci, r"(?i)\bCARTON\s*(?:NO\.?\s*)?\d+\s*-\s*\d+"):
                c.not_run("field_not_found", field="pl_items[rng]", doc=ci.name)
                c._input(ci, "pl_items[rng]", "NOT_FOUND")
            else:
                c.na(evidence="not_printed", field="pl_items[rng]", doc=ci.name)
            c.end()
        return
    ck.need_items(ci, "pl_items")
    co_of = {id(p): it for it, p in _pairs(ci, co)}
    inv_of = {id(p): a for a, p in zip(ci.items, ci.pl_items)} if len(ci.items) == len(ci.pl_items) else {}
    expect = 1
    for p in items:
        a, b = p["rng"]
        have = b - a + 1
        cnt = _true_ctn(co_of.get(id(p)), p) or (have if have > 0 else None)
        model = p.get("model") or ""
        loc = at(ci, p.get("ctn_f"))
        ck.compared()
        if cnt is None:                                   # reversed range, nothing to go on
            ck.add(Finding("PL_RANGE_ORDER", "ERROR", [ci], dict(model=model), p["ctn_f"].raw, f"CARTON {b}-{a}", loc))
            expect = max(a, b) + 1
            continue
        want = f"CARTON {expect}-{expect + cnt - 1}"
        if (a, b) != (expect, expect + cnt - 1):
            per = co_of.get(id(p), {}).get("per_ctn")
            if b < a:
                key, sev_ = "PL_RANGE_ORDER", "ERROR"
            elif a != expect:
                key = "PL_RANGE_START" if expect == 1 else ("PL_RANGE_GAP" if a > expect else "PL_RANGE_OVERLAP")
                sev_ = "ERROR"
            else:
                key, sev_ = "PL_RANGE_COUNT", "ERROR"
                inv = inv_of.get(id(p))
                if per and inv and _close(inv["qty"].value / per, have):
                    # the range fits the invoice quantity: the packing-list quantity is the wrong one, and
                    # PL_LINE already reports it. The range is right; carry on from where it really ends.
                    expect = b + 1
                    continue
            ck.add(Finding(key, sev_, [ci] + ([co] if per else []),
                           dict(model=model, expect=expect, have=have, cnt=cnt, qty=p["qty"].raw, per=per or ""),
                           p["ctn_f"].raw, want, loc))
        expect += cnt
    ck.end()
    tot = ci.f.get("pl_total_ctn")
    ck_t.need(ci, "pl_total_ctn", absent_ok=True)
    ck_t._input(ci, "pl_items[rng]", "READ")
    if tot:
        ck_t.compared()
    if tot and expect - 1 != tot.value:
        ck_t.add(Finding("PL_RANGE_TOTAL", "ERROR", [ci], dict(last=expect - 1, total=f"{tot.value:,.0f}"),
                         tot.raw, f"{expect - 1:,}", at(ci, tot) + at(ci, items[-1].get("ctn_f"), "ref")))
    ck_t.end()


def _item_list_at(d, name: str, it):
    """The entry of d.lists[name] (kept parallel to d.items) for item it, or None."""
    lst = d.lists.get(name) or []
    k = next((i for i, x in enumerate(d.items) if x is it), None)
    return lst[k] if k is not None and k < len(lst) else None


def _product_name(desc: str) -> str:
    """'RICE COOKER SERIES 1.0L(NMF)' -> 'RICE COOKER'."""
    return re.split(r"\s+(?:SERIES\b|MODEL\b|\d|\()", desc.upper().strip(' "'))[0].strip()


def r_co_packages(ci, co, out):
    """Form D box 7 per item: cartons (figures + words) × sets per carton = quantity, and = packing list;
    goods name = invoice. Blame the document that does not add up."""
    if not (ci and co):
        return
    ck, ck_g = begin("CO_PKG", out), begin("CO_GOODS_DESC", out)
    pairs = _pairs(ci, co)
    for c in (ck, ck_g):
        c.need_items(co)
        c.need_items(ci, "pl_items")
        if co.items and ci.pl_items and not pairs:
            c.not_run("items_not_comparable", n=len(co.items), m=len(ci.pl_items))
    if pairs and len(pairs) < len(co.items):          # some Form D items have no packing-list line to compare with
        pl_models = {master.key(p.get("model")) for p in ci.pl_items if p.get("model")}
        paired = {id(it) for it, _p in pairs}
        lost = [it for it in co.items if id(it) not in paired]
        if lost and all(it.get("model") and master.key(it["model"]) not in pl_models for it in lost):
            ck.blocked("CO_MODEL")                    # their model is wrong (CO_MODEL reports it): not a reading gap
        else:
            ck.not_run("items_not_comparable", n=len(co.items), m=len(pairs))
    for it, p in pairs:
        fig, words, per, qty = it.get("pkg_fig"), it.get("pkg_words"), it.get("per_ctn"), it["qty"].value
        rng = p["ctn"]
        ref_locs = at(ci, p.get("ctn_f"), "ref")
        # true carton count = quantity ÷ sets per carton (when whole); otherwise the packing-list count
        truth = _whole(qty / per) if per else None
        truth = truth or rng
        n0 = ck.n_compared
        if fig and truth:
            ck.compared()
        if fig and truth and not _close(fig.value, truth):
            ck.add(Finding("CO_PKG_COUNT", "ERROR", [co, ci], dict(no=it["no"], what="@figures", ref=f"{truth:,}"),
                           f"({fig.raw})", f"({truth:,})", at(co, fig) + ref_locs))
        wv = words_to_number(words) if words else None
        if wv is not None and truth:
            ck.compared()
        if wv is not None and truth and not _close(wv, truth):
            wf = _item_list_at(co, "pkg_words_f", it)          # box the words themselves (they are what is wrong)
            ck.add(Finding("CO_PKG_COUNT", "ERROR", [co, ci], dict(no=it["no"], what="@words", ref=f"{truth:,}"),
                           words, _words_like(truth, words), (at(co, wf) if wf else at(co, fig) if fig else []) + ref_locs))
        if per and truth:
            ck.compared()
        if per and truth and not _close(per * truth, qty):
            ck.add(Finding("CO_SET_PER_CTN", "ERROR", [co, ci],
                           dict(no=it["no"], ctn=f"{truth:,.0f}", per=per, calc=f"{per * truth:,.0f}", qty=it["qty"].raw),
                           f"1 CARTON = {per} SET", f"1 CARTON = {_fmt(qty / truth)} SET",
                           at(co, it["qty"]) + ref_locs))
        if rng and per and not p.get("rng") and not _close(p["qty"].value / rng, per):
            # carton count given as a number (no range): ranges are checked by r_pl_ranges
            ck.add(Finding("PL_SET_PER_CTN", "ERROR", [ci, co],
                           dict(model=p["model"], ctn=f"{rng:,}", qty=p["qty"].raw, per=per),
                           _fmt(p["qty"].value / rng), f"{per}", at(ci, p["qty"]) + at(ci, p.get("ctn_f"))))
        if ck.n_compared == n0:                       # nothing of box 7 could be compared for this item
            ck.need_item(co, it, "pkg_fig")
            ck.need_item(co, it, "per_ctn")
        goods = it.get("goods")
        ck_g.need_item(co, it, "goods")
        ck_g.need_item(ci, p, "desc")
        if goods and p.get("desc"):
            want = _product_name(p["desc"].value)
            if want:
                ck_g.compared()
            if want and want not in re.sub(r"\s+", " ", goods.value.upper()):
                ck_g.add(Finding("CO_GOODS_DESC", "ERROR", [co, ci], dict(no=it["no"], model=it.get("model") or ""),
                                 goods.value, want, at(co, goods) + at(ci, p["desc"], "ref")))
    ck.end()
    ck_g.end()
    tot, tot_w, ref = co.f.get("total_ctn"), co.f.get("total_ctn_words"), true_total(ci, "ctn")
    ck = begin("CO_TOTAL.ctn", out)
    ck.need(co, "total_ctn")
    ck.need_total_val(ci, "ctn", ref)
    if tot and ref:
        ck.compared()
        wv = words_to_number(tot_w.value) if tot_w else None
        ph = _phrase(tot_w, tot)
        if not _close(tot.value, ref.value) and wv is not None and not _close(wv, ref.value) and ph is not None:
            # words and figure both wrong: one finding over the whole phrase (owner, 2026-11-19)
            want = f"{_words_like(ref.value, tot_w.value)} ({fmt_like(ref.value, tot.raw)})"
            ck.add(Finding("CO_TOTAL", "ERROR", [co, ci], dict(label="@ctn_phrase", src="@src_pl"), ph.raw, want,
                           at(co, ph) + at(ci, ref, "ref")))
            ck.end()
            return
        if not _close(tot.value, ref.value):
            ck.add(Finding("CO_TOTAL", "ERROR", [co, ci], dict(label="@ctn", src="@src_pl"), tot.raw, f"{ref.value:,.0f}",
                           at(co, tot) + at(ci, ref, "ref")))
        if wv is not None and not _close(wv, ref.value):
            ck.add(Finding("CO_TOTAL", "ERROR", [co, ci], dict(label="@ctn_words", src="@src_pl"), tot_w.value,
                           _words_like(ref.value, tot_w.value), at(co, tot_w) + at(ci, ref, "ref")))
    ck.end()


def r_pod(docs, out):
    for d in docs:
        ck = begin("PORT_NAME", out, d)
        ck.compared()                                 # scan of the port names read on the document
        for f in d.lists.get("pod", []):
            canon = _canon_port(f.value)
            if canon and f.value.upper().strip() != canon:
                # spelling of a known port (HOCHIMINH for HO CHI MINH CITY): information, not a document error (owner, 2026-11-19)
                ck.add(Finding("PORT_NAME", "INFO", [d], {}, f.value, canon, at(d, f)))
        ck.end()


def r_words(docs, out):
    has_pl = any(d.kind == "CI" and d.pl_items for d in docs)
    for d in docs:
        ck = begin("WORDS_VS_FIGURES", out, d)
        ck.compared()                                 # scan of every "words (figures)" pair on the document
        aw, tot = d.f.get("amount_words"), d.f.get("total_amount")
        checks = []
        if aw and tot:
            checks.append((aw.value, tot.value, "Amount in words / Số tiền bằng chữ", at_line(d, aw.line)))
        if d.kind in ("CO", "BL"):
            joined = " ".join(l.text for l in d.lines)
            for m in re.finditer(r"((?:[A-Z]+[\- ])*[A-Z]+) \(([\d,.]+)\)", joined):
                if has_pl and re.match(r"\s*(?:CARTON|CASE|PALLET|PACKAGE|BOX)", joined[m.end():]):
                    continue                  # carton counts: r_co_packages checks words and figures vs the packing list
                if d.kind == "BL" and re.match(r"\s*CONTAINER", joined[m.end():]):
                    continue                  # container count in words: r_containers (CNTR_WORDS)
                # box the figure on the line where it follows these words (not the first '(n)' on the page)
                tail = m[1].split()[-1]
                ln = next((l for l in d.lines if re.search(re.escape(tail) + r"\s*\(" + re.escape(m[2]) + r"\)", l.text)), None)
                fm = re.search(r"\(" + re.escape(m[2]) + r"\)", ln.text) if ln else None
                loc = at(d, Field(m[2], f"({m[2]})", ln, fm.start(), fm.end())) if fm else [Loc(d, None, None, f"({m[2]})")]
                checks.append((m[1], float(m[2].replace(",", "")), f"{m[1]} ({m[2]})", loc))
        # a Form D TOTAL line already reported against the invoice / packing list: not again as words vs figures
        covered = [l for f in out if f.key == "CO_TOTAL" for l in f.locs if l.role == "wrong" and l.doc is d]
        for words, n, what, locs in checks:
            if any(l.page == c.page and l.clip and c.clip and l.clip[1] < c.clip[3] and c.clip[1] < l.clip[3]
                   for l in locs for c in covered):
                continue                      # the whole phrase is already reported against the invoice / packing list
            w = words_to_number(words)
            if w is not None and not _close(w, n):
                ck.add(Finding("WORDS_VS_FIGURES", "ERROR", [d], dict(what=what), f"{words.strip()} = {w:,}",
                               f"{n:,}", locs))
        ck.end()


def r_text_fixes(docs, out):
    for d in docs:
        ck = begin("TEXT_FIXES", out, d)
        ck.compared()
        for fx in CONFIG["text_fixes"]:
            if fx.get("kinds") and d.kind not in fx["kinds"]:
                continue
            rx = re.compile(fx["pattern"])
            for l in d.lines:
                for m in rx.finditer(l.text):
                    f = Field(m[0], m[0], l, m.start(), m.end())
                    ck.add(Finding(fx["id"], fx.get("severity", "MINOR"), [d], {}, m[0], m.expand(fx["replace"]),
                                   at(d, f)))
        ck.end()


def r_broken_wrap(docs, out):
    """A word split across two lines in a B/L box ('HOT PO' / 'T', 'THAILAND, C' / 'Y')."""
    for d in docs:
        if d.kind != "BL":
            continue
        ck = begin("WORD_WRAP", out, d)
        ck.compared()
        for i, b in enumerate(d.lines):
            for t in b.spans:
                frag = t.text.strip()
                if not re.fullmatch(r"[A-Z]{1,2}", frag):
                    continue
                # the line above in the SAME column (other columns' lines may sit in between)
                above = [a for a in d.lines[max(0, i - 4):i] if a.page == b.page and 0 < b.y - a.y < 14]
                s = next((s for a in reversed(above) for s in a.spans
                          if abs(s.bbox[0] - t.bbox[0]) < 5 and re.search(r"[A-Z]$", s.text)), None)
                if s:
                    a = next(a for a in above if s in a.spans)
                    last = re.search(r"([A-Z]+)$", s.text)[1]
                    ck.add(Finding("WORD_WRAP", "MINOR", [d], {}, f"{last} / {frag}", last + frag,
                                   [Loc(d, a.page, s.bbox, None), Loc(d, b.page, t.bbox, None)]))
        ck.end()


def r_documents(scs, cos, out):
    for s in scs:
        ck = begin("SC_DOCS", out, s)
        f = s.f.get("docs_required")
        if ck.need(s, "docs_required"):
            ck.compared()
        req = f.value.upper() if f else ""
        ins_line = next((l for l in s.lines if "INSURANCE" in l.text.upper()), None)
        if s.lists.get("fob") and "INSURANCE" in req:
            ck.add(Finding("SC_DOCS_INSURANCE", "WARNING", [s], {}, "Insurance Policy", "",
                           at_line(s, ins_line) if ins_line else []))
        if cos and not re.search(r"CERTIFICATE OF ORIGIN|\bORIGIN\b|FORM D", req):
            doc_line = next((l for l in s.lines if "DOCUMENTS REQUIRED" in l.text.upper()), None)
            ck.add(Finding("SC_DOCS_FORMD", "INFO", [s], {}, "", "Form D",
                           at_line(s, doc_line) if doc_line else []))
        ck.end()


def r_draft_status(docs, out):
    for d in docs:
        ck = begin("DRAFT_STATUS", out, d)
        ck.compared()
        if d.kind in ("BL", "CO") and not d.is_draft:
            ck.add(Finding("ISSUED_DOC", "INFO", [d], {}, "", "DRAFT"))
        ck.end()


def validate(docs: list[Doc]) -> list[Finding]:
    """One invoice: every rule on the whole package. Several invoices under one B/L: the rules per invoice (its own
    contract and Form D, plus the B/L), then the B/L against all invoices together."""
    return validate_checks(docs)[0]


def _label(ci: Doc | None, docs: list[Doc]) -> str:
    if ci is not None:
        return _v(ci.f.get("invoice_no")) or ci.name
    return docs[0].name if docs else "—"


def validate_checks(docs: list[Doc]) -> tuple[list[Finding], list]:
    """Findings (exactly as validate() always gave them) + one CheckResult per check and group (engine/checks.py)."""
    cis = [d for d in docs if d.kind == "CI"]
    with Run(docs) as run:
        if len(cis) <= 1:
            run.set_group(Group("inv1", "invoice", _label(next(iter(cis), None), docs), list(docs)))
            out = _validate_group(docs)
            run.close_group()
            run.set_group(Group("shipment", "shipment", _label(next(iter(cis), None), docs), list(docs)))
            ck = begin("DOC_PAIRING", out)
            ck.na(evidence="one_invoice")
            ck.end()
            run.call(_bl_invoices, docs, cis, out)
            run.call(r_bl_blocks, cis, next((d for d in docs if d.kind == "BL"), None), out)
            _block_explains(out)
            run.close_group()
        else:
            out = _validate_multi(docs, cis)
        out.sort(key=lambda f: SEVERITY.index(f.severity))
        results = run.finish(out)
    return out, results


def _call(fn, *args):
    run = current_run()
    return run.call(fn, *args) if run is not None else fn(*args)


_SHARED_TOTALS = ("BL_VS_PL", "BL_QTY", "BL_DESC_CTN", "BL_DESC_QTY", "INVOICE_REF", "CONTAINERS")   # B/L figures that cover all invoices of the package


def _pair_score(d: Doc, ci: Doc) -> int:
    """How surely document d (contract, Form D) belongs to invoice ci."""
    no = _v(ci.f.get("invoice_no")) or ""
    score = 0
    if no and any(e["no"].value == no for e in d.lists.get("invoices", [])):        # Form D box 10
        score += 100
    if no and no.upper() in d.name.upper():
        score += 50
    amt = _v(d.f.get("total_amount")) or _v(d.f.get("total_value"))
    if _close(amt, _v(true_total(ci, "amount")), 0.01):
        score += 30
    if _close(_v(d.f.get("total_qty")), _v(true_total(ci, "qty")), 0.01):
        score += 10
    pos, cpos = set(re.findall(r"[A-Z]{2}\d{6,}", str(_v(d.f.get("pos")) or ""))), \
        set(re.findall(r"[A-Z]{2}\d{6,}", str(_v(ci.f.get("pos")) or "")))
    if pos and pos <= cpos:
        score += 5
    return score


def _sig(f: Finding):
    return (f.key, f.severity, tuple(d.name for d in f.docs), f.current, f.suggested,
            tuple((l.doc.name, l.page, l.clip, l.text, l.role) for l in f.locs))


def _validate_multi(docs: list[Doc], cis: list[Doc]) -> list[Finding]:
    run = current_run()
    groups = {id(c): [c] for c in cis}
    shared = [d for d in docs if d.kind not in ("CI", "SC", "CO")]       # B/L: one for the whole shipment
    out: list[Finding] = []
    ship = Group("shipment", "shipment", ", ".join(_label(c, docs) for c in cis), list(docs), multi=True)
    if run is not None:
        run.set_group(ship)
    ck = begin("DOC_PAIRING", out)
    if not any(d.kind in ("SC", "CO") for d in docs):
        ck.na(evidence="nothing_to_pair")
    for d in docs:
        if d.kind not in ("SC", "CO"):
            continue
        ck.compared()
        scores = sorted(((_pair_score(d, c), i) for i, c in enumerate(cis)), reverse=True)
        best = cis[scores[0][1]]
        groups[id(best)].append(d)
        if scores[0][0] == 0 or scores[0][0] == scores[1][0]:
            ck.add(Finding("DOC_UNPAIRED", "WARNING", [d, best], dict(inv=_v(best.f.get("invoice_no")) or best.name)))
    ck.end()
    seen = set()
    for n, c in enumerate(cis, 1):
        gdocs = groups[id(c)] + shared
        if run is not None:
            run.set_group(Group(f"inv{n}", "invoice", _label(c, docs), gdocs, multi=True))
        for f in _validate_group(gdocs):
            if f.key in _SHARED_TOTALS or _sig(f) in seen:   # same B/L finding from every invoice: once
                continue
            seen.add(_sig(f))
            out.append(f)
        if run is not None:
            run.close_group()
    if run is not None:
        run.set_group(ship)
    _call(_bl_invoices, docs, cis, out)
    _call(_multi_bl_totals, shared, cis, out)
    _call(r_bl_blocks, cis, next((d for d in shared if d.kind == "BL"), None), out)
    _block_explains(out)
    if run is not None:
        run.close_group()
    return out


def _multi_bl_totals(shared: list[Doc], cis: list[Doc], out: list):
    """The B/L figures against all invoices of the package together."""
    for bl in (d for d in shared if d.kind == "BL"):
        listed = {f.value for f in bl.lists.get("invoice_nos", [])}
        missing = listed - {_v(c.f.get("invoice_no")) for c in cis}
        if missing:                                       # B/L covers more than this package: BL_INVOICE_EXTRA
            for cid in ("BL_VS_PL.gw", "BL_VS_PL.cbm", "BL_VS_PL.ctn", "BL_CARGO_QTY", "BL_CARGO_CTN"):
                ck = begin(cid, out)
                ck.not_run("document_missing", kind="CI", inv=", ".join(sorted(missing)), evidence="bl_lists_invoice")
                ck.end()
            continue
        for k in ("gw", "cbm", "ctn"):
            ck = begin(f"BL_VS_PL.{k}", out)
            b, ps = bl.f.get(k), [true_total(c, k) for c in cis]
            ck.need(bl, k)
            for c, p in zip(cis, ps):                     # every invoice whose total is missing is named
                ck.need_total_val(c, k, p)
            if not b or not all(ps):
                ck.end()
                continue
            ck.compared()
            total = sum(p.value for p in ps)
            if not _close(b.value, total, 0.0005):
                ck.add(Finding("BL_VS_PL", "ERROR", [bl] + cis, dict(label=f"@{k}"), b.raw, fmt_like(total, b.raw),
                               at(bl, b) + [l for c, p in zip(cis, ps) for l in at(c, p, "ref")]))
            ck.end()
        ps = [true_total(c, "qty") for c in cis]
        cs = [true_total(c, "ctn") for c in cis]
        _bl_qty(bl, cis, sum(p.value for p in ps) if all(ps) else None,
                [l for c, p in zip(cis, ps) if p for l in at(c, p, "ref")],
                sum(x.value for x in cs) if all(cs) else None, [l for c, x in zip(cis, cs) if x for l in at(c, x, "ref")], out,
                qty_src=list(zip(cis, ps)), ctn_src=list(zip(cis, cs)))


def _bl_invoices(docs: list[Doc], cis: list[Doc], out: list):
    """The invoices named on the B/L = the invoices in the package."""
    inv = {_v(c.f.get("invoice_no")): c for c in cis if _v(c.f.get("invoice_no"))}
    run = current_run()
    for bl in (d for d in docs if d.kind == "BL"):
        ck = begin("BL_INVOICE_REFS", out)
        listed = {f.value: f for f in bl.lists.get("invoice_nos", [])}
        ck.need_list(bl, "invoice_nos")
        for c in cis:
            ck.need(c, "invoice_no")
        if not listed or not inv or not (set(listed) & set(inv)):
            if listed and inv:                            # both read, no invoice in common
                ck.not_run("items_not_comparable", what="invoice_refs") if len(cis) > 1 else ck.blocked("INVOICE_REF")
            ck.end()
            continue                                      # none matches: INVOICE_REF (one invoice) / per invoice below
        ck.compared()
        extra = [n for n in listed if n not in inv]
        for n in extra:
            ck.add(Finding("BL_INVOICE_EXTRA", "WARNING", [bl], dict(inv=n), n, "", at(bl, listed[n])))
        if extra:                                         # its weights / CBM / cartons include the missing invoice
            out[:] = [f for f in out if not (f.key in ("BL_VS_PL", "BL_QTY", "BL_DESC_CTN", "BL_DESC_QTY")
                                             and f.docs[0] is bl)]
            if run is not None:                           # those checks cannot be made: say so instead of PASS / FAIL
                run.override({"BL_VS_PL.gw", "BL_VS_PL.cbm", "BL_VS_PL.ctn", "BL_CARGO_QTY", "BL_CARGO_CTN"},
                             CheckStatus.NOT_RUN, "document_missing",
                             dict(kind="CI", inv=", ".join(extra), evidence="bl_lists_invoice"))
        if len(cis) > 1:
            for n, c in inv.items():
                if n not in listed:
                    ck.add(Finding("BL_INVOICE_MISSING", "ERROR", [bl, c], dict(inv=n), ", ".join(listed), n,
                                   [l for f in listed.values() for l in at(bl, f)] + at(c, c.f.get("invoice_no"), "ref")))
        ck.end()


def _validate_group(docs: list[Doc]) -> list[Finding]:
    by = lambda k: [d for d in docs if d.kind == k]
    ci = next(iter(by("CI")), None)
    bl = next(iter(by("BL")), None)
    co = next(iter(by("CO")), None)
    scs = by("SC")
    out: list[Finding] = []
    _call(r_line_math, docs, out)
    _call(r_pl_sums, docs, out)
    _call(r_bl_vs_pl, ci, bl, out)
    _call(r_incoterm, docs, ci, bl, out)
    _call(r_po_coverage, scs, ci, out)
    _call(r_sc_vs_ci, scs, ci, out)
    _call(r_dates, scs, ci, co, out)
    _call(r_vessel, ci, bl, co, out)
    _call(r_co, ci, co, bl, out)
    _co_items_gate(out, docs)                           # early too: later scans (far dates …) report what it withdraws
    _call(r_hs, ci, co, bl, out)
    _call(r_containers, ci, bl, out)
    _call(r_bl_cargo, ci, co, bl, out)
    _call(r_co_marks, ci, co, out)
    _call(r_pl_ranges, ci, co, out)
    _call(r_co_packages, ci, co, out)
    _call(r_pod, docs, out)
    _call(r_words, docs, out)
    _call(r_text_fixes, docs, out)
    _call(r_broken_wrap, docs, out)
    _call(r_documents, scs, by("CO"), out)
    _call(r_draft_status, docs, out)
    from .rules_net import validate_net                # cross-document + self-consistency rules (2.1)
    validate_net(docs, ci, bl, co, scs, out)
    _co_items_gate(out, docs)                           # Form D item table wrong as a whole: no item-by-item findings
    _marks_none_gate(out)                               # marks list none of the invoice models: one ERROR per document
    return out


def unrecognised(docs: list[Doc], skipped: list) -> list[dict]:
    """Everything the engine could not read — so nothing passes silently."""
    out = []
    for p in skipped:
        if p.suffix.lower() == ".pdf":
            out.append(dict(doc=p.name, what="File not recognised as CI/PL, SC, B/L or Form D",
                            vi="Không nhận diện được loại chứng từ"))
        else:
            out.append(dict(doc=p.name, what="Not a PDF — not checked (check it manually)",
                            vi="Không phải file PDF — chưa được kiểm tra (cần kiểm tra thủ công)"))
    kinds = {d.kind for d in docs}
    for k in ("CI", "SC", "BL", "CO"):
        if k not in kinds:
            out.append(dict(doc="—", what=f"No {CONFIG['doc_kinds'][k]['en']} in this set",
                            vi=f"Bộ chứng từ không có {CONFIG['doc_kinds'][k]['vi']}"))
    for d in docs:
        for fld in CONFIG["required_fields"].get(d.kind, []):
            if not d.f.get(fld) or _v(d.f.get(fld)) in (None, ""):
                out.append(dict(doc=d.name, what=f"Field not found: {fld}", vi=f"Không đọc được trường: {fld}"))
        for l in d.lists.get("unparsed", []):
            out.append(dict(doc=d.name, what=f"Goods line not read (page {l.page + 1}): {l.text.strip()[:80]}",
                            vi=f"Không đọc được dòng hàng (trang {l.page + 1}): {l.text.strip()[:80]}"))
        ids = list(getattr(d, "item_ids", []) or []) + list(getattr(d, "pl_item_ids", []) or [])
        for n, it in enumerate(d.items + d.pl_items, 1):
            if n <= len(ids) and ids[n - 1].kind == "part_no":
                continue                                  # a part: identified by its part number
            if not it.get("model") and d.kind in ("CI", "SC"):
                out.append(dict(doc=d.name, what=f"Model not found for goods line {n} (page {it['qty'].page + 1})",
                                vi=f"Không đọc được model của dòng hàng {n} (trang {it['qty'].page + 1})"))
        for lst in CONFIG["required_lists"].get(d.kind, []):
            if not getattr(d, lst):
                out.append(dict(doc=d.name, what=f"No line items found ({lst})",
                                vi=f"Không đọc được các dòng hàng ({lst})"))
    return out
