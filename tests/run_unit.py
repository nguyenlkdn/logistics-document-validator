"""Checks for the review features around the engine (no browser needed):
stored session, cross-check, reviewer marks + trail, sign-off rule, report files, global search.

  python tests/run_unit.py          # exit code 1 on any failure

Uses the confidential test sets in tests/baseline (not in git); skips when they are absent.
Everything is written to temporary folders: the PC's real history, reports and HS list are not touched.
"""
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["LDV_DATA_DIR"] = tempfile.mkdtemp(prefix="ldv_unit_data_")
from engine import check, master, review_report, search, session   # noqa: E402
from engine.compare import compare                                   # noqa: E402
from engine.history import History                                   # noqa: E402

BASE = ROOT / "tests" / "baseline"
# A cross-check mismatch must be backed by a rule finding about the same thing (the comparison never contradicts
# the rules and never invents a problem they did not see).
FIELD_RULES = {
    "invoice_no": {"BL_INVOICE_EXTRA", "BL_INVOICE_MISSING", "CO_INVOICE_NO", "INVOICE_REF"},
    "invoice_date": {"CO_INVOICE_DATE"},
    "po": {"PL_HEADER", "SC_PO_EXTRA", "SC_PO_MISSING", "SC_PO_TYPO"},
    "vessel": {"PL_HEADER", "VESSEL"},
    "pol": {"INCOTERM", "PL_HEADER", "PORT_NAME"},
    "pod": {"BL_DESTINATION", "PL_HEADER", "PORT_NAME"},
    "sailing": {"DEPARTURE_DATE", "PL_HEADER"},
    "goods": {"BL_GOODS_DESC", "CO_GOODS_DESC", "PL_HEADER", "SC_GOODS_DESC"},
    "incoterm": {"INCOTERM", "PL_HEADER"},
    "hs": {"BL_HS_CODE", "BL_HS_MASTER", "CO_HS_MASTER", "HS_CODE"},
    "qty": {"BL_BLOCK", "BL_DESC_QTY", "BL_INVOICE_EXTRA", "BL_QTY", "CI_PL_QTY", "CO_QTY", "CO_SUM", "CO_TOTAL", "LINE_COUNT", "PL_TOTAL", "SC_VS_CI", "TOTAL_QTY"},
    "amount": {"CI_COVER_TOTAL", "CO_TOTAL", "SC_VS_CI", "TOTAL_AMOUNT"},
    "gw": {"BL_INVOICE_EXTRA", "BL_VS_PL", "PL_TOTAL"},
    "nw": {"PL_TOTAL"},
    "cbm": {"BL_INVOICE_EXTRA", "BL_VS_PL", "PL_TOTAL"},
    "ctn": {"BL_BLOCK", "BL_DESC_CTN", "BL_DESC_QTY", "BL_INVOICE_EXTRA", "BL_VS_PL", "CI_PL_CTN", "CO_PKG_COUNT", "CO_SUM", "CO_TOTAL", "PL_RANGE_TOTAL"},
    "containers": {"CNTR_COUNT", "CNTR_WORDS", "CONTAINERS", "PL_HEADER"},
    "final_dest": {"BL_DESTINATION"},
    "consignee": {"PARTY_NAME", "PL_HEADER"},
    "shipper": {"PARTY_NAME", "PL_HEADER"},
    "origin": {"ORIGIN", "PL_HEADER"},
    "currency": {"CURRENCY"},
    "payment": {"PAYMENT_TERMS", "PL_HEADER"},
    "freight": {"FREIGHT_TERM"},
}
FAILS = []


def test(name):
    def deco(fn):
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:                          # noqa: BLE001 — report every failure, keep going
            FAILS.append(name)
            print(f"FAIL  {name}: {e}")
            traceback.print_exc(limit=2)
        return fn
    return deco


def sets():
    """Same selection as run_baseline.test_sets(): zips holding PDFs and folders holding PDFs."""
    import zipfile

    def zip_has_pdf(z):
        try:
            return any(n.lower().endswith(".pdf") for n in zipfile.ZipFile(z).namelist())
        except zipfile.BadZipFile:
            return False
    return [z for z in sorted(BASE.iterdir())
            if (z.suffix.lower() == ".zip" and zip_has_pdf(z)) or (z.is_dir() and any(z.rglob("*.pdf")))]


def main():
    if not BASE.exists() or not sets():
        print("No test sets in tests/baseline/ (confidential, kept outside git).")
        return 0
    if (BASE / "master_hs.xlsx").exists():
        master.import_xlsx(BASE / "master_hs.xlsx")
    @test("vessel: the separator is a writing style (Form D 'V.', B/L '/'), a different voyage still differs")
    def _():
        from engine.extract import _vessel
        same = ["ABC STAR V.0123-045A, ", "ABC STAR/ 0123-045A", "ABC STAR / V.0123-045A", "ABC STAR V. 0123-045A",
                "ABC STAR VOY. 0123-045A", "ABC STAR VOYAGE NO. 0123-045A", "ABC STAR 0123-045A", "abc star/0123-045A"]
        got = {_vessel(v) for v in same}
        assert got == {("ABC STAR", "0123-045A")}, got
        assert _vessel("XY SEA V.12N") != _vessel("XY SEA / 12")
        assert _vessel("XY SEA V.12N") != _vessel("XY SEAS V.12N")

    tmp = Path(tempfile.mkdtemp(prefix="ldv_unit_"))
    hist = History(tmp / "history.db")
    runs = {}
    for z in sets():
        res = check([z], name=z.stem, out_root=tmp)
        runs[z.name] = (res, hist.record(res, "test"))

    @test("review.json: every document, finding, location and extracted value is stored and reloads")
    def _():
        for name, (res, _) in runs.items():
            s = session.load(res.out_dir)
            assert len(s["docs"]) == len(res.docs) and len(s["findings"]) == len(res.findings), name
            assert all("locs" in f for f in s["findings"]), name
            assert all(d["fields"] for d in s["docs"]), name
            assert all(Path(d["path"]).exists() for d in s["docs"]), name
            located = [f for f, rf in zip(s["findings"], res.findings) if rf.locs]
            assert all(f["locs"] for f in located), f"{name}: located finding without stored box"

    @test("cross-check: every mismatch is backed by a rule finding on the same subject")
    def _():
        for name, (res, _) in runs.items():
            keys = {f.key for f in res.findings}
            c = compare(session.load(res.out_dir))
            for row in c["rows"]:
                if row["result"] == "mismatch":
                    assert keys & FIELD_RULES[row["id"]], f"{name}: {row['id']} mismatch without a rule finding"
                for cell in row["cells"].values():
                    assert cell["state"] in ("value", "missing", "blank", "na", "nodoc")
            for line in c["lines"]:
                if line["result"] == "mismatch":
                    assert keys & {"CO_QTY", "CO_ITEMS", "SC_VS_CI", "CI_PL_QTY", "LINE_AMOUNT", "PL_LINE", "LINE_COUNT", "CO_MODEL"}, \
                        f"{name}: line {line['model']}"

    @test("reviewer marks: decisions are logged with who/when, unchanged decisions are not logged twice")
    def _():
        res, cid = next(iter(runs.values()))
        s = session.load(res.out_dir)
        f = s["findings"][0]
        assert hist.set_mark(s["shipment"], f["sig"], "in_review", "", who="T1")
        assert not hist.set_mark(s["shipment"], f["sig"], "in_review", "", who="T1")
        assert hist.set_mark(s["shipment"], f["sig"], "accepted", "ok by customer", who="T2")
        log = hist.log(s["shipment"], f["sig"])
        assert [(e["who"], e["old_status"], e["status"]) for e in log] == [("T2", "in_review", "accepted"),
                                                                           ("T1", "open", "in_review")]
        assert hist.marks(s["shipment"])[f["sig"]]["status"] == "accepted"
        assert any(x["sig"] == f["sig"] and x["status"] == "accepted" for x in hist.all_findings(check_id=cid))

    @test("sign-off: no plain approval while an error is open; exception and return need a reason")
    def _():
        open_err = lambda c: any(f["severity"] == "ERROR" and f["status"] in ("open", "in_review", "waiting")
                                 for f in hist.findings(c))
        cid = next(c for _, c in runs.values() if open_err(c))
        for result, note in (("approved", "x"), ("approved_exception", ""), ("returned", " ")):
            try:
                hist.sign(cid, result, note, who="T")
            except ValueError:
                pass
            else:
                raise AssertionError(f"{result} with note {note!r} was accepted")
        hist.sign(cid, "approved_exception", "customer accepted", who="T")
        so = hist.signoffs(cid)[0]
        assert so["result"] == "approved_exception" and so["open_errors"] > 0
        clean = next((c for _, c in runs.values() if not open_err(c)), None)
        if clean:
            hist.sign(clean, "approved", "", who="T")

    @test("report: PDF, Excel and HTML in EN / VI / both, with every section")
    def _():
        res, cid = next(iter(runs.values()))
        s = session.load(res.out_dir) | dict(revision=1)
        for lang, title in (("en", "Executive summary"), ("vi", "Tóm tắt"), ("both", "Tóm tắt")):   # no "fi": PDF ligature
            opts = dict(lang=lang, info=True, only_open=False, snapshots=True, crosscheck=True)
            for fmt in ("pdf", "xlsx", "html"):
                p = review_report.generate(s, hist, cid, opts, fmt)
                assert p.exists() and p.stat().st_size > 1000, p
                if fmt == "html":
                    assert title in p.read_text(encoding="utf-8"), (lang, title)
                if fmt == "pdf":
                    import pymupdf
                    with pymupdf.open(p) as d:
                        text = "".join(pg.get_text() for pg in d)
                    assert title in text and "1 / " in text, (lang, "pdf text")
        assert len(review_report.history(s)) == 9

    @test("search: finds a shipment, a document reference number and a finding ID")
    def _():
        idx = search.build(hist)
        res, cid = next(iter(runs.values()))
        s = session.load(res.out_dir)
        assert search.query(idx, s["shipment"])["reviews"], "shipment"
        f = s["findings"][0]
        fid = f"{s['shipment']}-R1-{f['no']:02d}"
        assert any(x["fid"] == fid for x in search.query(idx, fid)["findings"]), fid
        bl = next((d["fields"]["bl_no"]["value"] for d in s["docs"] if d.get("fields", {}).get("bl_no")), None)
        if bl:
            assert search.query(idx, bl)["refs"], "B/L no."
        assert not any(search.query(idx, "zzzz-no-such-thing").values())

    @test("B/L attach sheet: cartons, KGS and CBM of each container are boxed on their own text")
    def _():
        seen = 0
        for res, _cid in runs.values():
            for d in res.docs:
                for x in d.lists.get("cntr_load_parts", []):
                    seen += 1
                    for k, unit in (("ctn", "CARTON"), ("gw", "KGS"), ("cbm", "CBM")):
                        t = x[k].line.text[x[k].start:x[k].end]
                        assert unit in t and x[k].raw == t, f"{d.path.name} {x['no']} {k}: boxed '{t}'"
        assert seen, "no attach sheet in the test sets"

    @test("messages: one or several field names (@qty / @po) shown as labels in EN and VI")
    def _():
        from engine.rules import Finding
        for what, want in (("@qty", "quantity"), ("@qty / @po", "quantity / P/O"),
                           ("@model / @qty / @po", "model / quantity / P/O")):
            f = Finding("PL_LINE", "ERROR", [], dict(no=3, what=what), "", "")
            assert want in f.text("en"), f.text("en")
            assert "@" not in f.text("vi"), f.text("vi")

    print("RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
