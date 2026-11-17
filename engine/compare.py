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
    return any(k.strip() in a.split(", ") for k in src.split("|"))


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
        return dict(state="missing", doc=docs[0]["name"], page=None)
    # every document's own values, for the table (one line each, coloured per value)
    parts = [dict(doc=n, page=p, show=[fmt(a, typ) for a in v], norm=[_norm(a, typ) for a in v])
             for n, p, v in zip(names, pages, vals)]
    if typ == "number" and len(vals) > 1:                     # e.g. two sales contracts: add them up
        total = sum(_num(v[0]) or 0 for v in vals)
        flat = [str(total)]
    else:
        flat = list(dict.fromkeys(a for v in vals for a in v))
    return dict(state="value", raw=flat, show=", ".join(fmt(a, typ) for a in flat), items=[fmt(a, typ) for a in flat],
                norm=[_norm(a, typ) for a in flat], doc=names[0], docs=names, page=pages[0], parts=parts)


def _same(a: list, b: list, typ: str) -> bool:
    if typ == "number":
        return len(a) == len(b) == 1 and a[0] is not None and b[0] is not None and abs(a[0] - b[0]) <= TOL
    if typ == "hs":
        heads = [x for x in a + b if x]
        short = min(heads, key=len) if heads else ""
        return bool(short) and all(x.startswith(short) for x in heads)       # 8516 covers 8516.10.11
    if typ == "goods":                     # one document names the goods together, another one item at a time
        wa, wb = set(" ".join(a).split()), set(" ".join(b).split())
        return bool(wa and wb) and (wa <= wb or wb <= wa)
    if typ == "docref":                    # Form D box 10 may cut the invoice no. at the line end (rule CO_INVOICE_NO)
        pre = lambda x, ys: any(y.startswith(x) or x.startswith(y) for y in ys if min(len(x), len(y)) >= 8)
        return all(pre(x, b) for x in a) and all(pre(y, a) for y in b)
    return set(a) == set(b)


def compare(s: dict) -> dict:
    cfg = CONFIG["compare"]
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
        have = [(k, v) for k, v in cells.items() if v["state"] == "value"]
        missing = [k for k, v in cells.items() if v["state"] == "missing"]
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
        rows.append(dict(id=fd["id"], en=fd["en"], vi=fd["vi"], type=fd["type"], unit=fd.get("unit", ""),
                         cells=cells, result=result))
    return dict(columns=[{k: c[k] for k in ("id", "kind", "en", "vi")} | dict(n_docs=len(c["docs"]))
                         for c in cols], rows=rows, lines=lines(s, by_kind), not_read=cfg.get("not_read", []))


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
