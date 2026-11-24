"""Goods name and unit of every model against the company's master list (engine/master.py, columns name and unit).

The list is the reference. One finding per model and printed value: it names every document that prints it that way
(models that share one wrong heading share the finding).
  name  the name beside the model, else the goods heading of the document (which may list several names)
  unit  the word after the line's quantity, else the unit of the document's quantity column
A goods heading must not name goods either that none of the document's models has.
Wording that does not change the goods is ignored: quotes, BRAND, plurals, spaces, capitals, a size or SERIES after the
name ('20L(AB)SERIES'), and a missing brand where the line prints the name only.
"""
import difflib
import re
import unicodedata

from . import master
from .checks import begin
from .extract import Field
from .rules import CONFIG, Finding, _all_parts, _bl_block, at

_SIZE = re.compile(r"\d+(?:\.\d+)?\s*(?:L|LTR|LITERS?|LITRES?|KG|W|KW|CM|MM|INCH|IN)(?![A-Z])")
_AND = re.compile(r"\s+AND\s+|\s*[&,;]\s*")


def _text(t) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(t or ""))).strip().upper()


def _words(t) -> list:
    t = _text(t)
    m = _SIZE.search(t)
    if m and m.start():
        t = t[:m.start()]
    out = [re.sub(r"[^A-Z0-9]", "", w) for w in re.sub(r"[-/]", " ", t).split()]
    return [w[:-1] if len(w) > 3 and w.endswith("S") and not w.endswith("SS") else w
            for w in out if w and w not in ("BRAND", "SERIES")]


def same_name(printed, ref) -> bool:
    p, r = "".join(_words(printed)), _words(ref)
    return bool(p) and p in ("".join(r), "".join(r[1:]) or None)         # the line may leave out the brand


def _parts(text) -> list:
    return [x.strip() for x in _AND.split(_text(text)) if x.strip()]


def unit_key(u) -> str:
    """SETS / SET(S) / BỘ -> SET (config "units"); an unknown unit is itself, without its plural S."""
    t = re.sub(r"[^\w]", "", _text(u))
    for k, names in CONFIG.get("units", {}).items():
        if t in {re.sub(r"[^\w]", "", _text(n)) for n in [k] + names}:
            return k
    return t[:-1] if len(t) > 2 and t.endswith("S") else t


def _model(it) -> str:
    m = it.get("model")
    return str(m.value if isinstance(m, Field) else m or "")


def _line_unit(it):
    """(unit, Field to box) printed with the quantity of a line, or None."""
    q = it.get("qty")
    if q is None:
        return None
    if it.get("unit"):
        u = it["unit"]
        return (u.value, u) if isinstance(u, Field) else (str(u), q)
    m = re.match(r"\s*([^\W\d_]{2,}(?:\s*\(\s*S\s*\))?)", q.line.text[q.end:]) if q.end > q.start else None
    return (m[1], Field(m[1], m[1], q.line, q.end + m.start(1), q.end + m.end(1))) if m else None


def _rows(ci, scs, co):
    """(document, its lines, the heading's goods name, is the packing list)."""
    yield ci, ci.items, ci.f.get("goods_full") or ci.f.get("goods"), False
    yield ci, ci.pl_items, ci.f.get("pl_goods_full") or ci.f.get("goods_full") or ci.f.get("goods"), True
    for s in scs:
        yield s, s.items, s.f.get("goods_full") or s.f.get("goods"), False
    if co:
        yield co, co.items, None, False


def r_master_goods(ci, scs, co, bl, out):
    if not ci:
        return
    have = master.load() is not None
    parts = _all_parts(ci)
    models = list(dict.fromkeys(m for it in ci.items if (m := _model(it))))
    ref = {m: r for m in models if (r := master.row_for(m))}
    for cid, col in (("MASTER_NAME", "name"), ("MASTER_UNIT", "unit")):
        ck = begin(cid, out)
        if parts:
            ck.na(evidence="items_are_parts")
        elif ck.master(have):
            ck.need_items(ci)
            for it in ci.items:
                ck.need_item(ci, it, "model")
            if not master.has_column(col):            # the Excel has no such column: nothing to check against
                ck.na(evidence="master_no_column")
            else:
                for m in models:
                    if not (ref.get(m) or {}).get(col):
                        ck.master_missing(m)
                want = {m: r[col] for m, r in ref.items() if r.get(col)}
                (_names if col == "name" else _units)(ck, ci, scs, co, bl, want)
        ck.end()


def _place(doc, f, name) -> Field:
    """Where one name of a heading is printed (a heading may go on over the next lines); else the heading."""
    # by its place: a B/L block's line is a part of the page line
    i = next((k for k, l in enumerate(doc.lines) if l is f.line or (l.page == f.line.page and abs(l.y - f.line.y) < 1)), None)
    near = doc.lines[i:i + 4] if i is not None else [f.line]
    rx = re.compile(r"\s+".join(re.escape(w) for w in _text(name).split()), re.I)
    for l in near:
        m = rx.search(l.text)
        if m and l.page == f.line.page:
            return Field(m[0], m[0], l, m.start(), m.end())
    return f


def _docs(hits) -> list:
    out = []
    for d, _f, _s in hits:
        if not any(d is x for x in out):
            out.append(d)
    return out


def _locs(hits) -> list:
    out, seen = [], set()
    for d, f, _s in hits:
        for x in at(d, f):
            k = (id(d), x.page, x.clip)
            if k not in seen:
                seen.add(k)
                out.append(x)
    return out


def _report(ck, key, bad: dict, want: dict):
    """bad: {(model, printed key): [(doc, Field, shown)]}"""
    same = {}                                     # one wrong heading for several models: one finding naming them
    for (m, k), hits in bad.items():
        place = tuple((id(d), f.line.page, round(f.line.y, 1), f.start, f.end, f.raw) for d, f, _s in hits)
        same.setdefault((place, k, _text(want[m])), []).append(m)
    for (_p, k, _r), ms in same.items():
        m, hits = ms[0], bad[(ms[0], k)]
        ck.add(Finding(key, "WARNING", _docs(hits), dict(model=", ".join(ms), ref=_text(want[m])), hits[0][2], _text(want[m]), _locs(hits)))


def _names(ck, ci, scs, co, bl, want):
    bad, extra = {}, {}

    def unused(doc, f, models):
        """The names of a goods heading that no model of the document has. Only when every model's name is known:
        else the name may be that of the unknown one."""
        if not models or not all(m in want for m in models):
            return
        refs = [want[m] for m in models]
        for n in _parts(f.value):
            k = "".join(_words(n))
            # half of a name that holds an 'AND' itself is not a name of its own
            if k and not any(same_name(n, r) or (len(_parts(r)) > 1 and k in "".join(_words(r))) for r in refs):
                extra.setdefault(k, []).append((doc, _place(doc, f, n), n))

    def check(doc, m, f, heading):
        ck.compared()
        names = _parts(f.value) if heading else [_text(f.value)]
        if any(same_name(n, want[m]) for n in names + [_text(f.value)]):
            return
        # a heading may list several names: the one nearest to the master name is shown
        near = max(names, key=lambda n: difflib.SequenceMatcher(None, "".join(_words(n)), "".join(_words(want[m]))).ratio(),
                   default=_text(f.value))
        bad.setdefault((m, "".join(_words(near))), []).append((doc, f, near))

    for doc, lines, head, _pl in _rows(ci, scs, co):
        done = set()
        if isinstance(head, Field) and any(not isinstance(it.get("desc"), Field) and not it.get("goods_full") for it in lines):
            unused(doc, head, [_model(it) for it in lines])
        for it in lines:
            m = _model(it)
            if m not in want:
                continue
            f = it.get("desc") if it.get("desc") is not None else it.get("goods_full") or it.get("goods")
            f, heading = (f, False) if isinstance(f, Field) else (head, True)
            if not isinstance(f, Field) or not _text(f.value):
                continue
            if (m, heading, _text(f.value)) not in done:
                done.add((m, heading, _text(f.value)))
                check(doc, m, f, heading)
    if bl:
        blk = _bl_block(bl, ci)
        f = blk.goods if blk is not None else bl.f.get("goods_full") or bl.f.get("goods")
        for m in want if f else ():
            check(bl, m, f, True)
        # a B/L heading over several invoices also names the goods of the others
        if f and (blk is not None or (len(bl.cargo_blocks) < 2 and len(bl.lists.get("invoice_nos") or []) < 2)):
            unused(bl, f, [_model(it) for it in ci.items])
    for k, hits in list(extra.items()):           # the same wrong name is printed beside a model: part of that finding
        mine = next((v for (_m, x), v in bad.items() if x == k), None)
        if mine is not None:
            told = [d for (_m, x), v in bad.items() if x == k for d, _f, _s in v]      # its heading is reported already
            mine += [h for h in hits if not any(h[0] is d for d in told)]
            del extra[k]
    _nothing(ck, ci, "goods_full", want)
    _report(ck, "MASTER_NAME", bad, want)
    for hits in extra.values():
        ck.add(Finding("MASTER_NAME_EXTRA", "WARNING", _docs(hits), dict(name=hits[0][2]), hits[0][2],
                       " / ".join(dict.fromkeys(_text(x) for x in want.values())), _locs(hits)))


def _units(ck, ci, scs, co, bl, want):
    bad = {}

    def check(doc, m, u, f):
        ck.compared()
        if unit_key(u) != unit_key(want[m]):
            bad.setdefault((m, unit_key(u)), []).append((doc, f, str(u)))

    for doc, lines, _head, pl in _rows(ci, scs, co):
        head = doc.f.get("qty_unit") if doc is ci else None
        done = set()
        for it in lines:
            m = _model(it)
            if m not in want:
                continue
            u = _line_unit(it) or ((head.value, head) if head is not None and not pl else None)
            if u and (m, unit_key(u[0])) not in done:
                done.add((m, unit_key(u[0])))
                check(doc, m, *u)
    blk = _bl_block(bl, ci) if bl else None
    f = blk.unit if blk is not None else bl.f.get("bl_unit") if bl else None
    if f and len({unit_key(u) for u in want.values()}) == 1:      # one unit on the B/L for all goods of the invoice
        for m in want:
            check(bl, m, f.value, f)
    _nothing(ck, ci, "qty_unit", want)
    _report(ck, "MASTER_UNIT", bad, want)


def _nothing(ck, ci, field, want):
    if want and not ck.n_compared:
        ck.na(evidence="not_printed", field=field, doc=ci.name)
