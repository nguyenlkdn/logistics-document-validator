"""Baseline regression test: every test set in tests/baseline must give exactly the approved findings + extracted data.

  python tests/run_baseline.py            # check (exit code 1 on any difference)
  python tests/run_baseline.py --update   # approve current output as the new baseline (after manual review!)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Never use the real HS master of this PC: the tests get their own data folder, with the test copy
# tests/baseline/master_hs.xlsx when present (confidential, ignored by git like the other test data).
os.environ["LDV_DATA_DIR"] = tempfile.mkdtemp(prefix="ldv_test_data_")
from engine import check                      # noqa: E402
from engine.report import plain                # noqa: E402

BASE = Path(__file__).resolve().parent / "baseline"
EXPECTED = BASE / "expected.json"


def snapshot(zip_path: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        res = check([zip_path], name=zip_path.stem, out_root=Path(tmp))
        evidence_ok = all(f.evidence or not f.locs for f in res.findings)
    return {
        "findings": sorted(f"{f.severity} | {f.key} | {f.doc_names[0]} | p{f.page} | {f.current} -> {f.suggested}"
                           for f in res.findings),
        "extracted": {d.name: {k: plain(v) for k, v in d.f.items()} | {
            "items": [{k: plain(v) for k, v in it.items()} for it in d.items],
            "pl_items": [{k: plain(v) for k, v in it.items()} for it in d.pl_items]} for d in res.docs},
        "unrecognised": [f"{u['doc']}: {u['what']}" for u in res.unrecognised],
        "evidence_for_every_located_finding": evidence_ok,
    }


def main():
    from engine import master
    if (BASE / "master_hs.xlsx").exists():
        master.import_xlsx(BASE / "master_hs.xlsx")
    if not any(z.suffix.lower() == ".zip" or z.is_dir() for z in BASE.iterdir()):
        print("No test sets in tests/baseline/ (confidential, kept outside git). See tests/baseline/README.md.")
        return 0
    current = {z.name: snapshot(z) for z in sorted(BASE.iterdir()) if z.suffix.lower() == ".zip" or z.is_dir()}
    if "--update" in sys.argv:
        EXPECTED.write_text(json.dumps(current, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"Baseline updated: {EXPECTED}")
        return 0
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(current, default=str))
    failures = 0
    for name in sorted(set(expected) | set(current)):
        e, c = expected.get(name), current.get(name)
        if e == c:
            print(f"PASS  {name}  ({len(c['findings'])} findings)")
            continue
        failures += 1
        print(f"FAIL  {name}")
        if not e or not c:
            print("   pack missing from", "expected" if not e else "current")
            continue
        for k in e:
            if e[k] != c.get(k):
                if isinstance(e[k], list):
                    for x in sorted(set(map(str, e[k])) - set(map(str, c.get(k, [])))):
                        print(f"   - missing  [{k}] {x}")
                    for x in sorted(set(map(str, c.get(k, []))) - set(map(str, e[k]))):
                        print(f"   + new      [{k}] {x}")
                else:
                    print(f"   ~ changed  [{k}]")
    print("RESULT:", "ALL PASS" if not failures else f"{failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
