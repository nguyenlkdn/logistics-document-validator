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

if __name__ == "__main__":
    print("RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)
