"""Value grammar (LDV 2.4, P2): one place for how numbers, quantities, units, document numbers, dates and labels are
written. Readers build their patterns from these pieces instead of writing their own each time.

Every piece matches a WHOLE token: a number is never read from the middle of a larger number ('357.00' is 357.00,
never '00'; '1,250' is 1,250, never '250'). Ambiguous forms ('1,25', '1.250,00') are not numbers here: they are
reported by the reader as not understood instead of guessed.

    NUM        a number: 357 · 357.00 · 1,250 · 1,250.00 · 0.481 · 48,316.250        (group-free: wrap it in ( ))
    DEC        a number with decimals (amounts, weights, CBM): 1,250.00 · 0.481
    QTY_UNIT   SET(S) · SET (S) · SETS · SET · PCS · PC · PIECE(S) · UNIT(S)
    CTN_UNIT   CARTON(S) · CARTON (S) · CARTONS · CARTON · CTNS · CTN
    DATE_DMY   21/11/2026
    DOC_ID     a document number: letters / digits, single '-' '/' '.' inside (ACME2611E001 · ABC26-XYZ021)
    SAILING    the 'sailing on or about' label in its spellings (ON OR ABOUT · ON/OR ABOUT · On Or About)

All examples are invented.
"""
import re

_INT = r"\d{1,3}(?:,\d{3})+|\d+"
NUM = rf"(?<![\d.,])(?:{_INT})(?:\.\d+)?(?!\d|[.,]\d)"
DEC = rf"(?<![\d.,])(?:{_INT})\.\d+(?!\d|[.,]\d)"
DEC2 = rf"(?<![\d.,])(?:{_INT})\.\d{{2}}(?!\d|[.,]\d)"
QTY_UNIT = r"(?:SETS?\s*\(\s*S\s*\)|(?:SETS?|PCS|PC|PIECES?|UNITS?)\b)"
CTN_UNIT = r"(?:CARTON\s*\(\s*S\s*\)|(?:CARTONS?|CTNS?)\b)"
DATE_DMY = r"\d{1,2}/\d{1,2}/\d{4}"
# at least one digit; letters / digits with single separators inside; not a date (no '/' between 1-2 digit groups)
DOC_ID = r"(?=[A-Z0-9\-/.]*\d)(?![0-9]{1,2}/[0-9]{1,2}/)[A-Z0-9](?:[A-Z0-9]|[\-/.](?=[A-Z0-9]))+"
SAILING = r"SAILING\s+ON\s*(?:/\s*)?OR\s+ABOUT"

_NUM_FULL = re.compile(rf"\s*({NUM})\s*")


def number(text: str):
    """The value of a number written as one whole token, or None (not a number, or written ambiguously)."""
    m = _NUM_FULL.fullmatch(str(text or ""))
    return float(m[1].replace(",", "")) if m else None


def numbers(text: str) -> list[str]:
    """Every whole number token in text, as written."""
    return re.findall(NUM, text)
