"""Cross-document ("net") and self-consistency rules, added in LDV 2.1 (report only).

Self-checks inside one document:
  CI_COVER_TOTAL, PL_COVER_TOTAL  cover-page TTL = attachment TTL (cartons, quantity, amount, N.W., G.W., CBM)
  PL_GW_NW                        gross weight >= net weight (each packing-list line and the total)
  ETA_DATE                        ETA not before the sailing date
  DOC_HEADER                      invoice no. / date identical on every page of the invoice + packing-list file
  CI_PO_LIST                      P/O list on the cover = P/O numbers on the lines
  CO_SUM, CO_NUMBERING, CO_PAGES  Form D items add up to its totals; items numbered 1..n; "Page n of m" right
Between documents:
  CI_PL_CTN                       invoice carton total = packing-list carton total
  LINE_COUNT, PL_LINE             invoice lines = packing-list lines (count, then model / quantity / P/O /
                                  description per line)
  CI_LINE_DESC                    invoice line description names another series than its model and the packing list
  CO_MODEL                        Form D item n model = invoice line n model
  MARKS_MISSING, CI_MARKS_MODEL   shipping marks list every invoice model / only invoice models
  ORIGIN, CO_IMPORT_COUNTRY       country of origin and importing country agree
  PARTY_NAME                      consignee / shipper names agree (legal-form spelling ignored)
  CURRENCY, PAYMENT_TERMS         same currency; same payment terms on invoice and contract
  SC_GOODS_DESC                   goods named on the contract = goods on the invoice
  PL_HEADER                       packing-list header = invoice header (consignee, vessel, ports, terms, P/O …)
  FREIGHT_TERM                    freight COLLECT / PREPAID agrees on invoice, packing list, B/L and with the Incoterm
Typos anywhere in the text (whether LDV reads that field or not):
  TEXT_TYPO                       a word that looks mistyped: a lowercase letter inside a capital word ('HAIPhONG'),
                                  a digit inside a word ('C0LLECT') or a letter inside a number ('2O26', '1,O43')
  VALUE_UNREADABLE                a value found at its label but not understood (e.g. the date '21-NOV-2O26')
  DATE_FAR                        a date more than 300 days from the invoice date (a mistyped year)

Where several documents state the same thing, the value most of them agree on is the reference and the document
that differs is blamed. Nothing is reported when a value was not read.
"""
import difflib
import re
from collections import Counter

from . import master
from .extract import NUMBER_WORDS, Field
from .rules import Finding, _close, at, fmt_like

ZIP = zip


def _num_fmt(v):
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _party(name: str) -> str:
    """Company name for comparison: legal forms and punctuation ignored (CO., LTD. = COMPANY LIMITED)."""
    n = (name or "").upper()
    n = re.sub(r"\bCOMPANY\b", "CO", n)
    n = re.sub(r"\bLIMITED\b", "LTD", n)
    n = re.sub(r"\bCORPORATION\b", "CORP", n)
    n = re.sub(r"\bPUBLIC\s+CO\b", "PCL", n)
    return re.sub(r"[^A-Z0-9]", "", n)


def _terms(t: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", re.sub(r"^\s*BY\s+", "", (t or "").upper()))


def _goods_words(t: str) -> set:
    """Words of a goods description: quotes, BRAND, AND, OF and plural S ignored ('ACME WASHING MACHINES' =
    '"ACME" BRAND WASHING MACHINE')."""
    words = re.sub(r"[^A-Z0-9 ]", " ", (t or "").upper()).split()
    return {w[:-1] if len(w) > 3 and w.endswith("S") and not w.endswith("SS") else w
            for w in words if w not in ("BRAND", "AND", "OF", "THE")}


def _odd_ones(entries: list, norm) -> tuple[list, str | None]:
    """entries = [(doc, Field)]. Returns ([(doc, Field)] that differ from the majority, majority raw value)."""
    have = [(d, f) for d, f in entries if f and str(f.value).strip()]
    if len(have) < 2:
        return [], None
    count = Counter(norm(f.value) for _, f in have)
    if len(count) == 1:
        return [], None
    (top, n1), (_, n2) = count.most_common(2)
    if n1 == n2:                                   # no majority: the first source (the reference document) wins
        top = norm(have[0][1].value)
    ref = next(f.value for _, f in have if norm(f.value) == top)
    return [(d, f) for d, f in have if norm(f.value) != top], ref


# ----------------------------------------------------------------------------- self-checks
def r_cover_totals(ci, out):
    if not ci:
        return
    for lst, key, keys in (("ci_ttls", "CI_COVER_TOTAL", ("ctn", "qty", "amount")),
                           ("pl_ttls", "PL_COVER_TOTAL", ("ctn", "qty", "nw", "gw", "cbm"))):
        rows = ci.lists.get(lst, [])
        if len(rows) < 2:
            continue
        ref = rows[-1]                             # the attachment's TTL: the one the line sums are checked against
        for row in rows[:-1]:
            for k in keys:
                a, b = row.get(k), ref.get(k)
                if a and b and not _close(a.value, b.value, 0.005):
                    out.append(Finding(key, "ERROR", [ci], dict(label=f"@{k}"), a.raw, fmt_like(b.value, a.raw),
                                       at(ci, a) + at(ci, b, "ref")))


def r_gw_nw(ci, out):
    if not ci:
        return
    rows = [(p.get("model") or "", p) for p in ci.pl_items] + [("TTL", {k: ci.f.get(f"pl_total_{k}") for k in ("nw", "gw")})]
    for model, p in rows:
        nw, gw = p.get("nw"), p.get("gw")
        if nw and gw and gw.value < nw.value - 0.0005:
            out.append(Finding("PL_GW_NW", "ERROR", [ci], dict(model=model, nw=nw.raw), gw.raw, f"≥ {nw.raw}",
                               at(ci, gw) + at(ci, nw, "ref")))


def r_eta(ci, out):
    if not ci:
        return
    eta, sail = ci.f.get("eta"), ci.f.get("sailing")
    if eta and sail and eta.value and sail.value and eta.value < sail.value:
        out.append(Finding("ETA_DATE", "ERROR", [ci], {}, f"{eta.value:%d/%m/%Y}", f"≥ {sail.value:%d/%m/%Y}",
                           at(ci, eta) + at(ci, sail, "ref")))


def r_headers(ci, out):
    if not ci:
        return
    heads = ci.lists.get("headers", [])
    for k, show in (("no", lambda v: v), ("date", lambda v: f"{v:%d/%m/%Y}")):
        odd, ref = _odd_ones([(ci, h[k]) for h in heads], lambda v: v)
        for _, f in odd:
            out.append(Finding("DOC_HEADER", "ERROR", [ci], dict(label=f"@hdr_{k}", page=f.page + 1), f.raw, show(ref),
                               at(ci, f)))


def r_cover_pos(ci, out):
    if not ci or not ci.lists.get("cover_pos"):
        return
    cover = ci.lists["cover_pos"][0]
    lines = {it.get("po") for it in ci.items if it.get("po")}
    if not lines:
        return
    missing, extra = sorted(lines - set(cover.value)), sorted(set(cover.value) - lines)
    if missing or extra:
        out.append(Finding("CI_PO_LIST", "WARNING", [ci], dict(missing=", ".join(missing) or "—", extra=", ".join(extra) or "—"),
                           ", ".join(cover.value), ", ".join(sorted(lines)), [_line_loc(ci, cover)]))


def r_co_self(co, out):
    """Form D items vs its own totals. Only reported when no other rule already explains the difference
    (CO_QTY / CO_PKG_COUNT blame the items, CO_TOTAL blames the total against the invoice / packing list)."""
    if not co or not co.items:
        return
    seen = {f.key for f in out if f.docs and f.docs[0] is co}
    tq = co.f.get("total_qty")
    s = sum(it["qty"].value for it in co.items)
    if tq and not _close(s, tq.value) and not seen & {"CO_QTY", "CO_TOTAL"}:
        out.append(Finding("CO_SUM", "ERROR", [co], dict(label="@total_qty"), tq.raw, _num_fmt(s),
                           at(co, tq) + [x for it in co.items for x in at(co, it["qty"], "ref")]))
    tc = co.f.get("total_ctn")
    figs = [it.get("pkg_fig") for it in co.items]
    if tc and all(figs) and not seen & {"CO_PKG_COUNT", "CO_TOTAL"}:
        s = sum(f.value for f in figs)
        if not _close(s, tc.value):
            out.append(Finding("CO_SUM", "ERROR", [co], dict(label="@ctn"), tc.raw, _num_fmt(s),
                               at(co, tc) + [x for f in figs for x in at(co, f, "ref")]))
    nos = [it["no"] for it in co.items]
    if nos != list(range(1, len(nos) + 1)):
        out.append(Finding("CO_NUMBERING", "MINOR", [co], {}, ",".join(map(str, nos)),
                           ",".join(str(i) for i in range(1, len(nos) + 1)),
                           [x for it, i in ZIP(co.items, range(1, len(nos) + 1)) if it["no"] != i
                            for x in at(co, it.get("hs_f"))]))
    pages = co.lists.get("pages", [])
    n_pages = max((l.page for l in co.lines), default=-1) + 1
    for i, pg in enumerate(sorted(pages, key=lambda p: p["f"].page)):
        want_n, want_of = pg["f"].page + 1, n_pages
        if (pg["n"], pg["of"]) != (want_n, want_of):
            out.append(Finding("CO_PAGES", "MINOR", [co], {}, pg["f"].raw, f"Page : {want_n} of {want_of}", at(co, pg["f"])))


# ----------------------------------------------------------------------------- between documents
def r_ci_pl_ctn(ci, out):
    if not ci or not ci.lists.get("ci_ttls"):
        return
    a, b = ci.lists["ci_ttls"][-1].get("ctn"), ci.f.get("pl_total_ctn")
    if a and b and not _close(a.value, b.value):
        out.append(Finding("CI_PL_CTN", "ERROR", [ci], {}, a.raw, fmt_like(b.value, a.raw), at(ci, a) + at(ci, b, "ref")))


def r_lines(ci, out):
    if not ci or not ci.items or not ci.pl_items:
        return
    if len(ci.items) != len(ci.pl_items):
        ref = ci.f.get("pl_total_qty") or ci.pl_items[-1]["qty"]
        out.append(Finding("LINE_COUNT", "ERROR", [ci], dict(have=len(ci.pl_items), want=len(ci.items)),
                           str(len(ci.pl_items)), str(len(ci.items)), at(ci, ref)))
        return
    for n, (a, p) in enumerate(ZIP(ci.items, ci.pl_items), 1):
        diffs = []
        if a.get("model") and p.get("model") and master.key(a["model"]) != master.key(p["model"]):
            diffs.append(("@model", p["model"], a["model"]))
        if not _close(a["qty"].value, p["qty"].value):
            diffs.append(("@qty", p["qty"].raw, fmt_like(a["qty"].value, p["qty"].raw)))
        if a.get("po") and p.get("po") and a["po"] != p["po"]:
            diffs.append(("@po", p["po"], a["po"]))
        da, dp = a.get("desc"), p.get("desc")                # '20L' vs '21L', '(AB12)' vs '(A812)'
        if da and dp and re.sub(r"\s+", "", da.value.upper()) != re.sub(r"\s+", "", dp.value.upper()):
            core = re.search(r"-([A-Z0-9\-]+)\(", a.get("model") or "")   # CD-Y20PE(BM)VN -> Y20PE
            if core and core[1] in dp.value.upper() and core[1] not in da.value.upper():
                # the packing list names the model's series, the invoice does not: the invoice is wrong
                out.append(Finding("CI_LINE_DESC", "ERROR", [ci], dict(no=a.get("no") or n, model=a["model"]),
                                   da.value, dp.value, at(ci, da) + at(ci, dp, "ref")))
            else:
                diffs.append(("@desc", dp.value, da.value))
        if diffs:
            out.append(Finding("PL_LINE", "ERROR", [ci], dict(no=a.get("no") or n, what=" / ".join(d[0] for d in diffs)),
                               "; ".join(d[1] for d in diffs), "; ".join(d[2] for d in diffs),
                               at(ci, p["qty"]) + at(ci, a["qty"], "ref")))


def r_co_model(ci, co, out):
    if not (ci and co) or len(co.items) != len(ci.items):
        return                                     # CO_ITEMS already reports a different number of items
    for it, a in ZIP(co.items, ci.items):
        m, ref = it.get("model"), a.get("model")
        if m and ref and master.key(m) != master.key(ref):
            out.append(Finding("CO_MODEL", "ERROR", [co, ci], dict(no=it["no"], model=m, ref=ref), m, ref,
                               at(co, it.get("hs_f")) + at(ci, a["qty"], "ref")))


def r_marks(ci, bl, co, out):
    if not ci:
        return
    models = sorted({it["model"] for it in ci.items if it.get("model")})
    if not models:
        return
    cover = ci.lists.get("marks_models", [])
    pl_marks = ci.lists.get("pl_marks_models", [])
    for key, lst in (("CI_MARKS_MODEL", cover), ("PL_MARKS_MODEL", pl_marks)):
        for f in lst:                              # the invoice's / packing list's own marks: a model not on the invoice
            if f.value not in models and f.value not in {p.get("model") for p in ci.pl_items}:
                near = difflib.get_close_matches(f.value, models, n=1, cutoff=0.75)
                out.append(Finding(key, "ERROR" if near else "WARNING", [ci], dict(model=f.value),
                                   f.value, near[0] if near else "", at(ci, f)))
    for d, lst in ((ci, cover), (bl, bl.lists.get("marks_models", []) if bl else []),
                   (co, co.lists.get("marks_models", []) if co else [])):
        if not d or not lst:
            continue                               # marks not written as model list (e.g. 'BRAND/ABCD'): nothing to check
        have = {master.key(f.value) for f in lst}
        typos = [f.value for f in lst if f.value not in models]          # reported as *_MARKS_MODEL already
        missing = [m for m in models if master.key(m) not in have
                   and not difflib.get_close_matches(m, typos, n=1, cutoff=0.75)]
        if missing:
            out.append(Finding("MARKS_MISSING", "WARNING", [d, ci], dict(models=", ".join(missing)),
                               ", ".join(f.value for f in lst), ", ".join(models), at(d, lst[-1])))


def r_origin(ci, scs, co, out, bl=None):
    entries = ([(co, f) for f in co.lists.get("origin", [])] if co else []) + \
              ([(ci, ci.f.get("origin"))] if ci else []) + [(s, s.f.get("origin")) for s in scs] + \
              ([(bl, bl.f.get("origin"))] if bl else [])          # B/L: 'MADE IN ...' in the marks
    odd, ref = _odd_ones(entries, lambda v: str(v).upper().strip())
    for d, f in odd:
        out.append(Finding("ORIGIN", "ERROR", [d], dict(origin=f.value, ref=ref.upper()), f.value, ref.upper(), at(d, f)))


def r_import_country(co, bl, out):
    if not (co and bl and bl.f.get("dest_country")):
        return
    dest = bl.f["dest_country"]
    for f in co.lists.get("import_country", []):
        if f.value.upper().strip() != dest.value.upper().strip():
            out.append(Finding("CO_IMPORT_COUNTRY", "ERROR", [co, bl], dict(country=f.value, ref=dest.value), f.value,
                               dest.value, at(co, f) + at(bl, dest, "ref")))


def r_parties(ci, scs, bl, co, out):
    # order = which document wins a tie: contract / invoice, then Form D (certified), the B/L (typed by the forwarder) last
    for role, entries in (
            ("@consignee", [(ci, ci.f.get("consignee") if ci else None)] + [(s, s.f.get("buyer")) for s in scs]
             + [(co, co.f.get("consignee") if co else None), (bl, bl.f.get("consignee") if bl else None)]),
            ("@shipper", [(s, s.f.get("seller")) for s in scs]
             + [(co, co.f.get("exporter") if co else None), (bl, bl.f.get("shipper") if bl else None)])):
        odd, ref = _odd_ones([(d, f) for d, f in entries if d], _party)
        for d, f in odd:
            out.append(Finding("PARTY_NAME", "WARNING", [d], dict(role=role, name=f.value, ref=ref), f.value, ref, at(d, f)))


def r_currency(ci, scs, co, out):
    per_doc = [(d, d.lists.get("currency", [])) for d in ([ci] + list(scs) + [co]) if d]
    per_doc = [(d, fs) for d, fs in per_doc if fs]
    codes = Counter(c for _, fs in per_doc for c in {f.value for f in fs})
    if len(codes) < 2:
        return
    top = codes.most_common(1)[0][0]
    for d, fs in per_doc:
        bad = [f for f in fs if f.value != top]
        if bad:
            out.append(Finding("CURRENCY", "ERROR", [d], dict(cur=bad[0].value, ref=top), bad[0].raw, top, at(d, bad[0])))


def r_payment(ci, scs, out):
    a = ci.f.get("payment") if ci else None
    for s in scs:
        b = s.f.get("payment")
        if a and b and _terms(a.value) != _terms(b.value):
            out.append(Finding("PAYMENT_TERMS", "WARNING", [ci, s], {}, a.value, re.sub(r"^\s*By\s+", "", b.value),
                               at(ci, a) + at(s, b, "ref")))


def r_sc_goods(ci, scs, out):
    """Goods named on the Sales Contract = goods on the invoice (one may name more products than the other)."""
    ref = ci.f.get("goods_full") or ci.f.get("goods") if ci else None
    if not ref:
        return
    want = _goods_words(ref.value)
    for sc in scs:
        g = sc.f.get("goods_full")
        have = _goods_words(g.value) if g else set()
        if have and not (have <= want or want <= have):
            out.append(Finding("SC_GOODS_DESC", "ERROR", [sc, ci], {}, g.value, ref.value, at(sc, g) + at(ci, ref, "ref")))


def _same_val(k: str, a, b) -> bool:
    if k in ("consignee", "shipper"):
        return _party(a) == _party(b)
    if k == "payment":
        return _terms(a) == _terms(b)
    if k == "goods_full":
        return _goods_words(a) == _goods_words(b)
    if k in ("pol", "pod", "origin", "incoterm", "freight"):
        n = lambda v: re.sub(r"[^A-Z]", "", str(v).upper())
        return n(a) == n(b)
    if k == "pos":
        return set(a or []) == set(b or [])
    return a == b


PL_LABELS = dict(consignee="@consignee", shipper="@shipper", vessel="@vessel", pol="@pol", pod="@pod",
                 sailing="@sailing", payment="@payment", origin="@origin", goods_full="@goods", pos="@po",
                 containers="@containers", incoterm="@incoterm", freight="@freight")


_ELSEWHERE = dict(consignee=(("SC", "buyer"), ("BL", "consignee"), ("CO", "consignee")),
                  shipper=(("SC", "seller"), ("BL", "shipper"), ("CO", "exporter")),
                  vessel=(("BL", "vessel"), ("CO", "vessel")), pol=(("BL", "pol"), ("SC", "fob_port")),
                  pod=(("BL", "pod"), ("CO", "pod")), sailing=(("CO", "departure"),), payment=(("SC", "payment"),),
                  origin=(("SC", "origin"), ("CO", "origin"), ("BL", "origin")),
                  goods_full=(("SC", "goods_full"), ("BL", "goods_full")), pos=(("SC", "pos"),),
                  containers=(("BL", "containers"),), incoterm=(("SC", "incoterm"),), freight=(("BL", "freight"),))


def r_pl_header(ci, others, out):
    """The packing list repeats the invoice header: consignee, shipper, vessel, ports, dates, terms, P/O … must be the
    same. (Invoice no. and date on every page: DOC_HEADER.) When the other documents agree with the packing list, the
    invoice is the odd one out and the cross-document rule (ORIGIN, PARTY_NAME, …) reports it instead."""
    if not ci:
        return
    from .extract_net import PL_HEADER
    for k in PL_HEADER:
        a, b = ci.f.get(k), ci.f.get("pl_" + k)
        if not (a and b and a.value not in (None, "", []) and b.value not in (None, "", [])) or _same_val(k, a.value, b.value):
            continue
        if any(d.kind == kind and d.f.get(fk) and _same_val(k, d.f[fk].value, b.value)
               for kind, fk in _ELSEWHERE.get(k, ()) for d in others):
            continue
        if True:
            show = lambda f: ", ".join(f.value) if isinstance(f.value, list) else (
                f"{f.value[0]} V.{f.value[1]}" if isinstance(f.value, tuple) else
                f"{f.value:%d/%m/%Y}" if hasattr(f.value, "strftime") else str(f.value))
            out.append(Finding("PL_HEADER", "ERROR", [ci], dict(label=PL_LABELS[k]), show(b), show(a),
                               at(ci, b) + at(ci, a, "ref")))


_COLLECT = ("EXW", "FCA", "FAS", "FOB")             # buyer pays the main freight
_PREPAID = ("CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")


def r_freight(ci, bl, out):
    """Freight COLLECT / PREPAID on invoice, packing list and B/L agree with each other and with the Incoterm."""
    inco = (ci.f.get("incoterm") if ci else None)
    term = inco.value.split()[0] if inco else None
    want = "COLLECT" if term in _COLLECT else "PREPAID" if term in _PREPAID else None
    entries = [(d, d.f.get(k)) for d, k in ((ci, "freight"), (ci, "pl_freight"), (bl, "freight")) if d and d.f.get(k)]
    if not entries:
        return
    if not want:
        odd, ref = _odd_ones(entries, lambda v: str(v).upper())
        want = ref.upper() if odd and ref else None
    for d, f in entries:
        if want and f.value.upper() != want:
            out.append(Finding("FREIGHT_TERM", "ERROR", [d], dict(term=term or want, want=want), f"FREIGHT {f.value}",
                               f"FREIGHT {want}", at(d, f) + (at(ci, inco, "ref") if inco else [])))


def _line_loc(doc, f: Field):
    from .rules import Loc
    return Loc(doc, f.line.page, f.line.bbox, None)


_LOOK_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B"}       # digit written for a letter
_LOOK_DIGIT = {"O": "0", "I": "1", "l": "1", "S": "5", "B": "8"}  # letter written for a digit


def typo_words(text: str, vocab=frozenset()):
    """(start, end, word, kind, suggestion) for every word of text that looks mistyped. Made to stay quiet on real
    documents: codes mix letters and digits freely (ACME2611E001, Y20PE, 40HC, (S1)), so a word counts only when
    it is all letters but one digit, or all digits but one letter, or has a lowercase letter among capitals.
    vocab: the words of the whole package. A short or doubtful word ('PC5', 'TW0', 'LA1') counts only when
    its corrected form is written elsewhere in the package (PCS, TWO, LAI), so a product code is left alone.
    Not caught: a two-letter word in Title case ('Hp' for 'HP'): 'By', 'No.' are written that way on purpose."""
    for m in re.finditer(r"[A-Za-z0-9]+", text):
        w = m[0]
        up, lo, dg = (sum(c.isupper() for c in w), sum(c.islower() for c in w), sum(c.isdigit() for c in w))
        al = up + lo
        to_letter = re.sub(r"[0158]", lambda c: _LOOK_LETTER[c[0]], w)
        if (lo and (up >= 2 or re.search(r"[a-z][A-Z]", w) or (up and dg and not re.fullmatch(r"\d+[A-Z][a-z]+", w)))
                and not re.fullmatch(r"(?:[A-Z][a-z]+)+", w)                          # VietNam, McKay: CamelCase
                and not re.fullmatch(r"[A-Z]{2,}s", w)                                # PCs, CTNs
                and not re.fullmatch(r"(?:\d+x)+\d*[A-Z0-9']*", w)):                  # 1x40HQ
            yield m.start(), m.end(), w, "case", w.upper()                           # HAIPhONG, SEtS, xX10, 40hC
        elif dg == 1 and al >= 2 and re.search(r"[A-Za-z][0158][A-Za-z]", w) and (al >= 4 or to_letter in vocab):
            yield m.start(), m.end(), w, "letter", to_letter                         # C0LLECT, HAIPH0NG, M1NH, U5D
        elif dg == 1 and re.fullmatch(r"[0158][A-Z]{2,}", w) and (al >= 5 or to_letter in vocab):
            yield m.start(), m.end(), w, "letter", to_letter                         # 1NDUSTRIES, 5EVEN, 0VEN
        elif dg == 1 and re.fullmatch(r"[A-Z]{2,}[0158]", w) and to_letter in vocab \
                and not re.match(r"-\d", text[m.end():]):                            # PC5, TW0, LA1 (not CARTON1-25)
            yield m.start(), m.end(), w, "letter", to_letter
        elif re.fullmatch(r"\d+[a-z]{1,2}", w) and not re.fullmatch(r"\d*(?:1st|2nd|3rd|[04-9]th|1[1-3]th)", w) \
                and text[max(0, m.start() - 12):m.start()].upper() == text[max(0, m.start() - 12):m.start()]:
            yield m.start(), m.end(), w, "case", w.upper()                           # 20l (20L), V.74n (not 17th)
        elif dg >= 2 and al == 1 and re.fullmatch(r"[0-9OIlSB]+", w):               # 2O26, I053, 10S3
            yield m.start(), m.end(), w, "digit", re.sub(r"[OIlSB]", lambda c: _LOOK_DIGIT[c[0]], w)
        elif dg >= 6 and re.search(r"\d[OIl]\d", w):                                # AC00O000000001 (a P/O no.)
            yield m.start(), m.end(), w, "digit", re.sub(r"(?<=\d)[OIl](?=\d)", lambda c: _LOOK_DIGIT[c[0]], w)
    yield from _typo_contexts(text)


_PKG = r"(?:CARTON|CASE|PALLET|PACKAGE|BOX|CONTAINER|SET|PCS|PIECE)"
_CNTR_TYPES = r"(?:HC|HQ|GP|DC|RF|OT|FR)"


def _typo_contexts(text: str):
    """Typos a word alone does not show, but its place does: a figure in brackets before a package word, a carton
    range, a page number, a container size, an abbreviation."""
    d2 = lambda t: re.sub(r"[OIlSB]", lambda c: _LOOK_DIGIT[c[0]], t)
    pats = [  # (regex, group, kind, fix)
        (r"(?:\b(?:" + "|".join(sorted(NUMBER_WORDS)) + r")\s*)?\(\s*([0-9OIlSB,]*[OIlSB][0-9OIlSB,]*)\s*\)\s*" + _PKG,
         1, "digit", d2),                                                     # (2S) CARTON, ONE (I) CONTAINER
        (_PKG + r"\(([0-9])\)", 1, "letter", lambda t: "S"),                  # CARTON(5)
        (r"\bCARTONS?\s*([0-9OIlSB]*[OIlSB][0-9OIlSB]*)\s*-\s*[0-9OIlSB]+", 1, "digit", d2),   # CARTON I-1043
        (r"\bCARTONS?\s*\d+\s*-\s*([0-9OIlSB]*[OIlSB][0-9OIlSB]*)\b", 1, "digit", d2),       # CARTON 1-1O43
        (r"\bPage\s*:\s*([0-9OIlSB]*[OIlSB][0-9OIlSB]*)\s+of\b", 1, "digit", d2),          # Page : I of 2
        (r"\bPage\s*:\s*\d+\s+of\s+([0-9OIlSB]*[OIlSB][0-9OIlSB]*)\b", 1, "digit", d2),
        (r"(?:\b|(?<=\d[Xx]))(?:\d+\s*[Xx]\s*)?([0-9OIlSB]*[OIlSB][0-9OIlSB]*)\s*'?\s*" + _CNTR_TYPES + r"\b", 1,
         "digit", d2),                                                         # 4OHC, 1x4OHQ
        (r"(?:\b|(?<=\d[Xx]))(?!(?:20|40|45)(?!\d))(\d{2})\s*'?\s*" + _CNTR_TYPES + r"\b", 1, "size",
         lambda t: {"2": "20", "4": "40"}.get(t[0], "40")),                  # 1x41HQ: no 41-foot container
        (r"\b\d+\s*X?\s*\d{2}\s*'?\s*((?i:hc|hq|gp|dc|rf|ot|fr))\b", 1, "case", str.upper),   # 40'Hc
        (r"\b[A-Z]\.([0158])(?=\.|\s+[A-Za-z])", 1, "letter", lambda t: _LOOK_LETTER[t]),  # U.5. / U.5 Dollars
        (r"(?<![A-Za-z0-9])((?=[0-9OIlSB/]*[OIlSB])(?=[0-9OIlSB/]*\d)[0-9OIlSB]{1,2}/[0-9OIlSB]{1,2}/[0-9OIlSB]{4})(?![A-Za-z0-9])",
         1, "digit", d2),                                                     # I2/11/2026, 12/11/2O26
        (r"\d[.,]([0-9OIlSB]*[OIlSB][0-9OIlSB]*)\b", 1, "digit", d2),          # 36.O0, 11,633.6O
        (r"\b([0-9OIlSB]*[OIlSB][0-9OIlSB]*)[.,]\d", 1, "digit", d2),          # 1O,727.60
        (r"(?i:\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?)\s+([0-9OIlSB]*[OIlSB][0-9OIlSB]*)\b",
         1, "digit", d2),                                                     # November I0, 2026
        (r"\b([0-9OIlSB]*[OIlSB][0-9OIlSB]*)[\s\-]+(?i:(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*)\b",
         1, "digit", d2),                                                     # I5-NOV-2026
    ]
    for rx, g, kind, fix in pats:
        for m in re.finditer(rx, text):
            t = m[g]
            if (rx is pats[0][0] and not re.search(r"\d", t)
                    and not re.search(r"\b(?:" + "|".join(NUMBER_WORDS) + r")\s*\($", text[:m.start(g)])):
                continue                      # '(S)' alone is a plural; '(I)' counts only after a number word
            if kind == "case" and t.isupper():
                continue
            yield m.start(g), m.end(g), t, kind, fix(t)


def _reported(out, d, page, text):
    """Some earlier finding already shows this text as the wrong value, on this page of d (CI_MARKS_MODEL for
    'AB-xX10(W1)VN'). A finding that only boxes the same line for another reason does not count."""
    rx = re.compile(r"(?<![A-Za-z0-9])" + re.escape(text) + r"(?![A-Za-z0-9])")      # 'I' is not inside 'INVOICE'
    return any(rx.search(str(f.current)) and any(l.doc is d and l.role == "wrong" and l.page in (page, None)
                                                 for l in f.locs) for f in out)


def r_text_typo(docs, out):
    """A mistyped word anywhere in a document: this does not depend on LDV reading that field, so a typo in a value
    LDV does not compare (or cannot read because of the typo) is still shown."""
    vocab = frozenset(w.upper() for d in docs for l in d.lines for w in re.findall(r"[A-Za-z0-9]+", l.text)
                      if not re.search(r"[a-z]", w) or w.isupper()) | NUMBER_WORDS | {"PCS", "SETS", "SET", "CARTONS"}
    found = {}
    for d in docs:
        for l in d.lines:
            for a, b, w, kind, fix in typo_words(l.text, vocab):
                if any(x < b and a < y for x, y in found.get(id(l), [])) or _reported(out, d, l.page, w):
                    continue                        # the same place found by a word rule and a context rule: once
                found.setdefault(id(l), []).append((a, b))
                out.append(Finding("TEXT_TYPO", "WARNING", [d], dict(word=w, kind=f"@typo_{kind}"), w, fix,
                                   at(d, Field(w, w, l, a, b))))


def _fields(obj):
    if isinstance(obj, Field):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _fields(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _fields(v)


def r_unreadable(docs, out):
    """A value found at its label but not understood (value None): reported, never silently left out."""
    for d in docs:
        seen = set()
        for f in _fields([d.f, d.lists, d.items, d.pl_items]):
            if f.value is not None or not str(f.raw or "").strip():
                continue
            key = (f.page, round(f.line.y, 1), f.start, f.raw)
            if key in seen or _reported(out, d, f.page, f.raw) or any(
                    _reported(out, d, f.page, w) for _a, _b, w, _k, _x in typo_words(f.raw)):
                continue
            seen.add(key)
            out.append(Finding("VALUE_UNREADABLE", "WARNING", [d], dict(value=f.raw.strip()), f.raw.strip(), "",
                               at(d, f)))


DATE_FAR_DAYS = 300


def r_date_far(docs, ci, out):
    """Every date read in the package lies within DATE_FAR_DAYS of the invoice date: '17/11/3026' or '2025' for
    '2026' is a typo that no other rule would see when the date is not compared with another document."""
    ref_f = ci.f.get("invoice_date") if ci else None
    ref = ref_f.value if ref_f and hasattr(ref_f.value, "year") else None
    if not ref:
        return
    seen = set()
    for d in docs:
        for f in _fields([d.f, d.lists, d.items, d.pl_items]):
            v = f.value
            if not (hasattr(v, "year") and not hasattr(v, "hour")) or abs((v - ref).days) <= DATE_FAR_DAYS:
                continue
            key = (d.name, f.page, f.raw)
            if key in seen or _reported(out, d, f.page, f.raw):
                continue
            seen.add(key)
            out.append(Finding("DATE_FAR", "WARNING", [d], dict(date=f.raw.strip(), days=f"{abs((v - ref).days):,}",
                                                                ref=f"{ref:%d/%m/%Y}"),
                               f.raw.strip(), "", at(d, f) + at(ci, ref_f, "ref")))


def validate_net(docs, ci, bl, co, scs, out):
    r_cover_totals(ci, out)
    r_gw_nw(ci, out)
    r_eta(ci, out)
    r_headers(ci, out)
    r_cover_pos(ci, out)
    r_co_self(co, out)
    r_ci_pl_ctn(ci, out)
    r_lines(ci, out)
    r_co_model(ci, co, out)
    r_marks(ci, bl, co, out)
    r_origin(ci, scs, co, out, bl)
    r_import_country(co, bl, out)
    r_parties(ci, scs, bl, co, out)
    r_currency(ci, scs, co, out)
    r_payment(ci, scs, out)
    r_sc_goods(ci, scs, out)
    r_pl_header(ci, [d for d in docs if d is not ci], out)
    r_freight(ci, bl, out)
    r_date_far(docs, ci, out)
    r_text_typo(docs, out)                          # last: an earlier finding on the same text comes first
    r_unreadable(docs, out)
