"""Reader patterns: the layout variants LDV must read, each on a small made-up PDF (no real documents needed).

  python tests/run_reader.py          # exit code 1 on any failure

Every case here is a way of writing a value that LDV once read wrongly or not at all. When a new document shows
another variant, add it here first (it fails), then teach the reader (it passes). See docs/READING.md.
All names and numbers are invented (ACME, AB-X10…); never put values from real shipments in this file.
"""
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pymupdf                                                        # noqa: E402
from engine.extract import _vessel, column_models, load              # noqa: E402
from engine.pdftext import Line, Span                                 # noqa: E402
from engine.util import parse_date                                    # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="ldv_reader_"))
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


def pdf(name: str, rows: list, kind: str):
    """A one-page PDF: each row is a text line, or a list of (x, text) pieces on one line (a wide gap between
    pieces reads as a column break, like in the real documents). Returns the document as LDV reads it."""
    p = TMP / f"{name}.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 40
    for row in rows:
        for x, text in ([(40, row)] if isinstance(row, str) else row):
            page.insert_text((x, y), text, fontsize=8, fontname="helv")
        y += 13
    doc.save(p)
    return load(p, kind)


def lines(*texts):
    """Text lines without a PDF (for the helpers that only look at the text)."""
    return [Line(0, 10.0 * i, [Span(t, (40, 10 * i, 40 + 5 * len(t), 10 * i + 8), "helv", 8, 0, 0, (40, 10 * i))])
            for i, t in enumerate(texts)]


@test("vessel: 'V.', '/', 'VOY.', a space or a hyphenated voyage are the same vessel")
def _():
    same = ["ABC STAR V.0123-045A", "ABC STAR/ 0123-045A", "ABC STAR / V.0123-045A", "ABC STAR VOY. 0123-045A",
            "ABC STAR 0123-045A", "ABC STAR V.0123-045A,"]
    assert {_vessel(v) for v in same} == {("ABC STAR", "0123-045A")}, {_vessel(v) for v in same}


@test("dates: 21/11/2026, 21-NOV-2026, Nov 21, 2026, 21 November 2026 and 2026-11-21 are the same date")
def _():
    got = {parse_date(x) for x in ("21/11/2026", "21-NOV-2026", "21-Nov-2026", "Nov 21, 2026", "21 November 2026",
                                   "November 21, 2026", "2026-11-21")}
    assert len(got) == 1 and None not in got, got


@test("invoice: 'TOTAL CONTAINER : 1x40HQ,1x20GP' is 2 containers (every part is added)")
def _():
    for text, n in (("1x40HQ,1x20GP", 2), ("2 X 40'HC + 1 X 20'GP", 3), ("3x40HC", 3)):
        d = pdf("cntr", ["< COMMERCIAL INVOICE >", "INVOICE NO. ACME0000001   DATE : 01/02/2026",
                         f"TOTAL CONTAINER : {text}"], "CI")
        assert d.f["containers"].value == n, (text, d.f["containers"].value)


@test("shipping marks: a model whole on one line or split over two (before / after the colour code)")
def _():
    got = [f.value for f in column_models(lines("ACME", "AB-X10(W1)VN", "CD-Y20PE", "(BM)VN", "EF-Z30(BK)", "VN",
                                                "MADE IN NOWHERE"))]
    assert got == ["AB-X10(W1)VN", "CD-Y20PE(BM)VN", "EF-Z30(BK)VN"], got


@test("invoice marks: split models under SHIPPING MARK are read whole")
def _():
    d = pdf("ci_marks", ["< COMMERCIAL INVOICE >", "INVOICE NO. ACME0000001   DATE : 01/02/2026",
                         "SHIPPING MARK & NO.", "ACME", "AB-X10(W1)VN", "CD-Y20PE", "(BM)VN",
                         "-DETAILS AS PER ATTACHMENT (S)-"], "CI")
    assert [f.value for f in d.lists["marks_models"]] == ["AB-X10(W1)VN", "CD-Y20PE(BM)VN"], d.lists["marks_models"]


@test("Form D box 6 marks: whole-line and split models are all found")
def _():
    d = pdf("co_marks", ["FORM D", "ACME", "AB-X10(W1)VN", "CD-Y20PE", "(BM)VN", "EF-Z30(BK)", "VN"], "CO")
    got = sorted(f.value for f in d.lists["marks_models"])
    assert got == ["AB-X10(W1)VN", "CD-Y20PE(BM)VN", "EF-Z30(BK)VN"], got


@test("shipping marks: a model with a lowercase typo is still read, so the typo is reported")
def _():
    got = [f.value for f in column_models(lines("ACME", "AB-xX10(W1)VN", "CD-Y20pE", "(BM)VN"))]
    assert got == ["AB-xX10(W1)VN", "CD-Y20pE(BM)VN"], got
    d = pdf("co_marks_lc", ["FORM D", "ACME", "AB-X1a(W1)VN", "CD-Y20Pe", "(BM)VN"], "CO")
    got = sorted(f.value for f in d.lists["marks_models"])
    assert got == ["AB-X1a(W1)VN", "CD-Y20Pe(BM)VN"], got


@test("Form D total cartons: '(1,250) CARTON' on one line or 'CARTON***' on the next line")
def _():
    for rows in (["TOTAL : ONE THOUSAND TWO HUNDRED FIFTY (1,250) CARTON(S)***"],
                 ["TOTAL : ONE THOUSAND TWO HUNDRED FIFTY (1,250)", "CARTON***"]):
        d = pdf("co_total", ["FORM D"] + rows, "CO")
        assert d.f.get("total_ctn") and d.f["total_ctn"].value == 1250, rows
        assert d.f["total_ctn_words"].value == "ONE THOUSAND TWO HUNDRED FIFTY", d.f["total_ctn_words"]


B_L = ["[ Shipper ]", "ACME TRADING CO., LTD."]


@test("B/L: '1,251 CARTONS (1,251 SETS)' gives cartons and quantity; the total cartons come from the "
      "said-to-contain box even when the description line comes first")
def _():
    d = pdf("bl_qty", B_L + ["1251 CARTONS (1251 SETS)", "1,250 CARTONS", "ABCU1234567 // SEAL01 // 950 CARTONS // "
                             "12,290.00 KGS // 55.00 CBM"], "BL")
    assert d.f["bl_qty"].value == 1251 and d.f["bl_qty_ctn"].value == 1251, (d.f["bl_qty"], d.f["bl_qty_ctn"])
    assert d.f["bl_qty_phrase"].raw == "1251 CARTONS (1251 SETS)", d.f["bl_qty_phrase"].raw
    assert d.f["ctn"].value == 1250, d.f["ctn"]


@test("B/L attach sheet: cartons, KGS and CBM of a container row each have their own place")
def _():
    d = pdf("bl_attach", B_L + ["*1 ABCU1234567 // SEAL01 // 950 CARTONS // 12,290.00 KGS // 55.00 CBM",
                                "   DEFU7654321 // SEAL02 // 300 CARTONS // 3,900.00 KGS // 21.00 CBM"], "BL")
    rows = d.lists["cntr_load_parts"]
    assert [r["no"] for r in rows] == ["ABCU1234567", "DEFU7654321"], rows
    for r, (c, g, m) in zip(rows, ((950, 12290, 55), (300, 3900, 21))):
        assert (r["ctn"].value, r["gw"].value, r["cbm"].value) == (c, g, m), r
        for k, unit in (("ctn", "CARTONS"), ("gw", "KGS"), ("cbm", "CBM")):
            assert r[k].line.text[r[k].start:r[k].end].endswith(unit), (k, r[k].raw)


@test("B/L final destination: read when printed, marked 'not printed' when the B/L has none")
def _():
    d = pdf("bl_dest", B_L + ["FINAL DESTINATION : PORT A, NOWHERE"], "BL")
    assert d.f["final_dest"].value == "PORT A", d.f["final_dest"]
    d = pdf("bl_dest_lc", B_L + ["FINAL DESTINATION : Port b, NOWHERE"], "BL")      # not only in capitals
    assert d.f["final_dest"].value == "Port b", d.f["final_dest"]
    d = pdf("bl_nodest", B_L + ["SAID TO CONTAIN"], "BL")
    assert "final_dest" in (d.f["absent"].value if d.f.get("absent") else ""), d.f.get("absent")


# --- Typos: every one must give a finding; normal wording must give none (tools/typo_sweep.py checks real sets) ---
TYPOS = [  # (printed text, the mistyped word LDV must report, its correction)
    ("PORT OF DISCHARGE : PORT AlPHA", "AlPHA", "ALPHA"),        # lowercase letter in a capital word
    ("UNIT : SEtS", "SEtS", "SETS"),
    ("AB-xX10(W1)VN", "xX10", "XX10"),
    ("AB-Xx10(W1)VN", "Xx10", "XX10"),
    ("RICE COOKER 1.8l(AB)SERIES", "8l", "8L"),
    ("VESSEL : ABC STAR V.012n", "012n", "012N"),
    ("FREIGHT C0LLECT", "C0LLECT", "COLLECT"),                   # digit for a letter
    ("ORIGIN : NOWH3RE 1NDUSTRIES", "1NDUSTRIES", "INDUSTRIES"),
    ("DATE : 12/11/2O26", "12/11/2O26", "12/11/2026"),           # letter for a digit
    ("No. :   AC000000000001   I2/11/2026", "I2/11/2026", "12/11/2026"),
    ("TOTAL :   1,O43 CARTON(S)", "O43", "043"),
    ("NET 36.O0", "O0", "00"),
    ("P/O NO.AC00O000000001", "AC00O000000001", "AC000000000001"),
    ("FIVE HUNDRED (2S) CARTON(S)", "2S", "25"),
    ("ONE (I) CONTAINER(S) ONLY", "I", "1"),
    ("1,250 CARTON(5)", "5", "S"),
    ("CARTON I-1250   1,250 SET(S)", "I", "1"),
    ("Page : I of 2", "I", "1"),
    ("TOTAL CONTAINER : 1x4OHQ", "4O", "40"),
    ("TOTAL CONTAINER : 1x41HQ", "41", "40"),                    # no 41-foot container
    ("3X40'Hc", "Hc", "HC"),
    ("November I0, 2026", "I0", "10"),
    ("AMOUNT : U.5 Dollars", "5", "S"),
]
CLEAN = ["TOTAL CONTAINER : 1x40HQ,1x20GP", "2 X 40'HC + 1 X 20'GP", "AB-X10(S1)VN", "Factory : VietNam",
         "9.1This contract", "CARTON1-25   100 SET(S)", "By T/T 90 days", "No. 12, Street 15", "17th November",
         "1,250 CARTON(S) OF \"ACME\" BRAND", "INVOICE NO. ACME26110001   DATE : 12/11/2026", "Page : 1 of 2",
         "1,234.500 KGS   12.50 CBM", "U.S. Dollars", "ABCU1234567/ SEAL123/ 40HC", "ABC STAR V.0123-045A"]


@test("typos: a mistyped word is reported wherever it is, with its correction")
def _():
    from engine.rules_net import typo_words
    for text, word, fix in TYPOS:
        got = [(w, f) for _a, _b, w, _k, f in typo_words(text)]
        assert (word, fix) in got, (text, got)


@test("typos: normal wording of the documents gives no typo")
def _():
    from engine.rules_net import typo_words
    for text in CLEAN:
        got = [w for _a, _b, w, _k, _f in typo_words(text)]
        assert not got, (text, got)


@test("typos: a short doubtful word counts only when its correction is written elsewhere in the package")
def _():
    from engine.rules_net import typo_words
    assert not list(typo_words("459 PC5")) and [w for *_x, w, _k, _f in typo_words("459 PC5", frozenset({"PCS"}))]
    assert [f for *_x, f in typo_words("CAT LA1", frozenset({"LAI"}))] == ["LAI"]


@test("dates: an impossible or mistyped date is 'not understood' (no crash, no wrong date)")
def _():
    for s in ("2026-13-11", "31/02/2026", "21-NOV-2O26", "I2/11/2026", "I5-NOV-2026"):
        assert parse_date(s) is None, (s, parse_date(s))
    assert parse_date("12/11/2026").day == 12 and parse_date("15-NOV-2026").day == 15
    d = pdf("sc_baddate", ["SALES CONTRACT", "No. :   AC000000000001   12/11/2026", "4. SHIPMENT   By 21-NOV-2O26"], "SC")
    assert d.f["shipment_by"] is not None and d.f["shipment_by"].value is None, d.f.get("shipment_by")


if __name__ == "__main__":
    print("RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)
