"""Cross-document ("net") and self-consistency rules, added in LDV 2.1 (report only).

Self-checks inside one document:
  CI_COVER_TOTAL, PL_COVER_TOTAL  cover-page TTL = what the item lines add up to (else the attachment TTL) (cartons, quantity, amount, N.W., G.W., CBM)
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
from .checks import begin, has_text, status_of
from .extract import NUMBER_WORDS, Field
from .rules import Finding, _call, _close, _v, at, fmt_like, true_total

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


def _sources(ck, entries):
    """Inputs of a "same value on every document" check. entries = [(doc, field name, Field | None)].
    Two or more values read: compared (a document whose value was not read is recorded as missing, so the check
    cannot PASS for it). Fewer: NOT_RUN(too_few_values) when another document prints it, NOT_APPLICABLE when every
    other document is known not to print it (reader 'absent' list)."""
    read, unread = 0, 0
    for d, name, f in entries:
        if d is None:
            continue
        if f is not None and str(f.value).strip():
            ck._input(d, name, "READ")
            read += 1
            continue
        st = status_of(d, name) if not name.startswith("lists.") else "NOT_FOUND"
        if st == "ABSENT":
            ck.inputs.append(dict(doc=d.name, kind=d.kind, name=name, status=st))
        else:
            ck._input(d, name, st)
            unread += 1
    if read >= 2:
        ck.compared()
    elif unread:
        ck.not_run("too_few_values", n=read)
    else:
        ck.na(evidence="fewer_than_two_sources")


# ----------------------------------------------------------------------------- self-checks
def _ttl_row(text: str, n: int) -> bool:
    """A printed totals row: starts with TTL / TOTAL and holds at least n figures ('TOTAL PACKED IN … (500) CARTONS'
    is a sentence, not a totals row)."""
    return bool(re.match(r"\s*(?:TTL|TOTAL)\b", text, re.I)) and len(re.findall(r"\d[\d,]*(?:\.\d+)?", text)) >= n


def r_cover_totals(ci, out):
    if not ci:
        return
    L = ci.lines
    pl_start = next((i for i, l in enumerate(L) if "PACKING LIST" in l.text.upper()), len(L))
    parts = dict(ci_ttls=L[:pl_start], pl_ttls=L[pl_start:])
    for lst, key, keys in (("ci_ttls", "CI_COVER_TOTAL", ("ctn", "qty", "amount")),
                           ("pl_ttls", "PL_COVER_TOTAL", ("ctn", "qty", "nw", "gw", "cbm"))):
        ck = begin(key, out, ci)
        rows = ci.lists.get(lst, [])
        if len(rows) < 2:
            n_ttl = sum(_ttl_row(l.text, 2 if lst == "ci_ttls" else 3) for l in parts[lst])
            if n_ttl < 2:                          # no cover page repeating the totals: nothing to compare
                ck.na(evidence="not_printed", field=f"lists.{lst}", doc=ci.name)
            else:                                  # printed twice, read fewer times
                ck._input(ci, f"lists.{lst}", "NOT_FOUND")
            ck.end()
            continue
        ck._input(ci, f"lists.{lst}", "READ")
        last = rows[-1]                            # the attachment's TTL: checked against the lines by PL_TOTAL & co.
        # every other TTL row against what the lines add up to, not against the attachment's printed TTL
        calc = {k: true_total(ci, {"qty": "qty" if lst == "ci_ttls" else "pl_qty"}.get(k, k)) for k in keys}
        for row in rows[:-1]:
            for k in keys:
                a, b = row.get(k), calc[k] or last.get(k)
                if a and b:
                    ck.compared()
                if a and b and not _close(a.value, b.value, 0.005):
                    ck.add(Finding(key, "ERROR", [ci], dict(label=f"@{k}"), a.raw, fmt_like(b.value, a.raw),
                                   at(ci, a) + at(ci, b, "ref")))
        ck.end()


def r_gw_nw(ci, out):
    if not ci:
        return
    ck = begin("PL_GW_NW", out, ci)
    ck.need_items(ci, "pl_items")
    ck.need(ci, "pl_total_nw")
    ck.need(ci, "pl_total_gw")
    from .rules import _units
    units = _units(ci) if ci.packages else [dict(p, label=p.get("model") or "") for p in ci.pl_items]
    rows = [(u["label"], u) for u in units] + [("TTL", {k: ci.f.get(f"pl_total_{k}") for k in ("nw", "gw")})]
    for model, p in rows:
        nw, gw = p.get("nw"), p.get("gw")
        if model != "TTL" or p is not rows[-1][1]:
            for k in ("nw", "gw"):
                if not p.get(k):
                    ck._input(ci, f"pl_items[{k}]", "NOT_FOUND")
        if nw and gw:
            ck.compared()
        if nw and gw and gw.value < nw.value - 0.0005:
            ck.add(Finding("PL_GW_NW", "ERROR", [ci], dict(model=model, nw=nw.raw), gw.raw, f"≥ {nw.raw}",
                           at(ci, gw) + at(ci, nw, "ref")))
    ck.end()


def r_eta(ci, out):
    if not ci:
        return
    ck = begin("ETA_DATE", out, ci)
    eta, sail = ci.f.get("eta"), ci.f.get("sailing")
    if ck.need(ci, "eta", trace=r"\bETA\b"):
        ck.need(ci, "sailing")
    if eta and sail and eta.value and sail.value:
        ck.compared()
    if eta and sail and eta.value and sail.value and eta.value < sail.value:
        ck.add(Finding("ETA_DATE", "ERROR", [ci], {}, f"{eta.value:%d/%m/%Y}", f"≥ {sail.value:%d/%m/%Y}",
                       at(ci, eta) + at(ci, sail, "ref")))
    ck.end()


def r_headers(ci, out):
    if not ci:
        return
    ck = begin("DOC_HEADER", out, ci)
    heads = ci.lists.get("headers", [])
    n_trace = sum(bool(re.search(r"(?i)INVOICE\s*NO", l.text)) for l in ci.lines)   # one header line per page
    if len(heads) >= 2:
        ck.compared()
        ck._input(ci, "lists.headers", "READ")
        if len(heads) < n_trace:                   # some page headers were not read
            ck._input(ci, "lists.headers", "NOT_FOUND")
    elif n_trace < 2:
        ck.na(evidence="not_printed", field="lists.headers", doc=ci.name)
    else:
        ck._input(ci, "lists.headers", "NOT_FOUND")
    for k, show in (("no", lambda v: v), ("date", lambda v: f"{v:%d/%m/%Y}")):
        odd, ref = _odd_ones([(ci, h[k]) for h in heads], lambda v: v)
        for _, f in odd:
            ck.add(Finding("DOC_HEADER", "ERROR", [ci], dict(label=f"@hdr_{k}", page=f.page + 1), f.raw, show(ref),
                           at(ci, f)))
    ck.end()


def r_cover_pos(ci, out):
    if not ci:
        return
    ck = begin("CI_PO_LIST", out, ci)
    if not ci.lists.get("cover_pos"):                   # a P/O list line without a line number: 'P/O NO.A, B'
        ck.need_list(ci, "cover_pos", trace=r"(?m)^\s*P/O NO")
        ck.end()
        return
    ck.need_list(ci, "cover_pos")
    cover = ci.lists["cover_pos"][0]
    lines = {it.get("po") for it in ci.items if it.get("po")}
    if not lines:
        for it in ci.items or [{}]:
            ck.need_item(ci, it, "po")
        ck.end()
        return
    ck.compared()
    missing, extra = sorted(lines - set(cover.value)), sorted(set(cover.value) - lines)
    if missing or extra:
        ck.add(Finding("CI_PO_LIST", "WARNING", [ci], dict(missing=", ".join(missing) or "—", extra=", ".join(extra) or "—"),
                       ", ".join(cover.value), ", ".join(sorted(lines)), [_line_loc(ci, cover)]))
    ck.end()


def r_co_self(co, out):
    """Form D items vs its own totals. Only reported when no other rule already explains the difference
    (CO_QTY / CO_PKG_COUNT blame the items, CO_TOTAL blames the total against the invoice / packing list)."""
    if not co:
        return
    cks = [begin(c, out, co) for c in ("CO_SUM", "CO_NUMBERING", "CO_PAGES")]
    if not co.items:
        for ck in cks:
            ck.need_items(co)
            ck.end()
        return
    ck_s, ck_n, ck_p = cks
    seen = {f.key for f in out if f.docs and f.docs[0] is co}
    tq = co.f.get("total_qty")
    s = sum(it["qty"].value for it in co.items)
    ck_s.need(co, "total_qty", absent_ok=getattr(co, "form", "D") == "E")   # Form E prints no quantity total
    if tq and seen & {"CO_QTY", "CO_TOTAL"} and not _close(s, tq.value):
        ck_s.blocked("CO_QTY / CO_TOTAL")         # the difference is already reported there
    elif tq:
        ck_s.compared()                            # items add up to the Form D's own TOTAL: a pass even if both are wrong
    if tq and not _close(s, tq.value) and not seen & {"CO_QTY", "CO_TOTAL"}:
        ck_s.add(Finding("CO_SUM", "ERROR", [co], dict(label="@total_qty"), tq.raw, _num_fmt(s),
                         at(co, tq) + [x for it in co.items for x in at(co, it["qty"], "ref")]))
    tc = co.f.get("total_ctn")
    figs = [it.get("pkg_fig") for it in co.items]
    if tc and all(figs) and not seen & {"CO_PKG_COUNT", "CO_TOTAL"}:
        ck_s.compared()
        s = sum(f.value for f in figs)
        if not _close(s, tc.value):
            ck_s.add(Finding("CO_SUM", "ERROR", [co], dict(label="@ctn"), tc.raw, _num_fmt(s),
                             at(co, tc) + [x for f in figs for x in at(co, f, "ref")]))
    ck_s.end()
    nos = [it["no"] for it in co.items]
    ck_n.compared()
    if nos != list(range(1, len(nos) + 1)):
        ck_n.add(Finding("CO_NUMBERING", "MINOR", [co], {}, ",".join(map(str, nos)),
                         ",".join(str(i) for i in range(1, len(nos) + 1)),
                         [x for it, i in ZIP(co.items, range(1, len(nos) + 1)) if it["no"] != i
                          for x in at(co, it.get("hs_f"))]))
    ck_n.end()
    pages = co.lists.get("pages", [])
    ck_p.need_list(co, "pages", trace=r"(?i)Page\s*:?\s*\d+\s*of")
    n_pages = max((l.page for l in co.lines), default=-1) + 1
    for i, pg in enumerate(sorted(pages, key=lambda p: p["f"].page)):
        ck_p.compared()
        want_n, want_of = pg["f"].page + 1, n_pages
        if (pg["n"], pg["of"]) != (want_n, want_of):
            ck_p.add(Finding("CO_PAGES", "MINOR", [co], {}, pg["f"].raw, f"Page : {want_n} of {want_of}", at(co, pg["f"])))
    if pages and getattr(co, "form", "D") == "E":    # every page carries '(PAGE n OF m)': one not read is mistyped
        from .rules import Loc
        have = {pg["f"].page for pg in pages}
        for p in range(n_pages):
            if p not in have:
                ck_p.compared()
                ck_p.add(Finding("CO_PAGES", "MINOR", [co], {}, "", f"(PAGE {p + 1} OF {n_pages})",
                                 [Loc(co, p, None, "PAGE")]))
    ck_p.end()


# ----------------------------------------------------------------------------- between documents
def r_ci_pl_ctn(ci, out):
    if not ci:
        return
    ck = begin("CI_PL_CTN", out, ci)
    if not ci.lists.get("ci_ttls"):
        L = ci.lines
        pl_start = next((i for i, l in enumerate(L) if "PACKING LIST" in l.text.upper()), len(L))
        if getattr(ci, "pl_page", None) is not None:   # an Excel workbook: the packing list is its own sheet
            pl_start = next((i for i, l in enumerate(L) if l.page >= ci.pl_page), len(L))
        if any(re.match(r"\s*(?:TTL|TOTAL)\b(?!\s+AMOUNT)", l.text, re.I) for l in L[:pl_start]):
            ck._input(ci, "lists.ci_ttls", "NOT_FOUND")
        else:
            ck.na(evidence="not_printed", field="lists.ci_ttls", doc=ci.name)
        ck.end()
        return
    ck._input(ci, "lists.ci_ttls", "READ")
    last = ci.lists["ci_ttls"][-1]
    a, b = last.get("ctn"), true_total(ci, "ctn")
    if not a:                                      # the invoice TTL row prints no carton count: nothing to compare
        row = next((x.line.text for x in last.values()), "")
        if re.search(r"(?i)CARTON", row):
            ck._input(ci, "lists.ci_ttls", "NOT_FOUND")
        else:
            ck.na(evidence="not_printed", field="ci_ttls.ctn", doc=ci.name)
    ck.need_total_val(ci, "ctn", b)
    if a and b:
        ck.compared()
    if a and b and not _close(a.value, b.value):
        ck.add(Finding("CI_PL_CTN", "ERROR", [ci], {}, a.raw, fmt_like(b.value, a.raw), at(ci, a) + at(ci, b, "ref")))
    ck.end()


def split_by_container(ci) -> bool:
    """The packing list is written container by container (a container number starts its rows)."""
    return bool(ci and ci.lists.get("pl_containers"))


def model_qty(rows) -> dict:
    """{model key: (total quantity, [rows])}."""
    out = {}
    for it in rows:
        if not it.get("model") or _v(it.get("qty")) is None:
            continue
        k = master.key(it["model"])
        q, rs = out.get(k, (0.0, []))
        out[k] = (q + it["qty"].value, rs + [it])
    return out


def r_lines(ci, out):
    if not ci:
        return
    ck = begin("LINES", out, ci)
    ck.need_items(ci)
    ck.need_items(ci, "pl_items")
    if not ci.items or not ci.pl_items:
        ck.end()
        return
    ck.compared()
    same_lines = len(ci.items) == len(ci.pl_items) and all(
        a.get("model") and p.get("model") and master.key(a["model"]) == master.key(p["model"])
        and _close(a["qty"].value, p["qty"].value) for a, p in zip(ci.items, ci.pl_items))
    if split_by_container(ci) and not same_lines:
        # a packing list by container: one invoice line may be loaded into several containers, and one container
        # holds several lines. Line by line means nothing here; every model's quantity must add up the same.
        inv, pl = model_qty(ci.items), model_qty(ci.pl_items)
        for k in sorted(set(inv) | set(pl)):
            a, b = inv.get(k), pl.get(k)
            if a and b and _close(a[0], b[0]):
                continue
            locs = [x for it in (b[1] if b else []) for x in at(ci, it["qty"])]
            locs += [x for it in (a[1] if a else []) for x in at(ci, it["qty"], "ref")]
            name = (a or b)[1][0]["model"]
            ck.add(Finding("PL_MODEL_QTY", "ERROR", [ci], dict(model=name), f"{b[0]:,.0f}" if b else "0",
                           f"{a[0]:,.0f}" if a else "0", locs))
        ck.end()
        return
    if len(ci.items) != len(ci.pl_items):
        ref = ci.f.get("pl_total_qty") or ci.pl_items[-1]["qty"]
        ck.add(Finding("LINE_COUNT", "ERROR", [ci], dict(have=len(ci.pl_items), want=len(ci.items)),
                       str(len(ci.pl_items)), str(len(ci.items)), at(ci, ref)))
        ck.end()
        return
    for n, (a, p) in enumerate(ZIP(ci.items, ci.pl_items), 1):
        diffs = []
        if a.get("model") and p.get("model") and master.key(a["model"]) != master.key(p["model"]):
            diffs.append(("@model", p["model"], a["model"]))
        if not _close(a["qty"].value, p["qty"].value):
            diffs.append(("@qty", p["qty"].raw, fmt_like(a["qty"].value, p["qty"].raw)))
        ia = ci.item_ids[n - 1] if len(ci.item_ids) == len(ci.items) else None
        ip = ci.pl_item_ids[n - 1] if len(ci.pl_item_ids) == len(ci.pl_items) else None
        if (ia and ip and ia.kind == ip.kind == "part_no" and ia.value != ip.value):
            diffs.append(("@model", ip.value, ia.value))   # part numbers of the same line differ
        if a.get("po") and p.get("po") and a["po"] != p["po"]:
            diffs.append(("@po", p["po"], a["po"]))
        da, dp = a.get("desc"), p.get("desc")                # '20L' vs '21L', '(AB12)' vs '(A812)'
        if da and dp and re.sub(r"\s+", "", da.value.upper()) != re.sub(r"\s+", "", dp.value.upper()):
            core = re.search(r"-([A-Z0-9\-]+)\(", a.get("model") or "")   # CD-Y20PE(BM)VN -> Y20PE
            if core and core[1] in dp.value.upper() and core[1] not in da.value.upper():
                # the packing list names the model's series, the invoice does not: the invoice is wrong
                ck.add(Finding("CI_LINE_DESC", "ERROR", [ci], dict(no=a.get("no") or n, model=a["model"]),
                               da.value, dp.value, at(ci, da) + at(ci, dp, "ref")))
            else:
                diffs.append(("@desc", dp.value, da.value))
        if diffs:
            ck.add(Finding("PL_LINE", "ERROR", [ci], dict(no=a.get("no") or n, what=" / ".join(d[0] for d in diffs)),
                           "; ".join(d[1] for d in diffs), "; ".join(d[2] for d in diffs),
                           at(ci, p["qty"]) + at(ci, a["qty"], "ref")))
    ck.end()


_CRITERIA = re.compile(r'^(?:WO|PE|CTH|CTSH|CC|PSR|DE\s*MINIMIS|ACU|\d{1,3}(?:\.\d+)?\s*%)$')


def r_co_values(ci, co, out):
    """Form E box 9: an item printing its FOB value (RVC criterion) prints the invoice line's amount; box 8: the
    origin criterion is one of the known codes ('"PE"', '"WO"', '"CTH"', '40%' …)."""
    if not co:
        return
    if getattr(co, "form", "D") != "E":            # Form D box 9: quantity only is normal (owner, 2026-11-17)
        for cid in (("CO_ITEM_VALUE", "CO_CRITERION") if ci else ("CO_CRITERION",)):
            ck = begin(cid, out, co) if cid == "CO_CRITERION" else begin(cid, out)
            ck.na(evidence="form_e_only")
            ck.end()
        return
    ck = begin("CO_ITEM_VALUE", out) if ci else None
    vals = [it for it in co.items if it.get("fob")]
    if ck is None:
        pass
    elif not vals:
        ck.na(evidence="not_printed", field="items[fob]", doc=co.name)
    elif len(co.items) != len(ci.items):
        ck.blocked("CO_ITEMS")
    else:
        for it, a in zip(co.items, ci.items):
            if not it.get("fob") or not a.get("amount"):
                continue
            ck.compared()
            if not _close(it["fob"].value, a["amount"].value):
                ck.add(Finding("CO_ITEM_VALUE", "ERROR", [co, ci], dict(no=it["no"]), it["fob"].raw,
                               fmt_like(a["amount"].value, it["fob"].raw), at(co, it["fob"]) + at(ci, a["amount"], "ref")))
    if ck is not None:
        ck.end()
    ck = begin("CO_CRITERION", out, co)
    for it in co.items:
        c = it.get("criterion")
        if not c:
            continue
        ck.compared()
        if not _CRITERIA.match(c.value.strip().upper()) or c.value.strip() != c.value.strip().upper():
            ck.add(Finding("CO_CRITERION", "WARNING", [co], dict(no=it["no"], crit=c.value), c.raw,
                           c.value.strip().upper(), at(co, c)))
    if not ck.n_compared:
        ck.na(evidence="not_printed", field="items[criterion]", doc=co.name)
    ck.end()


def r_co_model(ci, co, out):
    if not (ci and co):
        return
    ck = begin("CO_MODEL", out)
    ck.need_items(co)
    ck.need_items(ci)
    if len(co.items) != len(ci.items):
        ck.blocked("CO_ITEMS")                     # the item table is wrong as a whole: CO_ITEMS reports it
        ck.end()
        return
    for it, a in ZIP(co.items, ci.items):
        m, ref = it.get("model"), a.get("model")
        ck.need_item(co, it, "model")
        ck.need_item(ci, a, "model")
        if m and ref:
            ck.compared()
        if m and ref and (master.key(m) != master.key(ref) or (m != ref and re.sub(r"\s+", "", m) != re.sub(r"\s+", "", ref))):
            # a letter in the wrong case ('...(W)Vn') is a typo on the certificate too
            ck.add(Finding("CO_MODEL", "ERROR", [co, ci], dict(no=it["no"], model=m, ref=ref), m, ref,
                           _model_at(co, it) + at(ci, _line_model(a) or a["qty"], "ref")))
    ck.end()


def _line_model(a):
    """The model of an invoice / packing-list line as a Field on that line (lines keep the model as text only)."""
    m, q = a.get("model"), a.get("qty")
    if not (m and q is not None and getattr(q, "line", None) is not None):
        return None
    t = q.line.text
    k = t.find(m)
    if k < 0:                                     # printed with spaces inside ('AB-X10 (W1)VN'): match ignoring them
        rx = r"\s*".join(map(re.escape, m.replace(" ", "")))
        f = re.search(rx, t)
        if not f:
            return None
        return Field(m, f[0], q.line, f.start(), f.end())
    return Field(m, m, q.line, k, k + len(m))


def _model_at(co, it):
    """Box of a Form D item's model ('MODEL: …' line); the item's first line only if the model was not located."""
    from .rules import _item_list_at
    f = _item_list_at(co, "model_f", it)
    return at(co, f) if f else at(co, it.get("hs_f"))


def _block_box(locs: list) -> list:
    """One box around consecutive lines (per page) instead of one box per line: tight lines would overlap."""
    from .rules import Loc
    out, pages = [], {}
    for x in locs:
        if x.clip is None or x.page is None:
            out.append(x)
        else:
            pages.setdefault(x.page, []).append(x)
    for pg, xs in pages.items():
        c = (min(x.clip[0] for x in xs), min(x.clip[1] for x in xs), max(x.clip[2] for x in xs), max(x.clip[3] for x in xs))
        out.append(Loc(xs[0].doc, pg, c, None, xs[0].role))
    return out


def typos_near(typos: list, models: list) -> bool:
    """Some mark model looks like a typo of an invoice model (reported as such, so the marks are not 'all wrong')."""
    return any(difflib.get_close_matches(t, models, n=1, cutoff=0.75) for t in typos)


def r_marks(ci, bl, co, out):
    if not ci:
        return
    ck = begin("MARKS", out)
    models = sorted({it["model"] for it in ci.items if it.get("model")})
    from .rules import _all_parts
    if not models and _all_parts(ci):              # parts with part numbers: marks list no models to check
        ck.na(evidence="items_are_parts")
        ck.end()
        return
    if not models:
        ck.need_items(ci)
        for it in ci.items:
            ck.need_item(ci, it, "model")
        ck.end()
        return
    cover = ci.lists.get("marks_models", [])
    pl_marks = ci.lists.get("pl_marks_models", [])
    lists = [(ci, cover), (bl, bl.lists.get("marks_models", []) if bl else []),
             (co, co.lists.get("marks_models", []) if co else [])]
    if not cover and not pl_marks and not any(lst for _, lst in lists):
        from .rules import _MODEL_TRACE
        if any(has_text(d, _MODEL_TRACE, 0) for d in (bl, co) if d):   # a model printed on the B/L / Form D, not read
            ck._input(bl or co, "lists.marks_models", "NOT_FOUND")
        else:                                      # marks written as a brand / code ('BRAND/ABCD'): nothing to check
            ck.na(evidence="marks_not_models")
    for key, lst in (("CI_MARKS_MODEL", cover), ("PL_MARKS_MODEL", pl_marks)):
        for f in lst:                              # the invoice's / packing list's own marks: a model not on the invoice
            ck.compared()
            if f.value not in models and f.value not in {p.get("model") for p in ci.pl_items}:
                near = difflib.get_close_matches(f.value, models, n=1, cutoff=0.75)
                ck.add(Finding(key, "ERROR" if near else "WARNING", [ci], dict(model=f.value),
                               f.value, near[0] if near else "", at(ci, f)))
    for d, lst in lists:
        if not d or not lst:
            continue                               # marks not written as model list (e.g. 'BRAND/ABCD'): nothing to check
        ck.compared()
        have = {master.key(f.value) for f in lst}
        typos = [f.value for f in lst if f.value not in models]          # reported as *_MARKS_MODEL already
        missing = [m for m in models if master.key(m) not in have
                   and not difflib.get_close_matches(m, typos, n=1, cutoff=0.75)]
        if missing and len(missing) == len(models) and not typos_near(typos, models):
            # none of the invoice's models in these marks (copied from another shipment?): one ERROR over the block;
            # its per-model findings are withdrawn (_marks_none_gate)
            want = ", ".join(dict.fromkeys(it["model"] for it in ci.items if it.get("model")))   # invoice order
            ck.add(Finding("MARKS_NONE", "ERROR", [d, ci], dict(models=want),
                           ", ".join(f.value for f in lst), want, _block_box([x for f in lst for x in at(d, f)])))
        elif missing:
            ck.add(Finding("MARKS_MISSING", "WARNING", [d, ci], dict(models=", ".join(missing)),
                           ", ".join(f.value for f in lst), ", ".join(models), at(d, lst[-1])))
    ck.end()


def r_origin(ci, scs, co, out, bl=None):
    entries = ([(co, f) for f in co.lists.get("origin", [])] if co else []) + \
              ([(ci, ci.f.get("origin"))] if ci else []) + [(s, s.f.get("origin")) for s in scs] + \
              ([(bl, bl.f.get("origin"))] if bl else [])          # B/L: 'MADE IN ...' in the marks
    ck = begin("ORIGIN", out)
    src = ([(co, "lists.origin", f) for f in co.lists.get("origin", [])] or [(co, "lists.origin", None)] if co else []) + \
          ([(ci, "origin", ci.f.get("origin"))] if ci else []) + [(s, "origin", s.f.get("origin")) for s in scs] + \
          ([(bl, "origin", bl.f.get("origin"))] if bl else [])
    _sources(ck, src)
    odd, ref = _odd_ones(entries, lambda v: str(v).upper().strip())
    for d, f in odd:
        ck.add(Finding("ORIGIN", "ERROR", [d], dict(origin=f.value, ref=ref.upper()), f.value, ref.upper(), at(d, f)))
    ck.end()


def r_import_country(co, bl, out):
    if not (co and bl):
        return
    ck = begin("CO_IMPORT_COUNTRY", out)
    ck.need(bl, "dest_country")
    ck.need_list(co, "import_country")
    if not bl.f.get("dest_country"):
        ck.end()
        return
    dest = bl.f["dest_country"]
    for f in co.lists.get("import_country", []):
        ck.compared()
        if re.sub(r"\s+", "", f.value.upper()) != re.sub(r"\s+", "", dest.value.upper()):   # VIET NAM = VIETNAM
            ck.add(Finding("CO_IMPORT_COUNTRY", "ERROR", [co, bl], dict(country=f.value, ref=dest.value), f.value,
                           dest.value, at(co, f) + at(bl, dest, "ref")))
    ck.end()


def r_parties(ci, scs, bl, co, out):
    # order = which document wins a tie: contract / invoice, then Form D (certified), the B/L (typed by the forwarder) last
    names = dict(consignee=[(ci, "consignee")] + [(s, "buyer") for s in scs] + [(co, "consignee"), (bl, "consignee")],
                 shipper=[(s, "seller") for s in scs] + [(co, "exporter"), (bl, "shipper")])
    shippers = [(s, s.f.get("seller")) for s in scs] + [(co, co.f.get("exporter") if co else None),
                                                         (bl, bl.f.get("shipper") if bl else None)]
    tp = co.f.get("third_party") if co else None
    if tp:
        # third-party invoicing (Form E box 13): box 1 is the maker, the operator in box 7 is the seller. The B/L
        # shipper may be either of them.
        names["shipper"] = [(s, "seller") for s in scs] + [(co, "third_party"), (bl, "shipper")]
        maker = co.f.get("exporter")
        bs = bl.f.get("shipper") if bl else None
        shippers = [(s, s.f.get("seller")) for s in scs] + [(co, tp)] + (
            [] if bs is None or (maker and _party(bs.value) == _party(maker.value)) else [(bl, bs)])
    for role, entries in (
            ("@consignee", [(ci, ci.f.get("consignee") if ci else None)] + [(s, s.f.get("buyer")) for s in scs]
             + [(co, co.f.get("consignee") if co else None), (bl, bl.f.get("consignee") if bl else None)]),
            ("@shipper", shippers)):
        ck = begin(f"PARTY.{role[1:]}", out)
        _sources(ck, [(d, n, d.f.get(n)) for d, n in names[role[1:]] if d is not None])
        odd, ref = _odd_ones([(d, f) for d, f in entries if d], _party)
        for d, f in odd:
            ck.add(Finding("PARTY_NAME", "WARNING", [d], dict(role=role, name=f.value, ref=ref), f.value, ref, at(d, f)))
        ck.end()


def r_currency(ci, scs, co, out):
    ck = begin("CURRENCY", out)
    docs_ = [d for d in ([ci] + list(scs) + [co]) if d]
    for d in docs_:
        if d.lists.get("currency"):
            ck._input(d, "lists.currency", "READ")
        elif "currency" in str(_v(d.f.get("absent")) or "").split(", "):
            continue                               # the document prints no money at all (Form E without FOB values)
        else:
            ck._input(d, "lists.currency", "NOT_FOUND")
    per_doc = [(d, d.lists.get("currency", [])) for d in ([ci] + list(scs) + [co]) if d]
    per_doc = [(d, fs) for d, fs in per_doc if fs]
    if len(per_doc) >= 2:
        ck.compared()
    elif not ck.missing:
        ck.na(evidence="fewer_than_two_sources")
    codes = Counter(c for _, fs in per_doc for c in {f.value for f in fs})
    if len(codes) < 2:
        ck.end()
        return
    top = codes.most_common(1)[0][0]
    for d, fs in per_doc:
        bad = [f for f in fs if f.value != top]
        if bad:
            ck.add(Finding("CURRENCY", "ERROR", [d], dict(cur=bad[0].value, ref=top), bad[0].raw, top, at(d, bad[0])))
    ck.end()


def r_payment(ci, scs, out):
    a = ci.f.get("payment") if ci else None
    ck = begin("PAYMENT_TERMS", out)
    ck.need(ci, "payment")
    for s in scs:
        b = s.f.get("payment")
        ck.need(s, "payment")
        if a and b:
            ck.compared()
        if a and b and _terms(a.value) != _terms(b.value):
            ck.add(Finding("PAYMENT_TERMS", "WARNING", [ci, s], {}, a.value, re.sub(r"^\s*By\s+", "", b.value),
                           at(ci, a) + at(s, b, "ref")))
    ck.end()


def r_sc_goods(ci, scs, out):
    """Goods named on the Sales Contract = goods on the invoice (one may name more products than the other)."""
    ref = ci.f.get("goods_full") or ci.f.get("goods") if ci else None
    ck = begin("SC_GOODS_DESC", out)
    if not ref:
        ck.need(ci, "goods_full")
        ck.end()
        return
    ck._input(ci, "goods_full" if ci.f.get("goods_full") else "goods", "READ")   # the description it compares with
    want = _goods_words(ref.value)
    for sc in scs:
        g = sc.f.get("goods_full")
        ck.need(sc, "goods_full")
        have = _goods_words(g.value) if g else set()
        if have:
            ck.compared()
        if have and not (have <= want or want <= have):
            ck.add(Finding("SC_GOODS_DESC", "ERROR", [sc, ci], {}, g.value, ref.value, at(sc, g) + at(ci, ref, "ref")))
    ck.end()


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


_OTHER_RULE = dict(consignee="PARTY.consignee", shipper="PARTY.shipper", vessel="VESSEL.ci", pol="INCOTERM_PORT",
                   pod="BL_DESTINATION", sailing="DEPARTURE_DATE", payment="PAYMENT_TERMS", origin="ORIGIN",
                   goods_full="SC_GOODS_DESC", pos="SC_PO_COVERAGE", containers="CONTAINERS", incoterm="INCOTERM_PORT",
                   freight="FREIGHT_TERM")


def r_pl_header(ci, others, out):
    """The packing list repeats the invoice header: consignee, shipper, vessel, ports, dates, terms, P/O … must be the
    same. (Invoice no. and date on every page: DOC_HEADER.) When the other documents agree with the packing list, the
    invoice is the odd one out and the cross-document rule (ORIGIN, PARTY_NAME, …) reports it instead."""
    if not ci:
        return
    from .extract_net import PL_HEADER
    has_pl = any("PACKING LIST" in l.text.upper() for l in ci.lines)
    for k in PL_HEADER:
        ck = begin(f"PL_HEADER.{k}", out, ci)
        a, b = ci.f.get(k), ci.f.get("pl_" + k)
        if not has_pl:                             # no packing-list part in this file: nothing repeats the header
            ck.na(evidence="no_packing_list", doc=ci.name)
        elif k == "pos" and not (a and a.value) and not (b and b.value):
            ck.need(ci, k, trace=r"(?i)\bP/?O\b|PURCHASE ORDER")    # 'pos' is always set (maybe empty)
            ck.need(ci, "pl_" + k, trace=r"(?i)\bP/?O\b|PURCHASE ORDER")
        else:
            ck.need(ci, k, absent_ok=True)
            ck.need(ci, "pl_" + k, absent_ok=True)
        if a and b and a.value not in (None, "", []) and b.value not in (None, "", []):
            ck.compared()
        if not (a and b and a.value not in (None, "", []) and b.value not in (None, "", [])) or _same_val(k, a.value, b.value):
            ck.end()
            continue
        if any(d.kind == kind and d.f.get(fk) and _same_val(k, d.f[fk].value, b.value)
               for kind, fk in _ELSEWHERE.get(k, ()) for d in others):
            ck.blocked(_OTHER_RULE.get(k, "cross-document rule"))   # the invoice is the odd one out: reported there
            ck.end()
            continue
        if True:
            show = lambda f: ", ".join(f.value) if isinstance(f.value, list) else (
                f"{f.value[0]} V.{f.value[1]}" if isinstance(f.value, tuple) else
                f"{f.value:%d/%m/%Y}" if hasattr(f.value, "strftime") else str(f.value))
            ck.add(Finding("PL_HEADER", "ERROR", [ci], dict(label=PL_LABELS[k]), show(b), show(a),
                           at(ci, b) + at(ci, a, "ref")))
        ck.end()


_COLLECT = ("EXW", "FCA", "FAS", "FOB")             # buyer pays the main freight
_PREPAID = ("CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")


def r_freight(ci, bl, out):
    """Freight COLLECT / PREPAID on invoice, packing list and B/L agree with each other and with the Incoterm."""
    inco = (ci.f.get("incoterm") if ci else None)
    term = inco.value.split()[0] if inco else None
    want = "COLLECT" if term in _COLLECT else "PREPAID" if term in _PREPAID else None
    ck = begin("FREIGHT_TERM", out)
    for d, k in ((ci, "freight"), (ci, "pl_freight"), (bl, "freight")):
        ck.need(d, k, absent_ok=True, trace=r"(?i)\bFREIGHT\s+(?:COLLECT|PREPAID)")
    entries = [(d, d.f.get(k)) for d, k in ((ci, "freight"), (ci, "pl_freight"), (bl, "freight")) if d and d.f.get(k)]
    if not entries:
        ck.end()
        return
    if not want:
        ck.need(ci, "incoterm", absent_ok=True)
        odd, ref = _odd_ones(entries, lambda v: str(v).upper())
        want = ref.upper() if odd and ref else None
        if len(entries) >= 2:
            ck.compared()
    else:
        ck.compared()
    for d, f in entries:
        if want and f.value.upper() != want:
            ck.add(Finding("FREIGHT_TERM", "ERROR", [d], dict(term=term or want, want=want), f"FREIGHT {f.value}",
                           f"FREIGHT {want}", at(d, f) + (at(ci, inco, "ref") if inco else [])))
    ck.end()


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
        (r"\(\s*PAGE\s+([0-9OIlSB]*[OIlSB][0-9OIlSB]*)\s+(?i:OF)\b", 1, "digit", d2),          # (PAGE I OF 4)
        (r"\(\s*PAGE\s+\d+\s+(0[Ff])\s+\d", 1, "letter", lambda t: "OF"),            # (PAGE 2 0F 4)
        (r"\(\s*PAGE\s+\d+\s+(?i:OF)\s+([0-9OIlSB]*[OIlSB][0-9OIlSB]*)\s*\)", 1, "digit", d2),
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


def _tech_terms() -> frozenset:
    from .rules import CONFIG
    return frozenset(t.upper() for t in CONFIG.get("technical_terms", []))


_TECH_TERMS = _tech_terms()


def r_text_typo(docs, out):
    """A mistyped word anywhere in a document: this does not depend on LDV reading that field, so a typo in a value
    LDV does not compare (or cannot read because of the typo) is still shown."""
    vocab = frozenset(w.upper() for d in docs for l in d.lines for w in re.findall(r"[A-Za-z0-9]+", l.text)
                      if not re.search(r"[a-z]", w) or w.isupper()) | NUMBER_WORDS | {"PCS", "SETS", "SET", "CARTONS"}
    found = {}
    # a voyage number ending in its direction ('0123N', 'S034') is read as the voyage and compared (VESSEL)
    voyages = {v.value[1] for d in docs for v in [d.f.get("vessel")] if v is not None and isinstance(v.value, tuple)
               and re.fullmatch(r"\d{3,}[NSEW]|[NSEW]\d{3,}", v.value[1] or "")}   # 0123N, S034
    for d in docs:
        ck = begin("TEXT_TYPO", out, d)
        ck.compared()
        for l in d.lines:
            for a, b, w, kind, fix in typo_words(l.text, vocab):
                if kind == "digit" and w in voyages:
                    continue
                if any(x < b and a < y for x, y in found.get(id(l), [])) or _reported(out, d, l.page, w):
                    continue                        # the same place found by a word rule and a context rule: once
                found.setdefault(id(l), []).append((a, b))
                # a technical term written as it should be (RoHS): information only (config "technical_terms")
                sev = "INFO" if w.upper() in _TECH_TERMS else "WARNING"
                ck.add(Finding("TEXT_TYPO", sev, [d], dict(word=w, kind=f"@typo_{kind}"), w, fix,
                               at(d, Field(w, w, l, a, b))))
        ck.end()


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
        ck = begin("VALUE_UNREADABLE", out, d)
        ck.compared()
        seen = set()
        for f in _fields([d.f, d.lists, d.items, d.pl_items]):
            if f.value is not None or not str(f.raw or "").strip():
                continue
            key = (f.page, round(f.line.y, 1), f.start, f.raw)
            if key in seen or _reported(out, d, f.page, f.raw) or any(
                    _reported(out, d, f.page, w) for _a, _b, w, _k, _x in typo_words(f.raw)):
                continue
            seen.add(key)
            ck.add(Finding("VALUE_UNREADABLE", "WARNING", [d], dict(value=f.raw.strip()), f.raw.strip(), "",
                           at(d, f)))
        ck.end()


DATE_FAR_DAYS = 300


def r_date_far(docs, ci, out):
    """Every date read in the package lies within DATE_FAR_DAYS of the invoice date: '17/11/3026' or '2025' for
    '2026' is a typo that no other rule would see when the date is not compared with another document."""
    ref_f = ci.f.get("invoice_date") if ci else None
    ref = ref_f.value if ref_f and hasattr(ref_f.value, "year") else None
    if not ref:
        for d in docs:
            ck = begin("DATE_FAR", out, d)
            if ci is not None:
                ck.need(ci, "invoice_date")
            else:
                ck.not_run("document_missing", kind="CI")
            ck.end()
        return
    seen = set()
    for d in docs:
        ck = begin("DATE_FAR", out, d)
        ck._input(ci, "invoice_date", "READ")
        ck.compared()
        for f in _fields([d.f, d.lists, d.items, d.pl_items]):
            v = f.value
            if not (hasattr(v, "year") and not hasattr(v, "hour")) or abs((v - ref).days) <= DATE_FAR_DAYS:
                continue
            key = (d.name, f.page, f.raw)
            if key in seen or _reported(out, d, f.page, f.raw):
                continue
            seen.add(key)
            ck.add(Finding("DATE_FAR", "WARNING", [d], dict(date=f.raw.strip(), days=f"{abs((v - ref).days):,}",
                                                            ref=f"{ref:%d/%m/%Y}"),
                           f.raw.strip(), "", at(d, f) + at(ci, ref_f, "ref")))
        ck.end()


def validate_net(docs, ci, bl, co, scs, out):
    _call(r_cover_totals, ci, out)
    _call(r_gw_nw, ci, out)
    _call(r_eta, ci, out)
    _call(r_headers, ci, out)
    _call(r_cover_pos, ci, out)
    _call(r_co_self, co, out)
    _call(r_ci_pl_ctn, ci, out)
    _call(r_lines, ci, out)
    _call(r_co_model, ci, co, out)
    _call(r_co_values, ci, co, out)
    _call(r_marks, ci, bl, co, out)
    _call(r_origin, ci, scs, co, out, bl)
    _call(r_import_country, co, bl, out)
    _call(r_parties, ci, scs, bl, co, out)
    _call(r_currency, ci, scs, co, out)
    _call(r_payment, ci, scs, out)
    _call(r_sc_goods, ci, scs, out)
    _call(r_pl_header, ci, [d for d in docs if d is not ci], out)
    _call(r_freight, ci, bl, out)
    _call(r_date_far, docs, ci, out)
    _call(r_text_typo, docs, out)                          # last: an earlier finding on the same text comes first
    _call(r_unreadable, docs, out)
