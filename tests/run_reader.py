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
from engine.extract import _vessel, column_models, load, load_excel              # noqa: E402
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


@test("totals: other documents are compared with what the lines add up to, not a wrong TTL row")
def _():
    from engine.extract import Doc, Field
    from engine.rules import Finding, r_bl_vs_pl, r_co_packages, true_total   # noqa: F401
    ln = lines("x")[0]
    fld = lambda v, raw=None: Field(v, raw or f"{v:,}", ln, 0, 0)

    def ci(ttl_ctn, rng=(1, 500), pl_qty=500.0, gw=6500.0, nw=6000.0):
        d = Doc(Path("ci.pdf"), "CI", [ln], 600, False)
        d.items = [dict(model="AB-X10", qty=fld(500.0, "500"), price=fld(10.0, "10.00"), amount=fld(5000.0, "5,000.00"))]
        d.pl_items = [dict(model="AB-X10", ctn=rng[1] - rng[0] + 1, ctn_f=fld(rng[1] - rng[0] + 1), rng=rng,
                           qty=fld(pl_qty, "500"), nw=fld(nw, "6,000.00"), gw=fld(gw, "6,500.00"), cbm=fld(25.0, "25.00"))]
        d.f = dict(pl_total_ctn=fld(float(ttl_ctn), f"{ttl_ctn:,}"), pl_total_qty=fld(500.0, "500"),
                   total_qty=fld(500.0, "500"), total_amount=fld(5000.0, "5,000.00"),
                   pl_total_gw=fld(6500.0, "6,500.00"), pl_total_nw=fld(6000.0, "6,000.00"))
        return d
    assert true_total(ci(504), "ctn").value == 500                     # TTL 504 under CARTON 1-500: the lines win
    assert true_total(ci(500), "ctn").raw == "500"                     # TTL agrees: the TTL itself
    assert true_total(ci(504, rng=(1, 400)), "ctn").value == 400
    assert true_total(ci(504, rng=(0, 499)), "ctn").value == 504       # ranges not 1..n: lines are no truth
    assert true_total(ci(504, pl_qty=400.0), "ctn").value == 504       # PL lines ≠ invoice lines: printed TTL
    assert true_total(ci(500, gw=5000.0), "gw").value == 6500.0        # a line with G.W. < N.W.: printed TTL
    bl = Doc(Path("bl.pdf"), "BL", [ln], 600, False)
    bl.f = dict(ctn=fld(500.0, "500"))
    out = []
    r_bl_vs_pl(ci(504), bl, out)
    assert not [f for f in out if f.key == "BL_VS_PL"], out            # the B/L agrees with the lines: no finding



# ---- P2 value grammar (2026-11-19): layouts of an FOC parts invoice / a contract that were misread. Invented values.
@test("invoice: '357.00 PCS' total is 357 (not '00'), 'CARTON (S)' with a space, hyphenated invoice no. + bare date")
def _():
    d = pdf("p2_ci", [
        "<   INVOICE   >",
        [(40, "INVOICE NO. ABC26-XYZ021"), (300, "05/10/2026")],
        "SAILING ON/OR ABOUT: 14/10/2026",
        [(40, "1"), (60, "PART PLATE AB-100"), (300, "12"), (330, "PCS"), (380, "0.25"), (440, "3.00")],
        [(40, "1"), (60, "LABEL CD-200"), (300, "345"), (330, "PCS"), (380, "0.08"), (440, "27.60")],
        [(40, "TTL:"), (80, "1 CARTON (S)"), (300, "357.00"), (360, "PCS"), (400, "USD"), (440, "30.60")],
        "<   PACKING LIST   >",
        [(40, "INVOICE NO. ABC26-XYZ021"), (300, "05/10/2026")],
        [(40, "TTL:"), (80, "1 CARTON (S)"), (200, "357 PCS"), (300, "4.926"), (360, "6.380"), (420, "0.481")]], "CI")
    assert d.f["invoice_no"].value == "ABC26-XYZ021", d.f["invoice_no"]
    assert str(d.f["invoice_date"].value) == "2026-10-05", d.f["invoice_date"]
    assert str(d.f["sailing"].value) == "2026-10-14", d.f["sailing"]
    assert d.f["total_qty"].value == 357.0 and d.f["total_qty"].raw == "357.00", d.f["total_qty"]
    assert d.f["total_amount"].value == 30.60
    assert [it["qty"].value for it in d.items] == [12.0, 345.0]
    assert d.f["pl_total_ctn"].value == 1.0, d.f.get("pl_total_ctn")
    assert d.f["pl_total_qty"].value == 357.0 and d.f["pl_total_cbm"].value == 0.481
    assert [str(h["date"].value) for h in d.lists["headers"]] == ["2026-10-05", "2026-10-05"], d.lists["headers"]


@test("B/L: hyphenated invoice numbers in the invoice list")
def _():
    d = pdf("p2_bl", ["[ Shipper ]", "ACME CO., LTD.", "INVOICE NO. ACME26110001", "INVOICE NO. ABC26-XYZ021"], "BL")
    assert [f.value for f in d.lists["invoice_nos"]] == ["ACME26110001", "ABC26-XYZ021"], d.lists["invoice_nos"]


@test("contract: 'FOB PORT A,COUNTRY' (comma, no space) is the place PORT A")
def _():
    from engine.extract import _fob_all
    got = [f.value for f in _fob_all(lines('"ACME" BRAND RICE COOKER   FOB PORT A,THAILAND', "FOB PORT B, VIETNAM",
                                            "FOB PORT C   IN USD", "and FOB price where RVC is applied"))]
    assert got == ["PORT A", "PORT B", "PORT C"], got



# ---- P3 columns / cargo blocks / parties (2026-11-19). Invented values.
@test("B/L: two cargo blocks next to the shipping-mark column, one per invoice")
def _():
    d = pdf("p3_bl", [
        "[ Shipper ]", "ACME CO., LTD.",
        [(40, "ACME/BUYER"), (200, '"ACME" BRAND RICE COOKER')],
        [(40, "MADE IN THAILAND"), (200, "#HS CODE 8516")],
        [(40, "BUYER"), (200, "500 CARTON(S) 500 PCS")],
        [(40, "VIETNAM"), (200, "INVOICE NO. ACME26110001")],
        [(40, "CARTON BOX"), (200, '"SPARE PARTS OF RICE COOKER"')],
        [(40, "C/NO. 1/1"), (200, "#HS CODE 3926")],
        [(200, "1 CARTON(S)  120 PCS")],
        [(200, "INVOICE NO. ABC26-XYZ021")]], "BL")
    got = [(b.goods.value if b.goods else None, b.hs.value if b.hs else None, b.ctn.value, b.qty.value, b.unit.value,
            b.invoice.value) for b in d.cargo_blocks]
    assert got == [('"ACME" BRAND RICE COOKER', "8516", 500.0, 500.0, "PCS", "ACME26110001"),
                   ('"SPARE PARTS OF RICE COOKER"', "3926", 1.0, 120.0, "PCS", "ABC26-XYZ021")], got
    assert (d.f["bl_qty"].value, d.f["bl_qty_ctn"].value, d.f["bl_unit"].value) == (620.0, 501.0, "PCS")


@test("invoice: consignee label without colon or space; shipper from its label, not from a signature beside the marks")
def _():
    d = pdf("p3_ci", [
        "<   INVOICE   >",
        "SHIPPER : ACME TRADING (THAILAND) CO., LTD.",
        "CONSIGNEEBUYER VIETNAM CO., LTD.",
        "INVOICE NO. ACME26110001",
        [(40, "SHIPPING MARK & NO."), (300, "ACME TRADING")],
        [(40, "VIETNAM"), (300, "(THAILAND) CO., LTD.")]], "CI")
    assert d.f["consignee"].value == "BUYER VIETNAM CO., LTD.", d.f["consignee"]
    assert d.f["shipper"].value == "ACME TRADING (THAILAND) CO., LTD.", d.f["shipper"]



# ---- P4 cartons / part numbers / FOC goods (2026-11-19). Invented values.
@test("packing list: lines in one shared carton print qty + N.W. only; part numbers; quoted goods name")
def _():
    from engine.rules import true_total, validate
    d = pdf("p4_ci", [
        "<   INVOICE   >",
        [(40, "INVOICE NO. ABC26-XYZ021"), (300, "05/10/2026")],
        "F.O.C",
        '   "SPARE PARTS OF RICE COOKER"   NO COMMERCIAL VALUE',
        [(40, "1"), (60, "Inner Lid Plate"), (300, "12"), (330, "PCS"), (380, "0.25"), (440, "3.00")],
        "100000000001@AB",
        [(40, "1"), (60, "RATING LABEL"), (300, "40"), (330, "PCS"), (380, "0.05"), (440, "2.00")],
        "100000000002@AB",
        [(40, "TTL:"), (80, "1 CARTON (S)"), (300, "52.00"), (360, "PCS"), (400, "USD"), (440, "5.00")],
        "<   PACKING LIST   >",
        [(40, "INVOICE NO. ABC26-XYZ021"), (300, "05/10/2026")],
        '   "SPARE PARTS OF RICE COOKER"   NO COMMERCIAL VALUE',
        [(40, "CARTON/NO.1-1"), (120, "Inner Lid Plate"), (300, "12 PCS"), (360, "1.20"), (420, "2.40"), (480, "0.050")],
        "100000000001@AB",
        [(120, "RATING LABEL"), (300, "40 PCS"), (360, "0.04")],
        "100000000002@AB",
        [(40, "TTL:"), (80, "1 CARTON (S)"), (200, "52 PCS"), (300, "1.24"), (360, "2.40"), (420, "0.050")]], "CI")
    assert len(d.pl_items) == 2 and len(d.packages) == 1, (d.pl_items, d.packages)
    pk = d.packages[0]
    assert (pk.rng, pk.ctn, pk.gw.value, pk.cbm.value, pk.lines) == ((1, 1), 1, 2.40, 0.050, [0, 1]), pk
    assert d.pl_items[1]["gw"] is None and d.pl_items[1]["nw"].value == 0.04       # no G.W. of its own, not zero
    assert [(i.kind, i.value, i.category) for i in d.item_ids] == [("part_no", "100000000001@AB", "part"),
                                                                   ("part_no", "100000000002@AB", "label")], d.item_ids
    assert d.f["goods"].value == "SPARE PARTS OF RICE COOKER", d.f["goods"]
    assert d.f["pl_goods_full"].value == "SPARE PARTS OF RICE COOKER", d.f.get("pl_goods_full")
    assert true_total(d, "gw").value == 2.40 and true_total(d, "nw").value == 1.24 and true_total(d, "ctn").value == 1
    keys = {f.key for f in validate([d])}
    for k in ("PL_TOTAL", "LINE_COUNT", "CI_PL_QTY", "PL_GW_NW", "PL_LINE", "CI_COVER_TOTAL", "TOTAL_QTY"):
        assert k not in keys, (k, keys)
    d.pl_items[1]["nw"] = d.pl_items[1]["nw"].__class__(4.0, "4.00", d.pl_items[1]["nw"].line, 0, 0)   # carton too light
    assert "PL_GW_NW" in {f.key for f in validate([d])}, "a carton lighter than its lines must be reported"



@test("model with a hyphenated suffix after the colour code: EF-Z30-PQ(06)-MG is read whole (2026-11-19)")
def _():
    import re
    from engine.extract import MODEL_RE, _co_item_details
    assert re.search(MODEL_RE, "  EF-Z30-PQ(06)-MG   ")[0] == "EF-Z30-PQ(06)-MG"
    assert re.search(MODEL_RE, "AB-X10(W1)VN  100 SETS")[0] == "AB-X10(W1)VN"                 # unchanged
    assert [f.value for f in column_models(lines("EF-Z30-PQ(06)-MG", "AB-X10(W1)VN", "CD-Y20-PQ", "(52)-MG"))] == \
        ["EF-Z30-PQ(06)-MG", "AB-X10(W1)VN", "CD-Y20-PQ(52)-MG"]
    d = pdf("model_suffix_ci", [
        "< COMMERCIAL INVOICE >",
        [(40, "INVOICE NO. ACME26110001"), (300, "DATE : 01/11/2026")],
        [(40, "1. P/O NO.PR123456789012"), (200, "EF-Z30-PQ(06)-MG"), (330, "64"), (360, "SET(S)"), (420, "212.50"),
         (480, "13,600.00")]], "CI")
    assert [it["model"] for it in d.items] == ["EF-Z30-PQ(06)-MG"], d.items



@test("Form D: box 6 model split at a hyphen ('EF-Z30-' / 'PQ(06)-MG'); box 7 model wrapped after a hyphen")
def _():
    from engine.extract import _co_item_details
    import pymupdf
    from engine.extract_net import _hyphen_split
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text((65, 380), "EF-Z30-", fontsize=8, fontname="helv")
    pg.insert_text((65, 390), "PQ(06)-MG", fontsize=8, fontname="helv")
    pg.insert_text((200, 380), "ONE HUNDRED (100) CARTON(S)", fontsize=8, fontname="helv")
    got = _hyphen_split(pg)
    assert [g[:2] for g in got] == [("EF-Z30-", "PQ(06)-MG")], got
    assert got[0][2][0] == 65 and got[0][2][3] > got[0][2][1] + 12, got        # a box over both lines
    blk = lines("1   HS. CODE. 8418.10.32", "MODEL: EF-Z30-", "PQ(06)-MG ***")
    blk[0].spans[0].text = "HS. CODE. 8418.10.32"
    for l in blk[1:]:
        l.spans[0] = l.spans[0].__class__(l.spans[0].text, (blk[0].spans[0].bbox[0] + 1,) + l.spans[0].bbox[1:],
                                          "helv", 8, 0, 0, l.spans[0].origin)
    assert _co_item_details(blk)["model"] == "EF-Z30-PQ(06)-MG", _co_item_details(blk)



@test("invoice amount in words over three lines (… AND FORTY FIVE / CENTS ONLY) is read whole")
def _():
    from engine.util import words_to_number
    d = pdf("words3_ci", [
        "< COMMERCIAL INVOICE >",
        [(40, "INVOICE NO. ACME26110001"), (300, "DATE : 01/11/2026")],
        "SAY TOTAL U.S. DOLLARS ONE HUNDRED AND TWELVE",
        "THOUSAND FOUR HUNDRED AND SIXTY ONE  AND FORTY FIVE",
        "CENTS ONLY",
        [(40, "TOTAL"), (300, "USD 112,461.45")]], "CI")
    assert d.f["amount_words"].value.rstrip().endswith("CENTS ONLY"), d.f["amount_words"].value
    assert words_to_number(d.f["amount_words"].value) == 112461.45


@test("Form D box 7: wrong carton words are boxed on the words, not on the figure")
def _():
    from engine.extract import _co_item_details
    blk = lines("1   HS. CODE. 8418.10.31", "SEVENTY (140) CARTON(S) OF \"ACME\" BRAND", "REFRIGERATOR", "( 1 CARTON = 1 SET)",
                "MODEL: AB-X10(W1)VN ***")
    blk[0].spans[0].text = "HS. CODE. 8418.10.31"
    x0 = blk[0].spans[0].bbox[0]
    for l in blk[1:]:
        l.spans[0] = l.spans[0].__class__(l.spans[0].text, (x0 + 1,) + l.spans[0].bbox[1:], "helv", 8, 0, 0, l.spans[0].origin)
    det = _co_item_details(blk)
    w = det.get("_words_f")
    assert det["pkg_words"] == "SEVENTY" and w is not None and w.line.text[w.start:w.end] == "SEVENTY", det



@test("invoice 'TOTAL CONTAINER :' printed with nothing after it is a blank, not unread; cross-check shows it")
def _():
    from engine.compare import _cell
    d = pdf("blank_cntr_ci", [
        "< COMMERCIAL INVOICE >",
        [(40, "INVOICE NO. ACME26110001"), (300, "DATE : 01/11/2026")],
        "TOTAL CONTAINER : ",
        "FREIGHT COLLECT"], "CI")
    assert d.f.get("containers") is None and d.f.get("blank:containers") is not None, d.f.get("blank:containers")
    doc = dict(name="ci.pdf", fields={"blank:containers": dict(value="TOTAL CONTAINER", page=1)})
    c = _cell([doc], "containers", "number")
    assert c["state"] == "blank" and c["label"] == "TOTAL CONTAINER" and c["page"] == 1, c


def _workbook(path, charges=True, split_pl=True, blank_shipment=False):
    """An invented invoice / packing list / contract workbook (sheet layout like a supplier's Excel CIPL)."""
    import openpyxl
    wb = openpyxl.Workbook()
    inv = wb.active
    inv.title = "Inv."
    inv["B1"] = "ACME TRADING CO., LTD."
    inv["A8"], inv["B8"], inv["G8"], inv["H8"] = "Messrs:", "Buyer Vietnam Co.,Ltd.", "Invoice No.:", "ACME26110001X"
    inv["G10"], inv["H10"] = "Date:", "2026-11-01"
    inv["A12"], inv["B12"] = "Term of Payment:", "OA 30 days after B/L Date"
    inv["A13"], inv["B13"] = "PORT OF DISCHARGE:", "PORT ALPHA,NOWHERE"
    inv["A14"], inv["B14"], inv["G14"], inv["H14"], inv["I14"] = "Mark & No.", "Description of Goods", "Quantity\nSETS", "Unit Price \nUSD", "Amount\nUSD"
    inv["A16"], inv["B16"], inv["G16"] = "N/M", "ACME FAN AND ACME HEATER", "CIF PORT ALPHA,NOWHERE"
    inv["B18"] = "MODEL NO."
    inv["B19"], inv["G19"], inv["H19"], inv["I19"] = "AB-X10(W1)", 100, "10.00", 1000
    inv["B20"], inv["G20"], inv["H20"], inv["I20"] = "CD-Y20", 50, "20.50", 1025
    inv["B21"], inv["G21"], inv["H21"], inv["I21"] = "AB-X10(W1)", 30, "10.00", 300
    total = 2325
    if charges:
        inv["B22"], inv["I22"] = "Freight", 100
        inv["B23"], inv["I23"] = "Insurance", 25.5
        total += 125.5
    inv["B30"] = "Country of origin: Nowhere"
    inv["B32"] = "SAY TOTAL U.S. DOLLARS TWO THOUSAND FOUR HUNDRED FIFTY AND CENTS FIFTY ONLY"
    inv["G34"], inv["H34"], inv["I34"] = "TOTAL AMOUNT:", "USD", total
    pl = wb.create_sheet("PL")
    pl["C1"] = "ACME TRADING CO., LTD."
    pl["A7"], pl["B7"], pl["I7"], pl["J7"] = "Messrs:", "Buyer Vietnam Co.,Ltd.", "Invoice No.:", "ACME26110001X"
    pl["I9"], pl["J9"] = "Date:", "2026-11-01"
    for c, h in zip("ABGHIJK", ("Mark & No.", "Description of Goods", "Quantity\nSETS", "Quantity\nCTNS", "N.W.\nKGS",
                                "G.W.\nKGS", "Measurement\nCBM")):
        pl[f"{c}13"] = h
    pl["A15"], pl["B15"] = "N/M", "ACME FAN AND ACME HEATER"
    pl["B18"], pl["C18"] = "CONTAINER NO.", "MODEL NO."
    rows = ([("1.ABCU1234567/40HQ", "AB-X10(W1)", 80), (None, "CD-Y20", 50), ("2.ABCU7654321/40HQ", "AB-X10(W1)", 50)]
            if split_pl else [("1.ABCU1234567/40HQ", "AB-X10(W1)", 100), (None, "CD-Y20", 50), (None, "AB-X10(W1)", 30)])
    for i, (cn, model, q) in enumerate(rows):
        r = 19 + i
        if cn:
            pl[f"B{r}"] = cn
        pl[f"C{r}"], pl[f"G{r}"], pl[f"H{r}"], pl[f"I{r}"], pl[f"J{r}"], pl[f"K{r}"] = model, q, q, q * 2, q * 2.5, 0.1 * q
    pl["B30"], pl["C30"] = "PORT OF DISCHARGE:", "PORT ALPHA,NOWHERE"
    pl["B32"] = "TOTAL PACKED IN ONE HUNDRED AND EIGHTY (180) CARTONS ONLY."
    pl["F34"], pl["G34"], pl["H34"], pl["I34"], pl["J34"], pl["K34"] = "TOTAL:", 180, 180, 360, 450, 18
    sc = wb.create_sheet("SC")
    sc["A1"] = "Sales Contract"
    sc["A6"], sc["B6"] = "No.", "AC000000000001"
    sc["A10"], sc["B10"], sc["I10"], sc["J10"] = "The Seller:", "ACME TRADING CO., LTD.", "Date:", "2026-10-30"
    sc["A15"], sc["B15"] = "The Buyer:", "BUYER VIETNAM CO.,LTD"
    sc["A26"], sc["B26"], sc["G26"], sc["I26"], sc["J26"] = "NO.", "DESCRIPTION", "Quantity\nSETS", "U/PRICE", "AMOUNT(USD)"
    sc["B27"], sc["J27"] = "ACME FAN AND ACME HEATER", "CIF PORT ALPHA,NOWHERE"
    for i, (m, q, pr) in enumerate((("AB-X10(W1)", 100, "10.00"), ("CD-Y20", 50, "20.50"), ("AB-X10(W1)", 30, "10.00")), 1):
        sc[f"A{28 + i}"], sc[f"B{28 + i}"], sc[f"G{28 + i}"], sc[f"I{28 + i}"], sc[f"J{28 + i}"] = i, m, q, pr, q * float(pr)
    sc["B40"], sc["G40"], sc["J40"] = "TOTAL：", 180, 2325
    sc["A41"] = "SAY TOTAL U.S. DOLLARS TWO THOUSAND THREE HUNDRED TWENTY FIVE ONLY."
    sc["A45"], sc["B45"] = 5, " SHIPMENT"
    if not blank_shipment:
        sc["E45"], sc["F45"] = "By ", __import__("datetime").datetime(2026, 11, 20)
    sc["A47"], sc["B47"], sc["D47"] = 9, " PAYMENT    ", "OA 30 days after B/L Date"
    hidden = wb.create_sheet("work")
    hidden["A1"] = "Invoice No.: NOT-A-DOCUMENT"
    hidden.sheet_state = "hidden"
    wb.save(path)


@test("Excel workbook: invoice + packing list + contract sheets are read by cell; hidden sheets are not documents")
def _():
    from engine.extract import load_excel
    p = TMP / "acme_cipl.xlsx"
    _workbook(p)
    docs = load_excel(p, TMP)
    kinds = sorted(d.kind for d in docs)
    assert kinds == ["CI", "SC"], kinds
    ci = next(d for d in docs if d.kind == "CI")
    assert ci.f["invoice_no"].value == "ACME26110001X" and str(ci.f["invoice_date"].value) == "2026-11-01"
    assert [(i["model"], i["qty"].value, i["amount"].value) for i in ci.items] == [
        ("AB-X10(W1)", 100, 1000), ("CD-Y20", 50, 1025), ("AB-X10(W1)", 30, 300)], ci.items
    assert [c["amount"].value for c in ci.lists["charges"]] == [100, 25.5]
    assert ci.f["total_amount"].value == 2450.5 and ci.f["incoterm"].value == "CIF PORT ALPHA"
    assert ci.f["qty_unit"].value == "SETS" and ci.f["currency"].value == "USD"
    assert ci.f["pl_total_ctn"].value == 180 and ci.f["containers"].value == 2 and len(ci.pl_items) == 3
    assert ci.pl_items[2]["container"] == "ABCU7654321"
    f = ci.f["invoice_no"]                          # the value keeps its place on the drawn page
    assert f.line.text[f.start:f.end] == "ACME26110001X", (f.line.text, f.start, f.end)
    sc = next(d for d in docs if d.kind == "SC")
    assert sc.f["sc_no"].value == "AC000000000001" and sc.f["total_amount"].value == 2325
    assert str(sc.f["shipment_by"].value) == "2026-11-20" and len(sc.items) == 3


@test("Excel invoice with freight / insurance rows: total = lines + charges; words 'AND CENTS FIFTY' read")
def _():
    from engine.extract import load_excel
    from engine.rules import validate
    from engine.util import words_to_number
    p = TMP / "acme_cipl2.xlsx"
    _workbook(p)
    docs = load_excel(p, TMP / "x2") if (TMP / "x2").mkdir() is None else None
    keys = {f.key for f in validate(docs)}
    assert "TOTAL_AMOUNT" not in keys and "WORDS_VS_FIGURES" not in keys, keys
    assert words_to_number("SAY TOTAL U.S. DOLLARS ONE HUNDRED TWENTY THREE AND CENTS FORTY FIVE ONLY.") == 123.45


@test("packing list by container: lines differ from the invoice, each model's quantity adds up (no LINE_COUNT)")
def _():
    from engine.extract import load_excel
    from engine.rules import validate
    p = TMP / "acme_cipl3.xlsx"
    _workbook(p, split_pl=True)
    (TMP / "x3").mkdir()
    docs = load_excel(p, TMP / "x3")
    keys = {f.key for f in validate(docs)}
    assert "LINE_COUNT" not in keys and "PL_MODEL_QTY" not in keys, keys
    ci = next(d for d in docs if d.kind == "CI")
    ci.pl_items[2]["qty"].value = 40                # 80 + 40 = 120 sets of AB-X10(W1) packed, invoice 130
    keys = {f.key for f in validate(docs)}
    assert "PL_MODEL_QTY" in keys, keys


@test("contract term 'SHIPMENT' printed with nothing after it is a blank, not unread")
def _():
    from engine.extract import load_excel
    p = TMP / "acme_cipl4.xlsx"
    _workbook(p, blank_shipment=True)
    (TMP / "x4").mkdir()
    sc = next(d for d in load_excel(p, TMP / "x4") if d.kind == "SC")
    assert sc.f.get("shipment_by") is None and sc.f.get("blank:shipment_by") is not None
    assert "shipment_by" in sc.f["absent"].value


def _form_e(name, items, total_lines, box10=("ACME26110001", "X", "NOV. 01,2026"), third=True):
    """An invented Form E page: box headings, column rules, box 7 cut at the column edge, box 10 printed once."""
    p = TMP / f"{name}.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    put = lambda x, y, t: page.insert_text((x, y), t, fontsize=7, fontname="helv")
    put(56, 44, "1.Products consigned from(Exporter's business name,address,")
    put(63, 62, "ACME MAKER APPLIANCES MANUFACTURING CO.,")
    put(63, 72, "LTD. NO.1 SOMEWHERE ROAD")
    put(362, 77, "ASEAN-CHINA FREE TRADE AREA")
    put(382, 105, "CERTIFICATE OF ORIGIN")
    put(57, 117, "2.Products consigned to (Consignee's name,address,country)")
    put(62, 130, "BUYER VIETNAM CO.,LTD.")
    put(435, 134, "FORM E")
    put(64, 217, "Departure date")
    put(125, 220, "NOV. 03,2026")
    put(64, 239, "Vessel's name/Aircraft etc. ACME STAR 012 S034")
    put(64, 263, "Port of Discharge    PORT ALPHA,NOWHERE")
    for x, t in ((56, "5.item"), (100, "6.Marks and"), (166, "7.Number and type of packages, description"),
                 (354, "8.Origin criteria"), (432, "9.Gross weight or net"), (512, "10.Number,")):
        put(x, 326, t)
    for x in (54, 98, 164, 352, 426, 500, 568):
        page.draw_line((x, 320), (x, 612), width=0.5)
    y = 376
    for k, it in enumerate(items):
        put(74, y, str(k + 1))
        put(99, y, "N/M")
        put(379, y, '"PE"')
        put(430, y, it["qty"])
        if k == 0 and box10:
            put(503, y, box10[0])
            put(503, y + 11, box10[1])
            put(503, y + 21, box10[2])
        for n, t in enumerate(it["box7"]):
            put(169, y + 11 * n, t)
        y += 11 * (len(it["box7"]) + 1)
    for n, t in enumerate(total_lines):
        put(169, y + 11 * n, t)
    put(61, 613, "11.Declaration by the exporter")
    put(70, 637, "and Statement are correct,that all the products were produced in")
    put(167, 654, "NOWHERE")
    put(70, 697, "products exported to")
    put(175, 714, "VIET NAM")
    put(279, 23, "非有效证书" if False else "Original")
    doc.save(p)
    return load(p)


_FE_ITEMS = [dict(qty="1250SETS", box7=["ONE THOUSAND TWO HUNDRED AND FIFTY (125", "0) CTNS OF ACME MICROWAVE O-",
                                        "VEN", "1 CTN = 1 SET", "MODEL NO: AB-X10(W1)", "HS CODE:123456"]),
             dict(qty="160SETS", box7=["EIGHTY (80) CTNS OF ACME BLEN-", "DER", "MODEL NO: CD-Y20",
                                       "1 CARTON=2 SETS", "HS CODE:234567"])]
_FE_TOTAL = ["TOTAL PACKED IN ONE THOUSAND THREE HUND-", "RED AND THIRTY (1330) CARTONS ONLY.", "***  ***  ***",
             "THIRD-PARTY OPERATOR:ACME TRADING CO., L-", "TD. 1 SOMEWHERE STREET"]


@test("Form E: box 7 words cut at the column edge and a figure split over lines are read whole; box 10 once")
def _():
    d = _form_e("fe1", _FE_ITEMS, _FE_TOTAL)
    assert d.kind == "CO" and d.form == "E", (d.kind, getattr(d, "form", None))
    a, b = d.items
    assert (a["pkg_words"], a["pkg_fig"].value, a["per_ctn"], a["model"], a["hs"]) == (
        "ONE THOUSAND TWO HUNDRED AND FIFTY", 1250, 1, "AB-X10(W1)", "123456"), a
    assert a["goods"].value == "ACME MICROWAVE OVEN", a["goods"].value
    assert (b["pkg_fig"].value, b["per_ctn"], b["qty"].value, b["goods"].value) == (80, 2, 160, "ACME BLENDER"), b
    assert a["inv_ref"] == b["inv_ref"] == "ACME26110001X" and str(b["inv_date"].value) == "2026-11-01"
    assert d.f["total_ctn"].value == 1330 and d.f["total_ctn_words"].value == "ONE THOUSAND THREE HUNDRED AND THIRTY"
    assert d.f["vessel"].value == ("ACME STAR 012", "S034") and str(d.f["departure"].value) == "2026-11-03"
    assert d.f["third_party"].value == "ACME TRADING CO., LTD.", d.f["third_party"].value
    assert d.f["exporter"].value == "ACME MAKER APPLIANCES MANUFACTURING CO., LTD.", d.f["exporter"].value
    assert "total_qty" in d.f["absent"].value            # Form E prints no quantity / value total


@test("Form E: wrong carton words are found; findings say 'Form E'")
def _():
    from engine.rules import Finding, r_co_packages
    items = [dict(_FE_ITEMS[0]), _FE_ITEMS[1]]
    items[0] = dict(items[0], box7=["ONE THOUSAND TWO HUNDRED AND FIVE (125"] + _FE_ITEMS[0]["box7"][1:])
    d = _form_e("fe2", items, _FE_TOTAL)
    assert d.items[0]["pkg_words"] == "ONE THOUSAND TWO HUNDRED AND FIVE"
    f = Finding("CO_QTY", "ERROR", [d], dict(no=1))
    assert "Form E" in f.text("en") and "Form D" not in f.text("en"), f.text("en")


def _plain_bl(name):
    """An invented carrier B/L whose box labels are a background picture: values only, read by position."""
    p = TMP / f"{name}.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=1190, height=1684)
    put = lambda x, y, t: page.insert_text((x, y), t, fontsize=14, fontname="helv")
    put(46, 63, "ACME MAKER APPLIANCES")
    put(981, 73, "ACMEBL0012345")
    put(46, 83, "MANUFACTURING CO.,LTD")
    put(46, 104, "NO.1 SOMEWHERE ROAD")
    put(46, 206, "BUYER VIETNAM CO.,LTD.")
    put(46, 226, "NO. 2, SOME STREET")
    put(44, 354, "ACME LOGISTICS VIETNAM CO., LTD.")
    put(44, 374, "ROOM 1, SOME TOWER")
    put(335, 503, "PORT BETA,NOWHERE")
    put(86, 553, "ACME STAR  012S")
    put(335, 553, "PORT BETA,NOWHERE")
    put(48, 603, "PORT ALPHA,VIETNAM")
    put(335, 603, "PORT ALPHA,VIETNAM")
    put(30, 728, "N/M")
    put(475, 755, "SHIPPER'S LOAD,COUNT&SEAL,CONTENTS UNKNOWN")
    put(30, 769, "ABCU1234567 /0012345     40HCF")
    put(607, 779, "SAID TO CONTAIN")
    put(30, 789, "ABCU7654321 /0054321     40HCF")
    put(352, 803, "180")
    put(420, 803, "CARTONS")
    put(540, 803, "ACME FAN AND")
    put(800, 803, "450.000KGS")
    put(960, 803, "18.000CBM")
    put(540, 823, "ACME HEATER")
    put(540, 843, "180 CTNS = 180 SETS")
    put(540, 863, "HS CODE:345678 , 456789")
    put(540, 883, "INVOICE NO.: ACME26110001X")
    put(335, 1268, "TOTAL: 2×40HC   CONTAINERS ONLY.")
    put(24, 1510, "FREIGHT PREPAID")
    doc.save(p)
    return load(p)


@test("B/L without label text (labels in the background picture): read by block order and column")
def _():
    d = _plain_bl("plain_bl")
    assert d.kind == "BL"
    f = d.f
    assert f["bl_no"].value == "ACMEBL0012345" and f["shipper"].value == "ACME MAKER APPLIANCES MANUFACTURING CO.,LTD"
    assert f["consignee"].value == "BUYER VIETNAM CO.,LTD." and f["vessel"].value == ("ACME STAR", "012S")
    assert (f["pol"].value, f["pod"].value, f["delivery"].value, f["dest_country"].value) == (
        "PORT BETA", "PORT ALPHA", "PORT ALPHA", "VIETNAM")
    assert [x.value for x in d.lists["cntr"]] == [("ABCU1234567", "40HC"), ("ABCU7654321", "40HC")]
    assert (f["ctn"].value, f["gw"].value, f["cbm"].value, f["bl_qty"].value) == (180, 450, 18, 180)
    assert f["cntr_summary"].value == "2X40HC" and f["invoice_no"].value == "ACME26110001X"
    assert f["goods"].value == "ACME FAN AND ACME HEATER" and f["hs_all"].value == "345678, 456789"
    assert f["freight"].value == "PREPAID"


def _pdf(name, cells, size=7, font="helv"):
    """An invented PDF from (page, x, y, text) cells."""
    doc = pymupdf.open()
    for _ in range(max(c[0] for c in cells) + 1):
        doc.new_page(width=595, height=842)
    for p, x, y, t in cells:
        doc[p].insert_text((x, y), t, fontsize=size, fontname=font)
    path = Path(tempfile.mkdtemp()) / f"{name}.pdf"
    doc.save(path)
    return path


_BOXES = [(0, 23, 56, "SHIPPER/EXPORTER (COMPLETE NAME AND ADDRESS)"), (0, 23, 66, "ACME MAKER APPLIANCES"),
          (0, 23, 76, "MANUFACTURING CO.,LTD"), (0, 23, 126, "CONSIGNEE (COMPLETE NAME AND ADDRESS)"),
          (0, 23, 136, "BUYER VIETNAM CO.,LTD."), (0, 23, 198, "NOTIFY PARTY (COMPLETE NAME AND ADDRESS)"),
          (0, 23, 210, "NOTIFY LOGISTICS CO., LTD."), (0, 23, 279, "PRE-CARRIAGE BY"), (0, 196, 279, "PLACE OF RECEIPT"),
          (0, 196, 288, "PORT BETA,NOWHERE"), (0, 23, 297, "VESSEL/VOYAGE/FLAG"), (0, 196, 297, "PORT OF LOADING"),
          (0, 196, 306, "PORT BETA,NOWHERE"), (0, 23, 316, "PORT OF DISCHARGE"), (0, 196, 316, "PLACE OF DELIVERY")]


def _waybill(name="waybill", inv="ACME26110001X", cntr2="ABCU7654321", ctn2=50, no="ACMU0012345"):
    """A typed (monospaced) sea waybill: footnotes complete the boxes, the description goes on on page 2."""
    pad = " " * 29
    rows = ["ABCU1234567  /SEAL0001   /    130 CARTONS       /FCL/FCL /40HQ/",
            f"{cntr2}  /SEAL0002   /    {ctn2:3d} CARTONS       /FCL/FCL /40HQ/", "-" * 93,
            "N/M                      180 ACME FAN AND                           450.000KGS    18.000CBM",
            "                     CARTONS ACME HEATER", pad + "180CTNS=180SETS", pad + "HS CODE:345678 / 456789",
            "                       **  TO BE CONTINUED ON ATTACHED LIST  **"]
    cells = _BOXES + [(0, 444, 52, "SEA WAYBILL NO."), (0, 444, 64, no), (0, 23, 306, "ACME STAR 012S"),
                      (0, 23, 326, "PORT ALPHA,++"), (0, 196, 326, "PORT ALPHA,++")]
    cells += [(0, 18, 365 + 8 * i, r) for i, r in enumerate(rows)]
    cells += [(1, 18, 47, "PAGE: 2 OF 2"), (1, 18, 98, pad + f"INVOICE NO.: {inv}"), (1, 18, 106, pad + "++VIETNAM"),
              (1, 18, 123, "TOTAL:                   180                                     450.000KGS    18.000CBM"),
              (1, 18, 148, "OCEAN FREIGHT PREPAID"),
              (1, 18, 165, "|CALCULATION OF PACKAGE LIMITATION (IF APPLICABLE):    2 CONTAINER(S)/PACKAGE(S)  |")]
    return _pdf(name, cells, size=6, font="cour")


@test("waybill with labelled boxes, typed cargo: boxes, footnote country, description over two pages, container rows")
def _():
    d = load(_waybill())
    f = d.f
    assert d.kind == "BL" and f["bl_no"].value == "ACMU0012345", f
    assert f["shipper"].value == "ACME MAKER APPLIANCES MANUFACTURING CO.,LTD" and f["consignee"].value == "BUYER VIETNAM CO.,LTD."
    assert f["notify"].value == "NOTIFY LOGISTICS CO., LTD." and f["vessel"].value == ("ACME STAR", "012S")
    assert (f["receipt"].value, f["pol"].value, f["pod"].value, f["dest_country"].value) == (
        "PORT BETA", "PORT BETA", "PORT ALPHA", "VIETNAM")
    assert (f["ctn"].value, f["gw"].value, f["cbm"].value, f["bl_qty"].value, f["containers"].value) == (180, 450, 18, 180, 2)
    assert f["goods"].value == "ACME FAN AND ACME HEATER" and f["hs_all"].value == "345678, 456789"
    assert f["invoice_no"].value == "ACME26110001X" and f["freight"].value == "PREPAID"
    assert [x.value for x in d.lists["cntr_load"]] == [("ABCU1234567", 130, None, None), ("ABCU7654321", 50, None, None)]


@test("carrier B/L with numbered boxes and columns; an empty vessel box is reported as empty")
def _():
    cells = [(0, 311, 89, "BILL OF LADING"), (0, 357, 89, "NO."), (0, 419, 95, "ACMEBL0012345"),
             (0, 33, 89, "1. SHIPPER Insert Name, Address and Phone"), (0, 33, 98, "ACME MAKER MANUFACTURING CO.,LTD"),
             (0, 33, 150, "2. CONSIGNEE Insert name, Address and Phone"), (0, 33, 159, "BUYER VIETNAM CO.,LTD."),
             (0, 33, 211, "3. NOTIFY PARTY Insert Name, Address and Phone"), (0, 33, 222, "NOTIFY LOGISTICS CO., LTD."),
             (0, 323, 232, "the place of receipt or the port of loading"),
             (0, 33, 273, "4. PRE-CARRIAGE BY"), (0, 196, 273, "5. PLACE OF RECEIPT"), (0, 194, 284, "PORT BETA,NOWHERE"),
             (0, 33, 297, "6. OCEAN VESSEL/VOY NO."), (0, 196, 297, "7. PORT OF LOADING"), (0, 194, 306, "PORT BETA,NOWHERE"),
             (0, 33, 322, "8. PORT OF DISCHARGE"), (0, 196, 322, "9. PLACE OF DELIVERY"),
             (0, 34, 332, "PORT ALPHA,VIET NAM"), (0, 193, 332, "PORT ALPHA,VIET NAM"),
             (0, 137, 366, "180CARTONS"), (0, 201, 366, "SHIPPER'S LOAD, COUNT & SEAL"), (0, 441, 366, "450.00 KGS"),
             (0, 520, 366, "18.00"), (0, 28, 371, "ABCU1234567/S0001 40HC"), (0, 28, 380, "ABCU7654321/S0002 20GP"),
             (0, 201, 374, "SAID TO CONTAIN"), (0, 520, 374, "CBM"), (0, 201, 392, "ACME FAN & ACME HEATER"),
             (0, 201, 400, "180CTNS=180SETS"), (0, 201, 409, "HS CODE:345678"), (0, 201, 417, "INVOICE NO.: ACME26110001X"),
             (0, 201, 504, "1x40HC,1x20GP FCL"), (0, 201, 521, "CY/CY"), (0, 201, 547, "FREIGHT COLLECT"),
             (0, 146, 584, "SAY TOTAL TWO (2) CONTAINERS ONLY"), (0, 290, 692, "T"), (0, 290, 701, "O"), (0, 290, 710, "T")]
    d = load(_pdf("boxes", cells))
    f = d.f
    assert f["bl_no"].value == "ACMEBL0012345" and f["blank:vessel"] and not f.get("vessel"), f
    assert (f["receipt"].value, f["pol"].value, f["pod"].value, f["dest_country"].value) == (
        "PORT BETA", "PORT BETA", "PORT ALPHA", "VIET NAM")
    assert (f["ctn"].value, f["gw"].value, f["cbm"].value, f["bl_qty"].value) == (180, 450, 18, 180)
    assert f["goods"].value == "ACME FAN & ACME HEATER" and f["cntr_summary"].value == "1X40HC,1X20GP"
    assert f["cntr_words"].value == "TWO" and f["cntr_words_n"].value == 2 and f["freight"].value == "COLLECT"
    from engine.rules import r_broken_wrap
    out = []
    r_broken_wrap([d], out)
    assert not out, [x.current for x in out]          # 'T / O / T' printed downwards is not a broken word


@test("plain B/L with containers written with slashes, description on the attached sheet, tax code before the name")
def _():
    cells = [(0, 20, 21, "ACME MAKER MANUFACTURING"), (0, 448, 21, "ACMEBL0099999"), (0, 20, 31, "CO.,LTD"),
             (0, 20, 41, "1 ACME ROAD"), (0, 20, 97, "TAX CODE:0000000001"), (0, 20, 107, "BUYER VIETNAM CO.,LTD."),
             (0, 20, 117, "2 BUYER STREET"), (0, 20, 183, "NOTIFY LOGISTICS CO., LTD."), (0, 20, 193, "3 NOTIFY STREET"),
             (0, 20, 283, "ACME STAR 012S"), (0, 166, 283, "PORT BETA,NOWHERE"), (0, 239, 295, "PORT ALPHA,VIETNAM"),
             (0, 20, 303, "PORT ALPHA,VIETNAM"), (0, 458, 344, "1,450.500"), (0, 546, 344, "18.000"),
             (0, 146, 360, "180"), (0, 200, 360, "SEE ATTACH"), (0, 478, 360, "KGS"), (0, 554, 360, "CBM"),
             (0, 146, 374, "CARTONS"), (0, 20, 564, "ABCU1234567/S0001/40'HC/130 CARTONS/G.W.1,325.500 KGS/13.000 CBM"),
             (0, 346, 564, "CY-CY"), (0, 436, 575, "2*40HC FCL"), (0, 346, 585, "FREIGHT PREPAID"),
             (0, 212, 624, "SAY TOTAL TWO (2)CONTAINERS ONLY"), (1, 13, 63, "ATTACHED SHEET"), (1, 242, 90, "DESCRIPTION OF GOODS"),
             (1, 242, 103, "ACME FAN"), (1, 242, 117, "180CTNS=180SETS"), (1, 242, 132, "HS CODE:345678"),
             (1, 242, 146, "INVOICE NO.: ACME26110001X"), (1, 13, 288, "ABCU7654321/S0002/40'HC/50 CARTONS/G.W.125.000 KGS/5.000 CBM")]
    d = load(_pdf("slashes", cells))
    f = d.f
    assert d.kind == "BL" and f["consignee"].value == "BUYER VIETNAM CO.,LTD.", f
    assert (f["vessel"].value, f["pod"].value, f["delivery"].value) == (("ACME STAR", "012S"), "PORT ALPHA", "PORT ALPHA")
    assert (f["ctn"].value, f["gw"].value, f["cbm"].value, f["goods"].value) == (180, 1450.5, 18, "ACME FAN")
    assert [x.value for x in d.lists["cntr_load"]] == [("ABCU1234567", 130, 1325.5, 13), ("ABCU7654321", 50, 125, 5)]


def _book(edit=None, name="book", **kw):
    import openpyxl
    path = Path(tempfile.mkdtemp()) / f"{name}.xlsx"
    _workbook(path, **kw)
    if edit:
        wb = openpyxl.load_workbook(path)
        edit(wb)
        wb.save(path)
    return load_excel(path, path.parent)


@test("Excel: goods name beside each model (no heading): read per line, the model is never taken as the goods name")
def _():
    def edit(wb):
        for ws, head, col, first in (("Inv.", "B16", "C", 19), ("PL", "B15", "D", 19), ("SC", "B27", "E", 29)):
            wb[ws][head] = None
            for i, g in enumerate(("ACME FAN", "ACME HEATER", "ACME FAN")):
                wb[ws][f"{col}{first + i}"] = g
    docs = _book(edit)
    for d in docs:
        assert d.f["goods_full"].value == "ACME FAN AND ACME HEATER", d.f["goods_full"].value
    assert docs[0].items[1]["desc"].value == "ACME HEATER" and docs[0].pl_items[1]["desc"].value == "ACME HEATER"


@test("Excel: freight on two contracts is one charge too many; a contract without line numbers is not a crash")
def _():
    from engine.rules import r_sc_vs_ci

    def edit(wb, both=False):
        def charge(ws):
            ws["B32"], ws["J32"], ws["B33"], ws["J33"] = "Freight", 100, "Insurance", 25.5
        charge(wb["SC"])
        for r in (30, 31):
            wb["SC"][f"A{r}"] = None
        if both:
            charge(wb.copy_worksheet(wb["SC"]))
    for both in (False, True):
        docs = _book(lambda wb: edit(wb, both))
        ci, scs, out = docs[0], docs[1:], []
        r_sc_vs_ci(scs, ci, out)
        assert len(scs) == 1 + both
        got = [f for f in out if f.key.startswith("SC_CHARGES")]
        if both:                                    
            f = got[0]                                 # on the page that prints the repeat; 'found' is what is printed there
            assert f.key == "SC_CHARGES_TWICE" and f.docs[0] is scs[1] and f.current == "100", (f.key, f.current)
            assert [(l.doc.name, l.role) for l in f.locs] == [(scs[1].name, "wrong"), (scs[0].name, "ref"), (ci.name, "ref")]
            assert "Contract 2" in f.text("en") and "200" in f.text("en"), f.text("en")
        assert len(got) == (2 if both else 0), [(f.key, f.current) for f in out]
        assert any(f.key == "SC_NUMBERING" and f.current == "1,—,—" for f in out)


@test("several B/Ls: each is checked with its own invoice; a wrong container no. / load is found; draft + final count once")
def _():
    from engine.rules import validate_checks, _shipments
    one = _book(name="one")
    def second(wb):
        for ws in ("Inv.", "PL"):
            for row in wb[ws].iter_rows():
                for c in row:
                    if c.value == "ACME26110001X":
                        c.value = "ACME26110002Y"
        wb["SC"]["B6"] = "AC000000000002"
        wb["PL"]["B21"] = "2.ABCU7654322/40HQ"
    two = _book(second, name="two ACME26110002Y")
    for d in two:
        if d.kind == "SC":
            assert "ACME26110002Y" in d.name
    b1, b2 = load(_waybill("bl1")), load(_waybill("bl2", inv="ACME26110002Y", cntr2="ABCU7654323", ctn2=49, no="ACMU0099999"))
    parts = _shipments(one + two + [b1, b2])
    assert len(parts) == 2 and [x.name for x in parts[0][0] if x.kind == "BL"] == ["bl1.pdf"]
    finds, checks = validate_checks(one + two + [b1, b2])
    keys = {(f.key, f.docs[0].name) for f in finds}
    assert ("CNTR_NO", "bl2.pdf") in keys and ("CNTR_NO", "bl1.pdf") not in keys, keys
    assert not {k for k in keys if k[0] in ("BL_VS_PL", "BL_INVOICE_MISSING", "VESSEL", "BL_INVOICE_EXTRA")}, keys
    assert [f.suggested for f in finds if f.key == "CNTR_NO"] == ["ABCU7654322"]
    assert not [c for c in checks if c.reason == "internal_error"]
    st = {c.group_id: c.status for c in checks if c.check_id == "CNTR_VS_PL"}
    assert st == {"shipment": "PASS", "shipment2": "FAIL"}, st
    again = load(_waybill("bl1 final", ctn2=48))            # the final B/L of invoice 1 has another carton count
    assert len(_shipments(one + [b1, again])) == 2
    finds, _c = validate_checks(one + [b1, again])
    assert ("CNTR_LOAD", "bl1 final.pdf") in {(f.key, f.docs[0].name) for f in finds}
    assert ("CNTR_LOAD", "bl1.pdf") not in {(f.key, f.docs[0].name) for f in finds}


@test("files with the same name in several folders of a zip stay apart")
def _():
    import zipfile
    from engine import collect
    t = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(t / "a.zip", "w") as z:
        for n in ("S1/DRAFT.pdf", "S2/draft.pdf", "S2/other.pdf"):
            z.writestr(n, n)
    (t / "w").mkdir()
    files = collect([t / "a.zip"], t / "w")
    assert sorted(f.name for f in files) == ["DRAFT (S1).pdf", "draft (S2).pdf", "other.pdf"], files
    assert next(f for f in files if f.name.startswith("draft")).read_text() == "S2/draft.pdf"


if __name__ == "__main__":
    print("RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)
