import difflib
import re
from datetime import date, datetime

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def _get(d, k, default=None):
    return d.get(k, default) if isinstance(d, dict) else getattr(d, k, default)


def co_form(docs) -> str:
    """The certificate form of the C/O documents in a set: 'D', 'E', 'D/E' (both kinds) or '' (no C/O, or a
    review stored before LDV 2.8 that does not say). Takes Doc objects or the session's document dicts."""
    return "/".join(sorted({_get(d, "form") for d in docs if _get(d, "kind") == "CO" and _get(d, "form")}))


def form_text(text: str, form: str) -> str:
    """A text written for a Form D (config messages, check names) said for the certificate actually checked."""
    if not text or form not in ("E", "D/E"):
        return text
    return text.replace("Form D", f"Form {form}").replace("mẫu D", f"mẫu {form}")


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
    m = re.search(r"([A-Z]{3})[A-Z]*\.?\s*(\d{1,2})\s+(\d{4})", s)          # 'OCT. 24,2026' (Form E)
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
    elif re.search(r"\bCENTS?\s+[A-Z]", t):           # '... FORTY TWO AND CENTS FIFTY FIVE ONLY'
        m = re.search(r"^(.*?)(?:\bAND\s+)?\bCENTS?\b(.*)$", t)
        c = _int_words(m[2].split())
        cents = (c or 0) / 100
        t = m[1]
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


def words_for(text: str, value: float) -> str | None:
    """The amount-in-words sentence text, corrected to value: its own wording, case, 'AND' and punctuation are kept and
    only the number words that differ are changed ('… ONE HUNDRED EIGHTY AND CENTS FIVE ONLY' -> '… ONE HUNDRED EIGHT
    AND CENTS FIVE ONLY'). None when the sentence is not written in a way that can be corrected word by word."""
    number = set(_UNITS) | set(_TENS) | set(_SCALES) | {"HUNDRED"}
    toks = [(m[0], m.start(), m.end()) for m in re.finditer(r"[A-Za-z]+", text)]
    whole, cents = divmod(round(value * 100), 100)
    at = lambda w: next((i for i, t in enumerate(toks) if t[0].upper() in w), None)
    c, pt = at(("CENT", "CENTS")), at(("POINT",))
    num = [i for i, t in enumerate(toks) if t[0].upper() in number]
    if not num or pt is not None:
        return None
    if c is None:
        part = {"whole": num, "cents": []}
    elif any(i > c for i in num):                      # '… AND CENTS FIVE'
        part = {"whole": [i for i in num if i < c], "cents": [i for i in num if i > c]}
    else:                                              # '… AND FIVE CENTS': the number after the last AND
        a = max((i for i, t in enumerate(toks[:c]) if t[0].upper() == "AND"), default=None)
        if a is None:
            return None
        part = {"whole": [i for i in num if i < a], "cents": [i for i in num if i > a]}
    if not part["whole"] or bool(part["cents"]) != bool(cents):
        return None
    edits = []                                         # (start, end, new text)
    for key, n in (("whole", whole), ("cents", cents)):
        idx = part[key]
        if not idx:
            continue
        have = [toks[i][0].upper() for i in idx]
        want = number_to_words(n).replace("-", " ").split()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, have, want, autojunk=False).get_opcodes():
            if op == "equal":
                continue
            sample = toks[idx[min(i1, len(idx) - 1)]][0]
            new = " ".join(w if sample.isupper() else w.capitalize() if sample[0].isupper() else w.lower()
                           for w in want[j1:j2])
            if op == "insert":
                k = toks[idx[i1 - 1]][2] if i1 else toks[idx[0]][1]
                edits.append((k, k, f" {new}" if i1 else f"{new} "))
            elif op == "replace":
                edits.append((toks[idx[i1]][1], toks[idx[i2 - 1]][2], new))
            else:                                      # the word goes, with the blank / hyphen before it
                start = toks[idx[i1]][1]
                edits.append((len(text[:start].rstrip(" -")), toks[idx[i2 - 1]][2], ""))
    out = text
    for a, b, new in sorted(edits, reverse=True):
        out = out[:a] + new + out[b:]
    out = re.sub(r"\s+", " ", re.sub(r"\b(AND)(\s+AND\b)+", r"\1", out, flags=re.I)).strip()
    got = words_to_number(out)
    return out if got is not None and abs(got - value) < 0.005 else None
