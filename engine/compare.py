"""Cross-document comparison of extracted values (works on a stored review session, see session.py).

For each field in config.json "compare.fields" and each document column it gives one cell:
  value   the value read from that document (+ document name and page)
  missing the field applies to that document, the document is in the package, but the value was not read
  na      the field does not appear on that kind of document
  nodoc   that kind of document is not in the package
and a result per field: match | mismatch | incomplete (some applicable values missing, the rest agree) |
single (only one document has it, nothing to compare) | none (no value anywhere).

Nothing is guessed: only values the engine extracted are compared, with the engine's own equivalences
(port / city names, HS headings, number tolerance). Several documents of one kind (e.g. two sales contracts)
are combined: numbers are added up, other values are pooled.
"""
import re

from . import master
from .rules import CONFIG, _canon_port, _city

TOL = 0.005


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def fmt(v, typ: str) -> str:
    if typ == "number":
        n = _num(v)
        if n is None:
            return str(v)
        return f"{n:,.0f}" if abs(n - round(n)) < 1e-9 else f"{n:,.3f}".rstrip("0").rstrip(".")
    return str(v)


def _atoms(raw: str, typ: str) -> list[str]:
    if typ == "po":                                  # contract / PO references; drops suffixes like "/10"
        return list(dict.fromkeys(re.findall(r"[A-Z0-9]{8,}", str(raw).upper())))
    if typ in ("set", "hs", "docref"):
        return [x.strip() for x in str(raw).split(",") if x.strip()]
    return [str(raw).strip()] if str(raw).strip() else []


def _norm(v: str, typ: str):
    s = re.sub(r"\s+", " ", str(v).upper()).strip()
    if typ == "number":
        return _num(s)
    if typ == "port":
        return _city(s) or _canon_port(s) or s
    if typ in ("vessel", "set", "docref", "po"):
        return re.sub(r"[^A-Z0-9]", "", s)
    if typ == "hs":
        return master.digits(s)
    if typ == "goods":                            # same words as rule SC_GOODS_DESC (quotes, BRAND, plurals ignored)
        from .rules_net import _goods_words
        return " ".join(sorted(_goods_words(s)))
    if typ in ("party", "terms"):                 # same normalisation as the PARTY_NAME / PAYMENT_TERMS rules
        from .rules_net import _party, _terms
        return _party(s) if typ == "party" else _terms(s)
    return s.strip(" .,;:")


def _values(doc: dict, src: str, typ: str) -> tuple[list[str], int | None]:
    """Raw values of one source in one document, and the page where the first one sits. 'a|b': the first one read."""
    if "|" in src:
        for alt in src.split("|"):
            v, p = _values(doc, alt, typ)
            if v:
                return v, p
        return [], None
    if src.startswith("Σitems."):                 # no printed total: the lines added up (as the rules do: true_total)
        key = src.split(".", 1)[1]
        vals = [_num(it.get(key)) for it in doc.get("items", [])]
        if not vals or any(v is None for v in vals):
            return [], None
        return [str(round(sum(vals), 6))], next((it.get("_page") for it in doc.get("items", []) if it.get("_page")), None)
    if src.startswith("items."):
        key = src.split(".", 1)[1]
        vals, page = [], None
        for it in doc.get("items", []):
            v = it.get(key)
            if v not in (None, ""):
                for a in _atoms(v, typ):
                    if a not in vals:
                        vals.append(a)
                page = page or it.get("_page")
        return vals, page
    f = doc.get("fields", {}).get(src)
    if not f or f.get("value") in (None, ""):
        return [], None
    return _atoms(f["value"], typ), f.get("page")


def _absent(d: dict, src: str) -> bool:
    """The document's layout does not print this field at all (extract_net marks it), so it is not 'not read'."""
    a = (d.get("fields", {}).get("absent") or {}).get("value") or ""
    return all(k.strip() in a.split(", ") for k in src.split("|"))   # 'a|b': not printed only if neither is


def _cell(docs: list[dict], src: str, typ: str) -> dict:
    vals, pages, names = [], [], []
    if docs and all(_absent(d, src) for d in docs):
        return dict(state="na")
    for d in docs:
        v, p = _values(d, src, typ)
        if v:
            vals.append(v)
            pages.append(p)
            names.append(d["name"])
    if not vals:
        for d in docs:                            # the label is printed with nothing after it: say so, not 'not read'
            b = next((d.get("fields", {}).get("blank:" + k.strip()) for k in src.split("|")
                      if d.get("fields", {}).get("blank:" + k.strip())), None)
            if b:
                return dict(state="blank", label=b.get("value") or "", doc=d["name"], page=b.get("page"))
        return dict(state="missing", doc=docs[0]["name"], page=None)
    # every document's own values, for the table (one line each, coloured per value)
    parts = [dict(doc=n, page=p, show=[fmt(a, typ) for a in v], norm=[_norm(a, typ) for a in v])
             for n, p, v in zip(names, pages, vals)]
    partial = False
    if typ == "number" and len(docs) > 1 and len(vals) < len(docs):
        # some documents of this kind give the value and others not (not printed or not read): no package total
        partial = True
    nos = [(d.get("fields") or {}).get("cntr_nos") for d in docs]
    if typ == "number" and len(vals) > 1 and src == "containers" and all(nos):
        # packing lists that name their containers: one container may hold goods of several invoices
        total = len({x.strip() for n in nos for x in str(n.get("value") or "").split(",") if x.strip()})
        flat = [str(total)]
    elif typ == "number" and len(vals) > 1:                   # e.g. two sales contracts: add them up
        total = sum(_num(v[0]) or 0 for v in vals)
        flat = [str(total)]
    else:
        flat = list(dict.fromkeys(a for v in vals for a in v))
    return dict(state="value", raw=flat, show=", ".join(fmt(a, typ) for a in flat), items=[fmt(a, typ) for a in flat],
                norm=[_norm(a, typ) for a in flat], doc=names[0], docs=names, page=pages[0], parts=parts,
                partial=partial)


def _same(a: list, b: list, typ: str) -> bool:
    if typ == "number":
        return len(a) == len(b) == 1 and a[0] is not None and b[0] is not None and abs(a[0] - b[0]) <= TOL
    if typ == "hs":                        # 8516 covers 8516.10.11; a B/L with several headings covers each item
        pre = lambda x, ys: any(x.startswith(y) or y.startswith(x) for y in ys)
        a_, b_ = [x for x in a if x], [x for x in b if x]
        return bool(a_ and b_) and all(pre(x, b_) for x in a_) and all(pre(y, a_) for y in b_)
    if typ == "goods":                     # one document names the goods together, another one item at a time
        wa, wb = set(" ".join(a).split()), set(" ".join(b).split())
        return bool(wa and wb) and (wa <= wb or wb <= wa)
    if typ == "docref":                    # Form D box 10 may cut the invoice no. at the line end (rule CO_INVOICE_NO)
        pre = lambda x, ys: any(y.startswith(x) or x.startswith(y) for y in ys if min(len(x), len(y)) >= 8)
        return all(pre(x, b) for x in a) and all(pre(y, a) for y in b)
    return set(a) == set(b)


def _groups(s: dict) -> dict:
    """Document name -> invoice group ids, from the check records (LDV >= 2.3). Several invoices: a contract / Form D
    belongs to one invoice group; a B/L to all of them."""
    out = {}
    for r in s.get("checks", []):
        if r.get("group_type") == "invoice":
            for d in r.get("documents", []):
                out.setdefault(d, set()).add(r["group"])
    return out


def compare(s: dict) -> dict:
    cfg = CONFIG["compare"]
    doc_groups = _groups(s)
    n_ci = sum(d.get("kind") == "CI" for d in s.get("docs", []))
    by_kind = {}
    for d in s.get("docs", []):
        by_kind.setdefault(d.get("kind"), []).append(d)
    cols = [dict(c, docs=by_kind.get(c["kind"], [])) for c in cfg["columns"]]
    rows = []
    for fd in cfg["fields"]:
        cells = {}
        for c in cols:
            src = fd["src"].get(c["id"])
            if not src:
                cells[c["id"]] = dict(state="na")
            elif not c["docs"]:
                cells[c["id"]] = dict(state="nodoc")
            else:
                cells[c["id"]] = _cell(c["docs"], src, fd["type"])
        have = [(k, v) for k, v in cells.items() if v["state"] == "value" and not v.get("partial")]
        if fd["id"] == "shipper":
            # third-party invoicing (Form E box 13): the certificate names the maker in box 1 and the seller as the
            # operator; a B/L shipper that is the maker is right too (rule PARTY.shipper does the same)
            makers = [_norm(x, fd["type"]) for d in by_kind.get("CO", []) if (d.get("fields") or {}).get("third_party")
                      for x in [((d.get("fields") or {}).get("exporter") or {}).get("value")] if x]
            bl = cells.get("BL", {})
            if makers and bl.get("state") == "value" and all(n in makers for n in bl["norm"]):
                bl["maker"] = True
                have = [(k, v) for k, v in have if k != "BL"]
        missing = [k for k, v in cells.items() if v["state"] == "missing" or v.get("partial")]
        # columns that may name only part of the values (config "subset"): a Form D certifies the invoices it lists,
        # it need not list every invoice of the package. They must not name anything the others do not have.
        subset_cols = set(fd.get("subset", []))
        if fd["type"] == "number" and n_ci > 1 and doc_groups:
            subset_cols |= {"SC", "CO"}          # several invoices: a contract / Form D covers its own invoice only
        sub = [(k, v) for k, v in have if k in subset_cols]
        if sub and len(have) > len(sub):
            have = [(k, v) for k, v in have if k not in subset_cols]
        else:
            sub = []
        if not have:
            result = "none"
        else:
            ref = have[0][1]["norm"]
            odd = [k for k, v in have[1:] if not _same(ref, v["norm"], fd["type"])]
            if odd:
                # the value most documents agree on is the reference; the others are the odd ones out
                groups = []
                for k, v in have:
                    g = next((g for g in groups if _same(g[0][1]["norm"], v["norm"], fd["type"])), None)
                    if g:
                        g.append((k, v))
                    else:
                        groups.append([(k, v)])
                groups.sort(key=len, reverse=True)
                odd = [k for g in groups[1:] for k, _ in g] if len(groups[0]) > len(groups[1]) else [k for k, _ in have]
                result = "mismatch"
            else:
                result = "incomplete" if missing else ("single" if len(have) == 1 else "match")
            for k in odd:
                cells[k]["odd"] = True
            agreed = [v["norm"] for k, v in have if k not in odd]
            for k, v in sub:
                if fd["type"] == "number":         # against the invoices of the same group(s) only
                    ok = _same(v["norm"], _group_sum(cells, have, v, doc_groups), "number")
                    if not ok:
                        cells[k]["vs_groups"] = True
                else:
                    ok = bool(agreed) and _same(v["norm"], [x for x in agreed[0] if any(_same([x], [y], fd["type"])
                                                                                       for y in v["norm"])], fd["type"])
                if not ok:
                    cells[k]["odd"] = True
                    result = "mismatch"
            if sub and result == "single" and not any(v.get("odd") for _, v in sub):
                result = "match"                   # the contract / Form D agree with their own invoice(s)
        rows.append(dict(id=fd["id"], en=fd["en"], vi=fd["vi"], type=fd["type"], unit=fd.get("unit", ""),
                         cells=cells, result=result))
    _against_ref(rows, cfg["fields"])
    return dict(columns=[{k: c[k] for k in ("id", "kind", "en", "vi")} | dict(n_docs=len(c["docs"]))
                         for c in cols], rows=rows, lines=lines(s, by_kind), not_read=cfg.get("not_read", []))


def _group_sum(cells: dict, have: list, cell: dict, groups: dict) -> list:
    """The invoice-side value of the invoice groups a contract / Form D cell belongs to: the per-document values of
    the first invoice-side column (CI, else PL) for the invoices in those groups, added up."""
    gs = set().union(*[groups.get(d, set()) for d in cell.get("docs", [])])
    for k, v in have:
        parts = [p for p in v.get("parts", []) if groups.get(p["doc"], set()) & gs]
        if k in ("CI", "PL") and parts:
            return [round(sum(p["norm"][0] or 0 for p in parts), 6)]
    return []


def _against_ref(rows: list, fields: list):
    """A field printed on one document only, checked against a related row ("ref" in config): the B/L final
    destination must be in the city of the port of discharge. Without this the row says "only one document" even
    when the B/L sends the goods to another city (rule BL_DESTINATION reports it too)."""
    by_id = {r["id"]: r for r in rows}
    for fd in fields:
        r, ref = by_id.get(fd["id"]), by_id.get(fd.get("ref") or "")
        if not (r and ref):
            continue
        agreed = [v for v in ref["cells"].values() if v["state"] == "value" and not v.get("odd")]
        if not agreed:
            continue
        want = agreed[0]
        r["vs"] = dict(en=ref["en"], vi=ref["vi"], show=want["show"])
        cells = [v for v in r["cells"].values() if v["state"] == "value"]
        bad = [v for v in cells if not _same(want["norm"], v["norm"], r["type"])]
        for v in bad:
            v["odd"] = True
        if bad:
            r["result"], r["vs"]["same"] = "mismatch", False
        elif cells:
            r["vs"]["same"] = True
            if r["result"] == "single":
                r["result"] = "match"


def lines(s: dict, by_kind: dict) -> list[dict]:
    """Per model: quantity in invoice / packing list / sales contract / Form D, unit price in invoice / contract."""
    srcs = CONFIG["compare"]["lines"]
    models, out = [], {}
    for col, lst in srcs.items():
        kind = "CI" if col == "PL" else col
        for d in by_kind.get(kind, []):
            for it in d.get(lst, []):
                m = master.key(it.get("model"))
                if not m:
                    continue
                if m not in out:
                    models.append(m)
                    out[m] = dict(model=it.get("model"), qty={}, price={}, page={}, doc={})
                r = out[m]
                r["qty"][col] = (r["qty"].get(col) or 0) + (_num(it.get("qty")) or 0)
                if it.get("price") not in (None, "") and col in ("CI", "SC"):
                    r["price"].setdefault(col, _num(it.get("price")))
                r["page"].setdefault(col, it.get("_page"))
                r["doc"].setdefault(col, d["name"])
    rows = []
    for m in models:
        r = out[m]
        present = {c for c in srcs if by_kind.get("CI" if c == "PL" else c)}
        q = [v for v in r["qty"].values()]
        qty_ok = all(abs(v - q[0]) <= TOL for v in q)
        p = list(r["price"].values())
        price_ok = all(abs(v - p[0]) <= TOL for v in p if v is not None)
        missing = sorted(present - set(r["qty"]), key=list(srcs).index)
        r.update(result="mismatch" if not (qty_ok and price_ok) else ("incomplete" if missing else "match"),
                 missing=missing, qty_odd=not qty_ok, price_odd=not price_ok)
        rows.append(r)
    return rows
