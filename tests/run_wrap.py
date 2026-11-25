"""Wrap test: a value that does not fit its column and goes on in the next line must be read as if it had not wrapped.

  python tests/run_wrap.py [--step 40] [--list] [--raw]     # tests/baseline (confidential, local only): counts, field names

Every value LDV reads from a PDF is cut where a document program may break it - after a space, '/' or '-' inside the value,
between its label and the value, before its unit - and its tail is put on the next line of the same column (every step-th
such cut). The whole package is checked and compared with the package as printed:
  same      the same errors and warnings, the same checks made
  unread    a check could not be made (shown to the user, no false result)
  FALSE     an error or warning that is not there
  LOST      an error or warning that is there is not reported
"""
import copy
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["LDV_DATA_DIR"] = tempfile.mkdtemp(prefix="ldv_test_data_")
from engine import collect, extract                      # noqa: E402
from engine.extract import Field                         # noqa: E402
from engine import rules                                 # noqa: E402
from engine.pdftext import Line, Span                    # noqa: E402

BASE = Path(__file__).resolve().parent / "baseline"
RUN = rules._run_checks if "--raw" in sys.argv else rules.validate_checks      # --raw: without engine/unwrap.py


def _part(s: Span, a: int, b: int, x: float, dy: float) -> Span:
    """Characters a..b of a span, placed at x and moved down by dy."""
    w = (s.bbox[2] - s.bbox[0]) / max(len(s.text), 1)
    x0 = s.bbox[0] + w * a if x is None else x
    return Span(s.text[a:b], (x0, s.bbox[1] + dy, x0 + w * (b - a), s.bbox[3] + dy), s.font, s.size, s.color, s.flags,
                (x0, s.origin[1] + dy))


def _moved(s: Span, dy: float) -> Span:
    return Span(s.text, (s.bbox[0], s.bbox[1] + dy, s.bbox[2], s.bbox[3] + dy), s.font, s.size, s.color, s.flags,
                (s.origin[0], s.origin[1] + dy))


def wrap(lines: list, line: Line, at: int, mode: str, rows: set = frozenset()) -> list | None:
    """The lines with the cell of `line` that holds character `at` cut there; the tail goes to the next row.
    mode 'row': a new row (all that is below moves down); 'column': only this column moves down, up to its next gap;
    the rows of a goods table (rows: their lines) stay where they are."""
    k = next((i for i, l in enumerate(lines) if l is line), None)
    if k is None:
        return None
    line.text
    cell = next((c for c in line.cells() for s in c.spans if any(s is s2 and a < at <= b for a, b, s2 in line._offs)), None)
    if cell is None:
        return None
    pitch = max(s.size for s in cell.spans) * 1.15
    x = cell.bbox[0]
    head, tail, cur = [], [], x
    for a, b, s in line._offs:
        if not any(s is c for c in cell.spans):
            continue
        if b <= at:
            head.append(s)
        else:
            i = max(at - a, 0)
            if i > 0:
                head.append(_part(s, 0, i, None, 0))
            t = s.text[i:]
            i += len(t) - len(t.lstrip()) if not tail else 0
            p = _part(s, i, len(s.text), cur, pitch)
            tail.append(p)
            cur = p.bbox[2]
    if not head or not tail or not "".join(s.text for s in tail).strip():
        return None
    spans = [(l.page, s) for l in lines for s in l.spans if not any(s is c for c in cell.spans)]
    out = [(line.page, s) for s in head + tail]
    if mode == "row":
        for p, s in spans:
            below = p == line.page and (s.bbox[1] + s.bbox[3]) / 2 > line.y + 3
            out.append((p, _moved(s, pitch) if below else s))
    else:
        col, bottom = set(), cell.bbox[3]
        for l in lines[k + 1:]:
            for c in l.cells():
                if l.page == line.page and id(l) not in rows and abs(c.bbox[0] - x) < 4 and -3 < c.bbox[1] - bottom < pitch:
                    col |= {id(s) for s in c.spans}
                    bottom = c.bbox[3]
        if any(l.page == line.page and 0 < l.y - line.y < pitch * 1.6 and c.bbox[0] < x - 4 < c.bbox[2] for l in lines
               for c in l.cells()):
            return None                              # another column's text would be in the way
        for p, s in spans:
            out.append((p, _moved(s, pitch) if id(s) in col else s))
        if any(l.page == line.page and id(l) in rows and 0 < l.y - line.y < pitch * 5 for l in lines):
            return None                                  # inside a goods table the whole row moves: mode 'row'
        for p, s in out:                                 # the moved column must not run into other text: no document does
            for q, o in out:
                if p == q == line.page and s is not o and (any(s is t for t in tail) or id(s) not in {id(x) for _p, x in spans}) \
                        and abs(s.bbox[1] - o.bbox[1]) < 5 and s.bbox[0] < o.bbox[2] - 1 and o.bbox[0] < s.bbox[2] - 1:
                    return None
    return _lines(out)


def _lines(spans: list) -> list:
    out = []
    for pg in sorted({p for p, _ in spans}):
        rows = []
        for s in sorted((s for p, s in spans if p == pg), key=lambda s: ((s.bbox[1] + s.bbox[3]) / 2, s.bbox[0])):
            yc = (s.bbox[1] + s.bbox[3]) / 2
            if rows and abs(rows[-1].y - yc) <= max(2.0, s.size * 0.3):
                rows[-1].spans.append(s)
            else:
                rows.append(Line(pg, yc, [s]))
        for l in rows:
            l.spans.sort(key=lambda s: s.bbox[0])
        out += rows
    return out


def opt(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def goods_rows(d) -> set:
    return {id(f.line) for part in (d.items, d.pl_items) for it in part for f in it.values() if isinstance(f, Field)}


def places(d):
    """(name, line, start, end) of every value that has a place on the page."""
    seen = set()

    def one(name, f):
        if isinstance(f, Field) and f.end > f.start and f.line in d.lines:
            key = (id(f.line), f.start, f.end)
            if key not in seen:
                seen.add(key)
                yield name, f.line, f.start, f.end
    for k, f in d.f.items():
        yield from one(k, f)
    for part in ("items", "pl_items"):
        for it in getattr(d, part):
            for k, f in it.items():
                yield from one(f"{part}.{k}", f)
    for k, fs in d.lists.items():
        for f in fs or []:
            yield from one(f"lists.{k}", f)


def cuts(line: Line, a: int, b: int):
    t = line.text
    for i in range(a + 1, b):
        if t[i - 1] in " /-" and t[i:b].strip():
            yield "inside", i
    if a and t[:a].strip() and re.search(r"\S ?$", t[:a]) and not re.search(r"\s{3}$", t[:a]):
        yield "label", a
    m = re.search(r"[ /(]+(?=\S)", t[b:b + 12])          # the value's unit / bracket / next part, cut off from it
    if m and not t[b:].startswith("   "):
        yield "after", b + m.end()


def sets():
    return [z for z in sorted(BASE.iterdir()) if z.suffix == ".zip" or (z.is_dir() and z.name != "specs")]


def load_pdfs(z: Path, tmp: Path) -> list:
    """The documents of a set of PDFs; [] for a set with other files or with too many documents for this test."""
    files = collect([z], tmp)
    ds = [d for p in files if p.suffix.lower() == ".pdf" and (d := extract.load(p))]
    return ds if len(ds) == len(files) < 20 else []


def outcome(docs):
    fs, cs = RUN(docs)
    return (Counter((f.key, f.docs[0].name) for f in fs if f.severity in ("ERROR", "WARNING")),
            {(c.check_id, c.group_id, c.doc) for c in cs if c.status in ("PASS", "FAIL", "REVIEW_REQUIRED")})


def one_set(z: Path, step: int) -> list:
    """[(result, document kind, field, how, detail)] of every step-th wrap of a set."""
    out, n, first = [], 0, sum(map(ord, z.name)) % step           # the sets start at different wraps
    with tempfile.TemporaryDirectory() as tmp:
        ds = load_pdfs(z, Path(tmp))
        if not ds:
            return out
        want, done = outcome([copy.copy(d) for d in ds]), set()
        for di, d in enumerate(ds):
            for name, line, a, b in list(places(d)):
                for how, i in cuts(line, a, b):
                    for mode in ("row", "column"):
                        if (id(line), i, mode) in done:
                            continue
                        done.add((id(line), i, mode))
                        n += 1
                        if n % step != first:
                            continue
                        new = wrap(d.lines, line, i, mode, goods_rows(d))
                        if new is None:
                            continue
                        try:
                            docs = [copy.copy(x) for x in ds]
                            docs[di] = extract.load(d.path, d.kind, new)
                            got = outcome(docs)
                        except Exception as e:
                            got = (Counter({(f"crash {type(e).__name__}", ""): 1}), set())
                        false, lost, blind = got[0] - want[0], want[0] - got[0], want[1] - got[1]
                        r = "FALSE" if false else "LOST" if lost else "unread" if blind else "same"
                        out.append((r, d.kind + (d.form if d.kind == "CO" else ""), name, how,
                                    f"{z.name[-14:]} {mode} n={n} at={i} doc={di} | {sorted(k for k, _ in false)} "
                                    f"{sorted(k for k, _ in lost)} {sorted({k for k, _, _ in blind})[:6]}"))
    return out


def main() -> int:
    from concurrent.futures import ProcessPoolExecutor
    step, total, fails = int(opt("--step", "40")), Counter(), defaultdict(Counter)
    with ProcessPoolExecutor() as pool:
        for rows in pool.map(one_set, sets(), [step] * len(sets())):
            for r, kind, name, how, detail in rows:
                total[r] += 1
                if r != "same":
                    fails[kind, name, how][r] += 1
                    if "--list" in sys.argv:
                        print(r, kind, name, how, detail, flush=True)
    print(sum(total.values()), "wraps:", dict(total))
    for k, c in sorted(fails.items(), key=lambda x: (-x[1]["FALSE"], -x[1]["LOST"], -x[1]["unread"])):
        print("  ", *k, dict(c))
    return 1 if total["FALSE"] or total["LOST"] else 0


if __name__ == "__main__":
    sys.exit(main())
