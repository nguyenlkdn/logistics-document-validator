"""Find values LDV did not read although they are printed in the PDF (developer tool).

  python tools/find_unread.py tests/baseline/SET.zip [more sets…]

For every Cross-check cell shown as "not read" (yellow) or "not printed" (·), the values the other documents give
for that row are looked for in the text of the document, in the usual ways of writing them (dates as 21/11/2026,
21-NOV-2026, 21 Nov…; numbers with and without thousands separators; the first words of names). A hit means:

  [missing]  LDV expected the value on this document and the text is there → most likely a reading gap: add the
             layout to tests/run_reader.py and teach engine/extract*.py (see docs/READING.md).
  [na]       the label was not found on this document, but the value appears somewhere in it. Often a different
             thing that happens to look the same (a buyer address with the port city, a contract deadline equal to
             the sailing date); sometimes a field written under another label. Read the line to decide.
"""
import datetime
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import check, compare                                  # noqa: E402

MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
          "NOVEMBER", "DECEMBER"]


def variants(v, typ: str) -> set:
    """The ways a value can be printed."""
    v = str(v).strip()
    if typ == "date" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        try:
            d = datetime.date.fromisoformat(v[:10])
        except ValueError:
            return {v.upper()}
        m = MONTHS[d.month - 1]
        out = {f"{d:%d/%m/%Y}", f"{d.day}/{d.month}/{d.year}", f"{d:%Y-%m-%d}", f"{d.day} {m[:3]}",
               f"{d.day:02d}-{m[:3]}-{d.year}", f"{d.day}-{m}-{d.year}", f"{m} {d.day}", f"{m[:3]} {d.day}",
               f"{d.day} {m}", f"{d:%d.%m.%Y}"}
        return {x.upper() for x in out}
    if typ == "number":
        try:
            n = float(v.replace(",", ""))
        except ValueError:
            return {v}
        if n < 10:                                      # too short: would match anywhere
            return set()
        out = {f"{n:,.0f}", f"{n:.0f}"} if n == int(n) else set()
        return out | {f"{n:,.2f}", f"{n:,.3f}", f"{n:.2f}", f"{n:.3f}"}
    w = re.sub(r"[^A-Z0-9 ]", " ", v.upper()).split()
    if typ == "party":
        return {" ".join(w[:3])} if len(w) >= 3 else set()
    if typ == "vessel":
        return {" ".join(w[:2])} if w else set()
    if typ == "hs":
        return {re.sub(r"\D", "", v)[:4]}
    return {" ".join(w)} if w else set()


def scan(path: Path, out_root: Path) -> list:
    res = check([path], out_root=out_root, with_evidence=False)
    s = json.loads((res.out_dir / "review.json").read_text(encoding="utf-8"))
    text = {d.name: (d.kind, [l.text for l in d.lines]) for d in res.docs}
    hits = []
    for r in compare.compare(s)["rows"]:
        vals = set()
        for cell in r["cells"].values():
            if cell.get("state") == "value":
                for a in cell["raw"]:
                    vals |= variants(a, r["type"])
        vals = {x for x in vals if len(x) >= 3}
        if not vals:
            continue
        for col, cell in r["cells"].items():
            if cell["state"] not in ("na", "missing"):
                continue
            kind = "CI" if col == "PL" else col           # the packing list is the second part of the invoice file
            for name, (k, lines) in text.items():
                if k != kind:
                    continue
                for ln in lines:
                    hit = next((x for x in vals if x in re.sub(r"\s+", " ", ln.upper())), None)
                    if hit:
                        hits.append((cell["state"], r["id"], col, name, hit, ln.strip()))
                        break
    return sorted(hits, key=lambda h: h[0] != "missing")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="ldv_unread_"))
    found = 0
    for a in sys.argv[1:]:
        print(f"\n## {Path(a).name}")
        hits = scan(Path(a), tmp)
        found += sum(h[0] == "missing" for h in hits)
        for state, row, col, name, hit, ln in hits:
            print(f"  [{state:7}] {row:12} {col:3} {name[:32]:32} '{hit}' in: {ln[:100]}")
        if not hits:
            print("  nothing: every printed value was read")
    print(f"\n{found} value(s) printed but not read ([missing]).")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
