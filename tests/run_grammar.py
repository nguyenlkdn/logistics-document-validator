"""Value grammar (engine/grammar.py): every way of writing a value the readers accept, and the traps.

  python tests/run_grammar.py        # exit code 1 on any failure

All values are invented.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.grammar import CTN_UNIT, DATE_DMY, DOC_ID, NUM, QTY_UNIT, SAILING, number, numbers  # noqa: E402

FAILS = []


def check(name, got, want):
    if got == want:
        print(f"PASS  {name}")
    else:
        FAILS.append(name)
        print(f"FAIL  {name}: got {got!r}, want {want!r}")


# numbers: whole tokens, every supported form
for txt, want in [("357", 357.0), ("357.00", 357.0), ("1,250", 1250.0), ("1,250.00", 1250.0), ("0.481", 0.481),
                  ("48,316.250", 48316.25), ("1,234,567.5", 1234567.5), ("0", 0.0)]:
    check(f"number {txt}", number(txt), want)
# ambiguous / not a number: rejected, never guessed
for txt in ("1,25", "1.250,00", "12,34,567", "1,2345", "1..2", "2O26", "", "abc", "1,250.", ".5"):
    check(f"not a number {txt!r}", number(txt), None)
# a number is never read from the middle of a larger one
check("357.00 PCS is 357.00, never 00", re.search(rf"({NUM})\s*PCS", "TTL:  1 CARTON (S)  357.00   PCS")[1], "357.00")
check("lazy prefix cannot cut a token", re.search(rf"^TTL\b.*?({NUM})\s*{QTY_UNIT}", "TTL: 1 CARTON (S) 357.00 PCS")[1],
      "357.00")
check("1,250 SETS is 1,250", re.search(rf"({NUM})\s*{QTY_UNIT}", "TOTAL 1,250 SETS")[1], "1,250")
check("tokens of a row", numbers("CARTON 1-500   500 SET(S)   6,000.00   6,500.00   32.5"),
      ["1", "500", "500", "6,000.00", "6,500.00", "32.5"])
# units
for u in ("SET(S)", "SET (S)", "SETS", "SET", "PCS", "PC", "PIECE", "PIECES", "UNITS", "SETS(S)"):
    check(f"qty unit {u}", bool(re.fullmatch(QTY_UNIT, u)), True)
for u in ("CARTON(S)", "CARTON (S)", "CARTONS", "CARTON", "CTNS", "CTN", "CARTON ( S )"):
    check(f"carton unit {u}", bool(re.fullmatch(CTN_UNIT, u)), True)
check("CARTONS is not a qty unit", bool(re.fullmatch(QTY_UNIT, "CARTONS")), False)
# document numbers
for txt, want in [("INVOICE NO. ABC26-XYZ021   05/10/2026", "ABC26-XYZ021"), ("INVOICE NO.ACME2611E001", "ACME2611E001"),
                  ("INVOICE NO. ACME0001 DATE : 01/11/2026", "ACME0001"), ("Invoice No.: ACME26110001", "ACME26110001"),
                  ("INVOICE NO. AB/123/2026", "AB/123/2026"), ("INVOICE NO. ACME0001-", "ACME0001")]:
    m = re.search(rf"INVOICE NO\.?\s*:?\s*({DOC_ID})", txt, re.I)
    check(f"invoice no in {txt!r}", m[1] if m else None, want)
check("a date is not a document number", re.fullmatch(DOC_ID, "05/10/2026"), None)
check("letters only are not a document number", re.fullmatch(DOC_ID, "INVOICE"), None)
# dates and labels
check("date d/m/yyyy", re.search(DATE_DMY, "DATE : 1/11/2026")[0], "1/11/2026")
for lab in ("SAILING ON OR ABOUT", "SAILING ON/OR ABOUT", "Sailing On Or About", "SAILING ON / OR ABOUT"):
    check(f"sailing label {lab!r}", bool(re.fullmatch(SAILING, lab, re.I)), True)
# metamorphic: extra spaces or case in the unit do not change the number read
for txt in ("357.00 PCS", "357.00   PCS", "357.00PCS", "357.00 pcs"):
    m = re.search(rf"({NUM})\s*{QTY_UNIT}", txt, re.I)
    check(f"same value in {txt!r}", number(m[1]) if m else None, 357.0)

print("RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
