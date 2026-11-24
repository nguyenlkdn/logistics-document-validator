"""Baseline regression test: every test set in tests/baseline must give exactly the approved findings + extracted data.

  python tests/run_baseline.py            # check (exit code 1 on any difference)
  python tests/run_baseline.py --update   # approve current output as the new baseline (after manual review!)
  python tests/run_baseline.py --update-checks   # approve the check statuses only (expected_checks.json)

Check statuses (LDV 2.3, engine/checks.py) are kept in their own file, expected_checks.json, so approving them never
touches the approved findings in expected.json. A set missing from one file is only reported for that file.
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
EXPECTED_CHECKS = BASE / "expected_checks.json"


def load_set(path: Path, tmp: Path) -> list:
    """Every document of a set as LDV reads it: PDFs and the sheets of Excel workbooks."""
    from engine import collect
    from engine.extract import EXCEL, load, load_excel
    docs = []
    for p in collect([path], tmp):
        if p.suffix.lower() in EXCEL:
            docs += load_excel(p, p.parent)
        elif p.suffix.lower() == ".pdf" and (d := load(p)):
            docs.append(d)
    return docs


def check_snapshot(zip_path: Path) -> list:
    """One line per check record: id | group | document | status | reason."""
    from engine.rules import validate_checks
    with tempfile.TemporaryDirectory() as tmp:
        _, checks = validate_checks(load_set(zip_path, Path(tmp)))
    return sorted(f"{c.check_id} | {c.group_id} | {c.doc} | {c.status} | {c.reason or ''}" for c in checks)


def compare_checks() -> int:
    current = {z.name: check_snapshot(z) for z in test_sets()}
    if "--update-checks" in sys.argv:
        EXPECTED_CHECKS.write_text(json.dumps(current, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"Check statuses approved: {EXPECTED_CHECKS}")
        return 0
    if not EXPECTED_CHECKS.exists():
        print("CHECKS  no expected_checks.json yet (approve with --update-checks after review)")
        return 0
    expected = json.loads(EXPECTED_CHECKS.read_text(encoding="utf-8"))
    failures = 0
    for name in sorted(set(expected) | set(current)):
        e, c = expected.get(name), current.get(name)
        if e == c:
            print(f"PASS  checks {name}  ({len(c)} records)")
            continue
        failures += 1
        print(f"FAIL  checks {name}")
        if e is None or c is None:
            print("   set missing from", "expected_checks.json" if e is None else "the test sets")
            continue
        for x in sorted(set(e) - set(c)):
            print(f"   - {x}")
        for x in sorted(set(c) - set(e)):
            print(f"   + {x}")
    return failures


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


def test_sets() -> list[Path]:
    """Every .zip and every folder holding PDFs (not specs/ or other helper folders, not an empty zip)."""
    import zipfile

    def zip_has_pdf(z):
        try:
            return any(n.lower().endswith(".pdf") for n in zipfile.ZipFile(z).namelist())
        except zipfile.BadZipFile:
            return False
    return [z for z in sorted(BASE.iterdir())
            if (z.suffix.lower() == ".zip" and zip_has_pdf(z)) or (z.is_dir() and any(z.rglob("*.pdf")))]


def main():
    from engine import master
    if (BASE / "master_hs.xlsx").exists():
        master.import_xlsx(BASE / "master_hs.xlsx")
    if not test_sets():
        print("No test sets in tests/baseline/ (confidential, kept outside git). See tests/baseline/README.md.")
        return 0
    if "--update-checks" in sys.argv:
        return compare_checks()
    current = {z.name: snapshot(z) for z in test_sets()}
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
    failures += compare_checks()
    print("RESULT:", "ALL PASS" if not failures else f"{failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
