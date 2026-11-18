import re
from datetime import date, datetime

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def num(s) -> float:
    return float(str(s).replace(",", "").strip())


def parse_date(s: str):
    """The date written in s, or None when there is none or it cannot exist (month 13, 31 June …)."""
    try:
        return _parse_date(s)
    except ValueError:
        return None


def _parse_date(s: str):
    s = s.strip().upper().replace(",", " ")
    # (?<![A-Z0-9]): the day starts the number. 'I2/11/2026' (a letter typed for 1) is not 2/11/2026: no date.
    m = re.search(r"(?<![A-Z0-9])(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(?<![A-Z0-9])(\d{1,2})[\s\-]+([A-Z]{3})[A-Z]*[\s\-]+(\d{4})", s)
    if m and m[2] in _MONTHS:
        return date(int(m[3]), _MONTHS[m[2]], int(m[1]))
    m = re.search(r"([A-Z]{3})[A-Z]*\s+(\d{1,2})\s+(\d{4})", s)
    if m and m[1] in _MONTHS:
        return date(int(m[3]), _MONTHS[m[1]], int(m[2]))
    return None


_UNITS = {w: i for i, w in enumerate(
    "ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE THIRTEEN FOURTEEN "
    "FIFTEEN SIXTEEN SEVENTEEN EIGHTEEN NINETEEN".split())}
_TENS = {w: (i + 2) * 10 for i, w in enumerate("TWENTY THIRTY FORTY FIFTY SIXTY SEVENTY EIGHTY NINETY".split())}
_SCALES = {"HUNDRED": 100, "THOUSAND": 1000, "MILLION": 10**6, "BILLION": 10**9}


def _int_words(words: list[str]):
    total = cur = 0
    seen = False
    for w in words:
        if w in _UNITS:
            cur += _UNITS[w]; seen = True
        elif w in _TENS:
            cur += _TENS[w]; seen = True
        elif w == "HUNDRED":
            cur = (cur or 1) * 100; seen = True
        elif w in _SCALES:
            total += (cur or 1) * _SCALES[w]; cur = 0; seen = True
    return total + cur if seen else None


def words_to_number(text: str):
    """'SIXTY NINE THOUSAND EIGHT HUNDRED SEVENTY', '... TWO AND FOURTEEN CENTS', '... POINT ONE FOUR'."""
    t = re.sub(r"[^A-Z ]", " ", text.upper().replace("-", " "))
    t = re.sub(r"\b(SAY|TOTAL|U S|US|USD|DOLLARS?|ONLY|PACKED|IN)\b", " ", t)
    cents = 0.0
    m = re.search(r"\bPOINT\b(.*)$", t)
    if m:
        digits = [str(_UNITS[w]) for w in m[1].split() if w in _UNITS]
        cents = float("0." + "".join(digits)) if digits else 0.0
        t = t[:m.start()]
    else:
        m = re.search(r"^(.*)\bAND\b(.*?)\bCENTS?\b", t)
        if m:
            c = _int_words(m[2].split())
            cents = (c or 0) / 100
            t = m[1]
    n = _int_words([w for w in t.split() if w != "AND"])
    return None if n is None else round(n + cents, 2)


def fmt_like(value: float, sample: str) -> str:
    """Format a number with the same thousands separator / decimals as sample."""
    dec = len(sample.split(".")[1]) if "." in sample else 0
    s = f"{value:,.{dec}f}"
    return s if "," in sample or value < 1000 else s.replace(",", "")


def number_to_words(n: int) -> str:
    """250 -> 'TWO HUNDRED FIFTY' (style used on Form D)."""
    units = list(_UNITS)
    tens = list(_TENS)

    def below_1000(x):
        out = []
        if x >= 100:
            out += [units[x // 100], "HUNDRED"]; x %= 100
        if x >= 20:
            out.append(tens[x // 10 - 2] + ("-" + units[x % 10] if x % 10 else "")); x = 0
        if x:
            out.append(units[x])
        return out

    n = int(n)
    if n == 0:
        return "ZERO"
    parts = []
    for scale, word in ((10**9, "BILLION"), (10**6, "MILLION"), (1000, "THOUSAND"), (1, "")):
        if n >= scale:
            parts += below_1000(n // scale) + ([word] if word else []); n %= scale
    return " ".join(parts)
