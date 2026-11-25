"""Values that do not fit their column and go on in the next line ('EGS…/ SEAL/' + '40HC', 'WASHING' + 'MACHINE').

The readers read a value from one printed line. Where a document wraps it, a reader sees a cut value or none, and the rules
report a difference that is not there. Instead of teaching every reader every wrap, the whole package is looked at before
anything is reported (rules.validate_checks):

  1. places to look   the cells of a document that has an error or warning, or an input that was not read
  2. join             the cell is joined with the cell(s) right under it in the same column and the document is read again
  3. accept           only when (a) nothing that was read is lost: every value is the same, or is the same value completed,
                      and (b) the package has fewer problems: findings or unread inputs disappear, no check stops running

A document is never changed and no value is guessed: only text printed right under the cut value is added. A wrong value
stays a finding, because joining cannot make it right. Doc.joins lists the accepted joins.
"""
import re
from collections import Counter
from dataclasses import replace

from .pdftext import Line

MAX_ROWS = 3                      # rows of one value under its first row
MAX_JOINS = 12                    # per package
MAX_READS = 4000                  # documents read again per package: a package full of real errors stays fast
_CUT = re.compile(r"(?:[/\-‐‑–(&+=:]|\bNO\.?|\bOF)\s*$", re.I)
COUNTED = ("containers",)         # counted from the rows read: changes when a cut row is read
_REAL = ("ERROR", "WARNING")       # remarks (a word broken over two lines …) are no reason to join
_READ_AGAIN = {"field_not_found", "field_unreadable", "items_not_read", "items_not_comparable"}


def _below(lines: list, cell: Line) -> Line | None:
    """The cell right under this one in its column: one line pitch down, starting inside the cell above."""
    h = cell.bbox[3] - cell.bbox[1]
    x0, _y0, x1, y1 = cell.bbox
    best = None
    for l in lines:
        if l.page != cell.page or not 0 < l.y - (cell.bbox[1] + y1) / 2 < h * 1.9:
            continue
        for c in l.cells():
            if x0 - 4 <= c.bbox[0] <= x1 and c.bbox[1] > cell.bbox[1] + 2 and (best is None or c.y < best.y):
                best = c
    return best


def chains(lines: list, cell: Line) -> list:
    """[[cell, next], [cell, next, next2] …]: the cell with the cells under it."""
    out, chain = [], [cell]
    for _ in range(MAX_ROWS):
        nxt = _below(lines, chain[-1])
        if nxt is None:
            break
        chain = chain + [nxt]
        out.append(chain)
    return out


def join(lines: list, chain: list, sep: str = " ") -> list:
    """The lines with the cells of the chain moved behind its first cell. The pieces keep their place on the page."""
    first, rest = chain[0], chain[1:]
    moved = {id(s) for c in rest for s in c.spans}
    last = first.spans[-1]
    out = []
    for l in lines:
        spans = [s for s in l.spans if id(s) not in moved]
        if any(s is last for s in spans):
            tail = []
            for c in rest:
                prev = (tail or [last])[-1].text
                glue = "" if sep == "" or prev.endswith(" ") else sep
                tail += [replace(c.spans[0], text=glue + c.spans[0].text.lstrip())] + c.spans[1:]
            k = next(i for i, s in enumerate(spans) if s is last) + 1
            spans = spans[:k] + tail + spans[k:]
        elif len(spans) == len(l.spans):
            out.append(l)
            continue
        if spans:
            out.append(Line(l.page, l.y, spans))
    return out


def reads(d) -> dict:
    """Everything read from a document, by name; the goods rows as a list of dicts."""
    out = {}
    val = lambda v: getattr(v, "value", v)
    for k, v in d.f.items():
        if v is not None and k != "docs_required" and not k.startswith(("absent", "blank")):
            out[k] = val(v)
    for part in ("items", "pl_items"):
        if rows := getattr(d, part):
            out[part] = [{k: val(v) for k, v in it.items() if v is not None and not isinstance(v, (dict, list))} for it in rows]
    for k, v in d.lists.items():
        if k not in ("unparsed", "cntr_untyped") and v:
            out["lists", k] = [val(x) for x in v]
    return {k: v for k, v in out.items() if _figure(v) or v is None or _norm(v)}


def _norm(x) -> str:
    """The letters and digits of a value (Fields, dicts and tuples included)."""
    x = getattr(x, "value", x)
    if isinstance(x, dict):
        return "".join(_norm(v) for v in x.values())
    if isinstance(x, (list, tuple)):
        return "".join(_norm(v) for v in x)
    return re.sub(r"[^A-Z0-9]", "", str(x).upper()) if x is not None else ""


def _figure(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _goes_on(old, new) -> bool:
    """new is old, or old completed: text that goes on before or behind it. A figure is never changed."""
    if old is None or old == new or not _figure(old) and not _norm(old):
        return True
    if _figure(old) or _figure(new):
        return False
    a, b = _norm(old), _norm(new)
    return a == b or bool(a) and (b.startswith(a) or b.endswith(a))


def _rows_kept(old: list, new: list) -> bool:
    """Every goods row is still there, in its order; rows may come in between and texts may go on."""
    it = iter(new)
    return all(any(all(k in n and _goes_on(v, n[k]) for k, v in row.items()) for n in it) for row in old)


def _label(text, lines: list) -> bool:
    """A 'value' that is the label of the next column ('Port of Loading :   Port of Discharge : …')."""
    return isinstance(text, str) and len(text) > 3 and any(re.search(re.escape(text.strip()) + r"\s*:", l.text) for l in lines)


def _kept(old: dict, new: dict, lines: list = (), tail: str = "", beside: str = "") -> bool:
    """Everything read before is still read. A text may be completed; a text that was taken from the rest of a cut value
    (another field's) may be replaced when that rest is now read as the end of a longer value."""
    longer = [_norm(v) for k, v in new.items() if isinstance(v, str) and old.get(k) != v]
    for k, v in old.items():
        n = new.get(k)
        if n is None:
            if v is None or not _figure(v) and not _norm(v):
                continue
            return False
        if k in COUNTED or v == n:
            continue
        if k in ("items", "pl_items"):
            if not _rows_kept(v, n):
                return False
        elif isinstance(v, list):
            if _norm(v) and _norm(n).startswith(_norm(v)) and not any(_figure(x) for x in v):
                continue                              # the same text in fewer pieces, or going on
            rest = list(n)
            for x in v:
                hit = next((i for i, y in enumerate(rest) if y == x or _norm(y) == _norm(x)), None)
                if hit is None:
                    hit = next((i for i, y in enumerate(rest) if _goes_on(x, y)), None)
                if hit is None:
                    return False
                del rest[hit]
        elif not _goes_on(v, n) and not _label(v, lines):
            t, s = _norm(v), _norm(n)
            if not _figure(v) and t and beside.startswith(t) and s and tail.startswith(s):
                continue                              # the text of the next column had been read behind an empty label
            if not _figure(v) and s and t.startswith(s) and tail and t[len(s):] == tail:
                continue                              # the rest of a cut value had been read as the end of this one
            if _figure(v) or len(t) < 4 or not any(x != t and x.endswith(t) for x in longer):
                return False
    return True


def _problems(findings, checks):
    f = Counter((x.key, x.severity, tuple(x.doc_names[:1])) for x in findings if x.severity in _REAL)
    f.update((c.check_id, "internal_error") for c in checks if c.reason == "internal_error")
    ran = {(c.check_id, c.group_id, c.doc) for c in checks if c.status in ("PASS", "FAIL", "REVIEW_REQUIRED") or c.reason in ("blocked_by", "document_missing")
           or c.reason == "master_data_missing" and c.detail.get("what") in ("master_list", "model")
           or c.status == "NOT_APPLICABLE" and c.detail.get("evidence") != "not_printed"}
    blind = {(c.check_id, c.group_id, c.doc) for c in checks if c.status == "NOT_RUN" and c.reason in _READ_AGAIN}
    return f, ran, blind


def _gain(old: dict, new: dict) -> bool:
    """Only values that were not read before came in; all the others are the same."""
    def same(v, n):
        if not isinstance(v, list) or not isinstance(n, list):
            return v == n
        it = iter(n)
        return all(any(x == y for y in it) for x in v)
    return all(same(v, new.get(k)) for k, v in old.items())


def _better(old, new, gain: bool = False) -> bool:
    """gain: the join only brought in values that were not read before. Then their checks count, also when they find
    something: a wrapped value is checked like any other."""
    (f0, r0, b0), (f1, r1, b1) = old, new
    gone, came = sum((f0 - f1).values()), sum((f1 - f0).values())
    if r0 - r1:                                            # a check that ran must still run
        return False
    if gone > came:
        return True
    return (came == 0 or gain) and (len(r1) > len(r0) or len(b1) < len(b0))


def _places(d, findings, checks) -> list:
    """Cells of document d that may be the first row of a cut value: every cell of a document that has a finding or an
    input that was not read; the cells the findings point at first."""
    real = [f for f in findings if f.severity in _REAL]
    unread = any(c.status in ("NOT_RUN", "NOT_APPLICABLE") and any(i["doc"] == d.name and i["status"] != "READ" for i in c.inputs)
                 for c in checks)
    clips = [(l.page, l.clip) for f in real for l in f.locs if l.doc is d and l.clip]
    if not unread and not any(d is x for f in real for x in f.docs):
        return []

    def far(c):
        b = c.bbox
        return not any(p == c.page and q[0] < b[2] + 2 and q[2] > b[0] - 2 and q[1] < b[3] + 14 and q[3] > b[1] - 14
                       for p, q in clips)
    return sorted((c for l in d.lines for c in l.cells()), key=far)


def _again(d, lines):
    from .extract import load
    try:
        return load(d.path, d.kind, lines)
    except Exception:                                       # a layout no reader expects: not a better reading
        return None


def _candidates(d, cells, stop):
    """(cell, document read again) for every join that loses nothing and changes something."""
    old = reads(d)
    for cell in cells:
        beside = ""                                         # right of a label that has nothing behind it in its own cell
        if re.search(r":\s*$", cell.text):
            ln = next(l for l in d.lines if any(s is cell.spans[0] for s in l.spans))
            beside = _norm(" ".join(c.text for c in ln.cells() if c.bbox[0] > cell.bbox[2]))
        for chain in chains(d.lines, cell):
            for sep in ("", " ") if _CUT.search(cell.text) else (" ", ""):
                if stop():
                    return
                new = _again(d, join(d.lines, chain, sep))
                if new is not None and (now := reads(new)) != old and _kept(old, now, d.lines, _norm(" ".join(c.text for c in chain[1:])), beside):
                    yield cell, new, _gain(old, now) and not any(":" in c.text for c in chain[1:])


def heal(docs: list, run) -> tuple:
    """run(docs) -> (findings, checks) after re-reading the documents with their cut values joined, where that is
    certain (see the module text). The Docs are updated in place."""
    best = run(docs)
    left = [MAX_READS]
    known: dict = {}                                        # id(document) -> its candidates, until it changes

    def stop():
        left[0] -= 1
        return left[0] < 0
    for _ in range(MAX_JOINS):
        state, pick = _problems(*best), None
        for d in docs:
            if d.source_file or not d.lines or d.path.suffix.lower() != ".pdf" or not d.path.exists():
                continue
            if id(d) not in known:
                cells = _places(d, *best)
                if not cells:
                    continue
                known[id(d)] = list(_candidates(d, cells, stop))
            for cell, new, gain in known[id(d)]:
                keep = dict(d.__dict__)
                d.__dict__.update(new.__dict__)
                res = run(docs)
                d.__dict__.clear()
                d.__dict__.update(keep)
                now = _problems(*res)
                if _better(state, now, gain) and (pick is None or _score(now) > pick[0]):
                    pick = (_score(now), d, cell, new)
            if pick:
                break
        if not pick:
            break
        _s, d, cell, new = pick
        joins = d.joins + [(cell.page, cell.text)]
        d.__dict__.update(new.__dict__)
        d.joins = joins
        known.pop(id(d))
        best = run(docs)
    return best


def _score(p) -> tuple:
    """The best of several joins: the fewest problems, the most checks made, the fewest unread inputs."""
    return -sum(p[0].values()), len(p[1]), -len(p[2])
