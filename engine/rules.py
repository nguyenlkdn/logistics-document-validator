"""Validation rules (report only). Each finding records where the wrong / reference values sit in the PDFs."""
import difflib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import master
from .extract import Doc, Field
from .util import fmt_like, number_to_words, words_to_number

SEVERITY = ["ERROR", "WARNING", "MINOR", "INFO"]
CONFIG = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text(encoding="utf-8"))


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

    def text(self, lang: str) -> str:
        p = {k: (CONFIG["labels"][v[1:]][lang] if isinstance(v, str) and v.startswith("@") else v)
             for k, v in self.params.items()}
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
    if f.end > f.start:
        spans = f.line.spans_for(f.start, f.end)
        clip = (min(s.bbox[0] for s in spans), min(s.bbox[1] for s in spans),
                max(s.bbox[2] for s in spans), max(s.bbox[3] for s in spans))
        return [Loc(doc, f.page, clip, f.raw, role)]
    return [Loc(doc, None, None, f.raw, role)] if f.raw else []


def at_line(doc: Doc, line, role="wrong") -> list:
    return [Loc(doc, line.page, line.bbox, None, role)]


def _v(f):
    return f.value if isinstance(f, Field) else None


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
        for it in d.items:
            exp = round(it["qty"].value * it["price"].value, 2)
            if not _close(exp, it["amount"].value):
                out.append(Finding("LINE_AMOUNT", "ERROR", [d], dict(model=it["model"]), it["amount"].raw,
                                   fmt_like(exp, it["amount"].raw),
                                   at(d, it["amount"]) + at(d, it["qty"], "ref") + at(d, it["price"], "ref")))
        tot = d.f.get("total_amount")
        if tot and d.items:
            exp = round(sum(it["qty"].value * it["price"].value for it in d.items), 2)
            if not _close(exp, tot.value):
                out.append(Finding("TOTAL_AMOUNT", "ERROR", [d], {}, tot.raw, fmt_like(exp, tot.raw), at(d, tot)))
        tq = d.f.get("total_qty")
        if tq and d.items:
            exp = sum(it["qty"].value for it in d.items)
            if not _close(exp, tq.value):
                out.append(Finding("TOTAL_QTY", "ERROR", [d], {}, tq.raw, fmt_like(exp, tq.raw), at(d, tq)))


def r_pl_sums(docs, out):
    for d in docs:
        if d.kind != "CI" or not d.pl_items:
            continue
        for k in ("qty", "nw", "gw", "cbm"):
            tot = d.f.get(f"pl_total_{k}")
            exp = round(sum(it[k].value for it in d.pl_items), 3)
            if tot and not _close(exp, tot.value):
                out.append(Finding("PL_TOTAL", "ERROR", [d], dict(label=f"@{k}"), tot.raw, fmt_like(exp, tot.raw),
                                   at(d, tot)))
        ctn = d.f.get("pl_total_ctn")
        if ctn and all(it["ctn"] for it in d.pl_items) and not any(it.get("rng") for it in d.pl_items):
            exp = sum(it["ctn"] for it in d.pl_items)
            if not _close(exp, ctn.value):
                out.append(Finding("PL_TOTAL", "ERROR", [d], dict(label="@ctn"), ctn.raw, fmt_like(exp, ctn.raw),
                                   at(d, ctn)))
        if d.items:
            ci_q = sum(it["qty"].value for it in d.items)
            pl_q = sum(it["qty"].value for it in d.pl_items)
            if not _close(ci_q, pl_q):
                out.append(Finding("CI_PL_QTY", "ERROR", [d], {}, f"{pl_q:,.0f}", f"{ci_q:,.0f}",
                                   at(d, d.f.get("pl_total_qty")) + at(d, d.f.get("total_qty"), "ref")))


def r_bl_vs_pl(ci, bl, out):
    if not (ci and bl):
        return
    for k, pk in (("gw", "pl_total_gw"), ("cbm", "pl_total_cbm"), ("ctn", "pl_total_ctn")):
        b, p = bl.f.get(k), ci.f.get(pk)
        if b and p and not _close(b.value, p.value, 0.0005):
            out.append(Finding("BL_VS_PL", "ERROR", [bl, ci], dict(label=f"@{k}"), b.raw, fmt_like(p.value, b.raw),
                               at(bl, b) + at(ci, p, "ref")))
    c1, c2 = bl.f.get("containers"), ci.f.get("containers")
    if c1 and c2 and c1.value != c2.value:
        out.append(Finding("CONTAINERS", "ERROR", [bl, ci], {}, str(c1.value), str(c2.value),
                           at(bl, c1) + at(ci, c2, "ref")))
    b, c = bl.f.get("invoice_no"), ci.f.get("invoice_no")
    if b and c and b.value != c.value:
        out.append(Finding("INVOICE_REF", "ERROR", [bl, ci], {}, b.raw, c.value, at(bl, b) + at(ci, c, "ref")))


def r_incoterm(docs, ci, bl, out):
    src = (bl, bl.f.get("pol")) if bl and bl.f.get("pol") else ((ci, ci.f.get("pol")) if ci else (None, None))
    if not src[1]:
        return
    pol = src[1].value.upper().strip()
    for d in docs:
        fobs = d.lists.get("fob", [])
        good = [f for f in fobs if pol.startswith(f.value.upper().strip())]
        for f in fobs:
            place = f.value.upper().strip()
            if not pol.startswith(place):
                fob_box = lambda fld, role: [Loc(l.doc, l.page, l.clip, "FOB " + fld.raw, role) for l in at(d, fld, role)]
                same = [g for g in good if g.page == f.page]
                ref = fob_box((same or good)[0], "ref") if good else at(src[0], src[1], "ref")
                out.append(Finding("INCOTERM", "ERROR", [d], dict(place=place, pol=pol), f"FOB {place}",
                                   f"FOB {pol}", fob_box(f, "wrong") + ref))


def r_po_coverage(scs, ci, out):
    if not (ci and scs):
        return
    inv_pos = set(ci.f["pos"].value)
    sc_pos = set().union(*[set(s.f["pos"].value) for s in scs if s.f.get("pos")])
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
            out.append(Finding("SC_PO_TYPO", "ERROR", list(scs) + [ci], dict(sc=typo[0], po=typo[1]),
                               sc_raw, sc_raw.replace(typo[0], typo[1]), wrong + ref))
        else:
            out.append(Finding("SC_PO_MISSING", "ERROR", list(scs) + [ci], dict(missing=", ".join(missing)),
                               sc_raw, ", ".join(sorted(sc_pos | set(missing))), wrong + ref))
    if extra:
        out.append(Finding("SC_PO_EXTRA", "WARNING", list(scs), dict(extra=", ".join(extra)), ", ".join(extra), "",
                           [x for s in scs for x in at(s, s.f.get("sc_no"))]))


def r_sc_vs_ci(scs, ci, out):
    if not (ci and scs):
        return
    key = lambda it: (it["model"], it["qty"].value, round(it["price"].value, 2))
    a = Counter(key(it) for it in ci.items)
    b = Counter(key(it) for s in scs for it in s.items)
    if a != b:
        fmt = lambda c: "; ".join(f"{m} {q:,.0f} @ {p}" for m, q, p in sorted(c.elements()))
        locs = [x for s in scs for it in s.items if key(it) in (b - a) for x in at_line(s, it["qty"].line)]
        out.append(Finding("SC_VS_CI", "ERROR", list(scs) + [ci], {}, fmt(b - a), fmt(a - b), locs))
    for s in scs:
        nums = [it["no"] for it in s.items]
        if [n.value for n in nums] != list(range(1, len(nums) + 1)):
            out.append(Finding("SC_NUMBERING", "MINOR", [s], {}, ",".join(n.raw for n in nums),
                               ",".join(str(i) for i in range(1, len(nums) + 1)),
                               [x for i, n in enumerate(nums, 1) if n.value != i for x in at(s, n)]))


def r_dates(scs, ci, co, out):
    sail_f = ci.f.get("sailing") if ci else None
    sail = _v(sail_f)
    if co and sail and co.f.get("departure") and co.f["departure"].value != sail:
        f = co.f["departure"]
        out.append(Finding("DEPARTURE_DATE", "ERROR", [co, ci], {}, f.raw, f"{sail:%d/%m/%Y}",
                           at(co, f) + at(ci, sail_f, "ref")))
    inv_f = ci.f.get("invoice_date") if ci else None
    inv_date = _v(inv_f)
    if co and inv_date:
        for it in co.items:
            f = it.get("inv_date")
            if f and f.value != inv_date:
                out.append(Finding("CO_INVOICE_DATE", "ERROR", [co, ci], dict(no=it["no"]), f.raw,
                                   f"{inv_date:%d/%m/%Y}", at(co, f) + at(ci, inv_f, "ref")))
    for s in scs:
        by_f = s.f.get("shipment_by")
        by = _v(by_f)
        if by and sail:
            if sail > by:
                out.append(Finding("SHIPMENT_LATE", "ERROR", [s], {}, f"{by:%d-%b-%Y}", f"≥ {sail:%d-%b-%Y}",
                                   at(s, by_f) + at(ci, sail_f, "ref")))
            elif (by - sail).days < CONFIG["shipment_slack_days"]:
                out.append(Finding("SHIPMENT_SLACK", "WARNING", [s], dict(days=(by - sail).days),
                                   f"{by:%d-%b-%Y} / {sail:%d-%b-%Y}", "", at(s, by_f) + at(ci, sail_f, "ref")))
        scd_f = s.f.get("sc_date")
        scd = _v(scd_f)
        if scd and inv_date and scd > inv_date:
            out.append(Finding("SC_DATE", "WARNING", [s], {}, f"{scd:%d/%m/%Y}", f"≤ {inv_date:%d/%m/%Y}",
                               at(s, scd_f) + at(ci, inv_f, "ref")))


def r_vessel(ci, bl, co, out):
    ref = bl.f.get("vessel") if bl else None
    if not ref:
        return
    for d in (ci, co):
        f = d.f.get("vessel") if d else None
        if f and f.value != ref.value:
            out.append(Finding("VESSEL", "ERROR", [d, bl], {}, f.raw, f"{ref.value[0]} V.{ref.value[1]}",
                               at(d, f) + at(bl, ref, "ref")))


def r_co(ci, co, bl, out):
    if not (ci and co):
        return
    inv_no = _v(ci.f.get("invoice_no"))
    for it, ci_it in zip(co.items, ci.items):
        if not _close(it["qty"].value, ci_it["qty"].value):
            out.append(Finding("CO_QTY", "ERROR", [co, ci], dict(no=it["no"]), it["qty"].raw,
                               fmt_like(ci_it["qty"].value, it["qty"].raw),
                               at(co, it["qty"]) + at(ci, ci_it["qty"], "ref")))
        if inv_no and not inv_no.startswith(it["inv_ref"]):
            out.append(Finding("CO_INVOICE_NO", "ERROR", [co, ci], dict(no=it["no"]), it["inv_ref"], inv_no,
                               at_line(co, it["qty"].line)))
    if len(co.items) != len(ci.items):
        out.append(Finding("CO_ITEMS", "ERROR", [co, ci], {}, str(len(co.items)), str(len(ci.items))))
    for k, ci_k in (("total_value", "total_amount"), ("total_qty", "total_qty")):
        a, b = co.f.get(k), ci.f.get(ci_k)
        bv = b.value if b else (sum(i["qty"].value for i in ci.items) if k == "total_qty" else None)
        if a and bv is not None and not _close(a.value, bv):
            out.append(Finding("CO_TOTAL", "ERROR", [co, ci], dict(label=f"@{k}"), a.raw, f"{bv:,.2f}".rstrip("0").rstrip("."),
                               at(co, a) + at(ci, b, "ref")))
    # Box 9 showing quantity (SET / PCS) instead of a per-item FOB value is normal practice, not a finding:
    # only the values themselves are checked (CO_QTY per item, CO_TOTAL for the totals).


def r_hs(ci, co, bl, out):
    """HS codes. With the HS master list (company Excel) the master is the reference and the document that
    differs is blamed: each Form D item, the B/L heading, and invoice models missing from the list.
    Models not in the master fall back to Form D vs B/L."""
    sval = lambda x: x.value if isinstance(x, Field) else x
    hs_bl_f = bl.f.get("hs") if bl else None
    hs_bl = master.digits(_v(hs_bl_f))
    have = master.load() is not None
    known = {}                                            # invoice model -> master HS
    if have and ci:
        for it in ci.items:
            m = sval(it.get("model"))
            if not m or m in known:
                continue
            hs = master.hs_for(m)
            known[m] = hs
            if hs is None:
                line = next((l for l in ci.lines if m in l.text), None)
                out.append(Finding("HS_MASTER_MISSING", "WARNING", [ci], dict(model=m), m, "",
                                   [Loc(ci, line.page if line else None, None, m)]))
    for it in (co.items if co else []):
        m = sval(it.get("model"))
        ref = master.hs_for(m) if (have and m) else None
        loc = at(co, it.get("hs_f")) or at_line(co, it["qty"].line)
        if ref:
            if master.digits(it["hs"]) != ref:
                out.append(Finding("CO_HS_MASTER", "ERROR", [co], dict(no=it["no"], model=m, ref=master.fmt(ref)),
                                   it["hs"], master.fmt(ref), loc))
        elif hs_bl and not master.digits(it["hs"]).startswith(hs_bl):
            out.append(Finding("HS_CODE", "ERROR", [co, bl], dict(no=it["no"], hs=it["hs"], hs_bl=_v(hs_bl_f)), it["hs"],
                               _v(hs_bl_f) + "…", loc + at(bl, hs_bl_f, "ref")))
    refs = [h for h in known.values() if h]
    if hs_bl and refs and not any(h.startswith(hs_bl) for h in refs):
        heads = Counter(h[:len(hs_bl)] for h in refs)
        out.append(Finding("BL_HS_MASTER", "ERROR", [bl], dict(hs=_v(hs_bl_f), ref=", ".join(sorted(heads))),
                           _v(hs_bl_f), heads.most_common(1)[0][0], at(bl, hs_bl_f)))


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
    if not items:
        return
    co_of = {id(p): it for it, p in _pairs(ci, co)}
    expect = 1
    for p in items:
        a, b = p["rng"]
        have = b - a + 1
        cnt = _true_ctn(co_of.get(id(p)), p) or (have if have > 0 else None)
        model = p.get("model") or ""
        loc = at(ci, p.get("ctn_f"))
        if cnt is None:                                   # reversed range, nothing to go on
            out.append(Finding("PL_RANGE_ORDER", "ERROR", [ci], dict(model=model), p["ctn_f"].raw, f"CARTON {b}-{a}", loc))
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
            out.append(Finding(key, sev_, [ci] + ([co] if per else []),
                               dict(model=model, expect=expect, have=have, cnt=cnt, qty=p["qty"].raw, per=per or ""),
                               p["ctn_f"].raw, want, loc))
        expect += cnt
    tot = ci.f.get("pl_total_ctn")
    if tot and expect - 1 != tot.value:
        out.append(Finding("PL_RANGE_TOTAL", "ERROR", [ci], dict(last=expect - 1, total=f"{tot.value:,.0f}"),
                           tot.raw, f"{expect - 1:,}", at(ci, tot) + at(ci, items[-1].get("ctn_f"), "ref")))


def _product_name(desc: str) -> str:
    """'RICE COOKER SERIES 1.0L(NMF)' -> 'RICE COOKER'."""
    return re.split(r"\s+(?:SERIES\b|MODEL\b|\d|\()", desc.upper().strip(' "'))[0].strip()


def r_co_packages(ci, co, out):
    """Form D box 7 per item: cartons (figures + words) × sets per carton = quantity, and = packing list;
    goods name = invoice. Blame the document that does not add up."""
    if not (ci and co):
        return
    for it, p in _pairs(ci, co):
        fig, words, per, qty = it.get("pkg_fig"), it.get("pkg_words"), it.get("per_ctn"), it["qty"].value
        rng = p["ctn"]
        ref_locs = at(ci, p.get("ctn_f"), "ref")
        # true carton count = quantity ÷ sets per carton (when whole); otherwise the packing-list count
        truth = _whole(qty / per) if per else None
        truth = truth or rng
        if fig and truth and not _close(fig.value, truth):
            out.append(Finding("CO_PKG_COUNT", "ERROR", [co, ci], dict(no=it["no"], what="@figures", ref=f"{truth:,}"),
                               f"({fig.raw})", f"({truth:,})", at(co, fig) + ref_locs))
        wv = words_to_number(words) if words else None
        if wv is not None and truth and not _close(wv, truth):
            out.append(Finding("CO_PKG_COUNT", "ERROR", [co, ci], dict(no=it["no"], what="@words", ref=f"{truth:,}"),
                               words, number_to_words(truth), (at(co, fig) if fig else []) + ref_locs))
        if per and truth and not _close(per * truth, qty):
            out.append(Finding("CO_SET_PER_CTN", "ERROR", [co, ci],
                               dict(no=it["no"], ctn=f"{truth:,.0f}", per=per, calc=f"{per * truth:,.0f}", qty=it["qty"].raw),
                               f"1 CARTON = {per} SET", f"1 CARTON = {_fmt(qty / truth)} SET",
                               at(co, it["qty"]) + ref_locs))
        if rng and per and not p.get("rng") and not _close(p["qty"].value / rng, per):
            # carton count given as a number (no range): ranges are checked by r_pl_ranges
            out.append(Finding("PL_SET_PER_CTN", "ERROR", [ci, co],
                               dict(model=p["model"], ctn=f"{rng:,}", qty=p["qty"].raw, per=per),
                               _fmt(p["qty"].value / rng), f"{per}", at(ci, p["qty"]) + at(ci, p.get("ctn_f"))))
        goods = it.get("goods")
        if goods and p.get("desc"):
            want = _product_name(p["desc"].value)
            if want and want not in re.sub(r"\s+", " ", goods.value.upper()):
                out.append(Finding("CO_GOODS_DESC", "ERROR", [co, ci], dict(no=it["no"], model=it.get("model") or ""),
                                   goods.value, want, at(co, goods) + at(ci, p["desc"], "ref")))
    tot, tot_w, ref = co.f.get("total_ctn"), co.f.get("total_ctn_words"), ci.f.get("pl_total_ctn")
    if tot and ref:
        if not _close(tot.value, ref.value):
            out.append(Finding("CO_TOTAL", "ERROR", [co, ci], dict(label="@ctn"), tot.raw, f"{ref.value:,.0f}",
                               at(co, tot) + at(ci, ref, "ref")))
        wv = words_to_number(tot_w.value) if tot_w else None
        if wv is not None and not _close(wv, ref.value):
            out.append(Finding("CO_TOTAL", "ERROR", [co, ci], dict(label="@ctn_words"), tot_w.value,
                               number_to_words(ref.value), at(co, tot_w) + at(ci, ref, "ref")))


def r_pod(docs, out):
    for d in docs:
        for f in d.lists.get("pod", []):
            canon = _canon_port(f.value)
            if canon and f.value.upper().strip() != canon:
                out.append(Finding("PORT_NAME", "WARNING", [d], {}, f.value, canon, at(d, f)))


def r_words(docs, out):
    has_pl = any(d.kind == "CI" and d.pl_items for d in docs)
    for d in docs:
        aw, tot = d.f.get("amount_words"), d.f.get("total_amount")
        checks = []
        if aw and tot:
            checks.append((aw.value, tot.value, "Amount in words / Số tiền bằng chữ", at_line(d, aw.line)))
        if d.kind == "CO":
            joined = " ".join(l.text for l in d.lines)
            for m in re.finditer(r"((?:[A-Z]+[\- ])*[A-Z]+) \(([\d,.]+)\)", joined):
                if has_pl and re.match(r"\s*(?:CARTON|CASE|PALLET|PACKAGE|BOX)", joined[m.end():]):
                    continue                  # carton counts: r_co_packages checks words and figures vs the packing list
                checks.append((m[1], float(m[2].replace(",", "")), f"{m[1]} ({m[2]})",
                               [Loc(d, None, None, f"({m[2]})")]))
        for words, n, what, locs in checks:
            w = words_to_number(words)
            if w is not None and not _close(w, n):
                out.append(Finding("WORDS_VS_FIGURES", "ERROR", [d], dict(what=what), f"{words.strip()} = {w:,}",
                                   f"{n:,}", locs))


def r_text_fixes(docs, out):
    for d in docs:
        for fx in CONFIG["text_fixes"]:
            if fx.get("kinds") and d.kind not in fx["kinds"]:
                continue
            rx = re.compile(fx["pattern"])
            for l in d.lines:
                for m in rx.finditer(l.text):
                    f = Field(m[0], m[0], l, m.start(), m.end())
                    out.append(Finding(fx["id"], fx.get("severity", "MINOR"), [d], {}, m[0], m.expand(fx["replace"]),
                                       at(d, f)))


def r_broken_wrap(docs, out):
    """A word split across two lines in a B/L box ('HOT PO' / 'T', 'THAILAND, C' / 'Y')."""
    for d in docs:
        if d.kind != "BL":
            continue
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
                    out.append(Finding("WORD_WRAP", "MINOR", [d], {}, f"{last} / {frag}", last + frag,
                                       [Loc(d, a.page, s.bbox, None), Loc(d, b.page, t.bbox, None)]))


def r_documents(scs, cos, out):
    for s in scs:
        f = s.f.get("docs_required")
        req = f.value.upper() if f else ""
        ins_line = next((l for l in s.lines if "INSURANCE" in l.text.upper()), None)
        if s.lists.get("fob") and "INSURANCE" in req:
            out.append(Finding("SC_DOCS_INSURANCE", "WARNING", [s], {}, "Insurance Policy", "",
                               at_line(s, ins_line) if ins_line else []))
        if cos and not re.search(r"CERTIFICATE OF ORIGIN|\bORIGIN\b|FORM D", req):
            doc_line = next((l for l in s.lines if "DOCUMENTS REQUIRED" in l.text.upper()), None)
            out.append(Finding("SC_DOCS_FORMD", "INFO", [s], {}, "", "Form D",
                               at_line(s, doc_line) if doc_line else []))


def r_draft_status(docs, out):
    for d in docs:
        if d.kind in ("BL", "CO") and not d.is_draft:
            out.append(Finding("ISSUED_DOC", "INFO", [d], {}, "", "DRAFT"))


def validate(docs: list[Doc]) -> list[Finding]:
    by = lambda k: [d for d in docs if d.kind == k]
    ci = next(iter(by("CI")), None)
    bl = next(iter(by("BL")), None)
    co = next(iter(by("CO")), None)
    scs = by("SC")
    out: list[Finding] = []
    r_line_math(docs, out)
    r_pl_sums(docs, out)
    r_bl_vs_pl(ci, bl, out)
    r_incoterm(docs, ci, bl, out)
    r_po_coverage(scs, ci, out)
    r_sc_vs_ci(scs, ci, out)
    r_dates(scs, ci, co, out)
    r_vessel(ci, bl, co, out)
    r_co(ci, co, bl, out)
    r_hs(ci, co, bl, out)
    r_pl_ranges(ci, co, out)
    r_co_packages(ci, co, out)
    r_pod(docs, out)
    r_words(docs, out)
    r_text_fixes(docs, out)
    r_broken_wrap(docs, out)
    r_documents(scs, by("CO"), out)
    r_draft_status(docs, out)
    out.sort(key=lambda f: SEVERITY.index(f.severity))
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
        for n, it in enumerate(d.items + d.pl_items, 1):
            if not it.get("model") and d.kind in ("CI", "SC"):
                out.append(dict(doc=d.name, what=f"Model not found for goods line {n} (page {it['qty'].page + 1})",
                                vi=f"Không đọc được model của dòng hàng {n} (trang {it['qty'].page + 1})"))
        for lst in CONFIG["required_lists"].get(d.kind, []):
            if not getattr(d, lst):
                out.append(dict(doc=d.name, what=f"No line items found ({lst})",
                                vi=f"Không đọc được các dòng hàng ({lst})"))
    return out
