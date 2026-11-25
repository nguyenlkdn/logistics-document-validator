"""Place names of one city (ports, terminals): the general list in config "cities" plus the names the user confirmed.

A name LDV does not know is never guessed: the check that needs it does not run. The one exception: a name one typo away
from another city's name (misspelled) is reported as the wrong city; it never makes a check pass. The Reference data page lists such names
from the checked documents with a suggested city, and the user confirms each one. The confirmed names stay on this PC:

  places_added.json     {key: {name, city, added_at, by, docs}} in the data folder (engine/master.data_dir)
  places_log.jsonl      one line per name added / removed
"""
import json
import re
from datetime import datetime

from . import master

_cache = {"key": None, "rows": {}}


def key(place) -> str:
    """A place name as a lookup key: its letters only."""
    return re.sub(r"[^A-Z]", "", str(place or "").upper())


def _file():
    return master.data_dir() / "places_added.json"


def added() -> dict:
    f = _file()
    k = (str(f), f.stat().st_mtime_ns) if f.exists() else None
    if _cache["key"] != k:
        _cache.update(key=k, rows=json.loads(f.read_text(encoding="utf-8")) if k else {})
    return dict(_cache["rows"])


def cities() -> dict:
    """{city: [names]}: config "cities" and the confirmed names; a confirmed name may belong to a new city."""
    from .rules import CONFIG
    out = {c: list(n) for c, n in CONFIG.get("cities", {}).items()}
    for r in added().values():
        out.setdefault(r["city"], []).append(r["name"])
    return out


def _lookup(place, groups: dict) -> str | None:
    p = key(place)
    if not p:
        return None
    for city, names in groups.items():
        if p in {key(n) for n in [city] + names}:
            return city
    for city, names in groups.items():                     # city + terminal: 'HAIPHONG DINH VU'
        al = {key(n) for n in [city] + names}
        if any(p.startswith(a) and p[len(a):] in al for a in al if len(a) >= 5):
            return city
    return None


def city(place) -> str | None:
    """Port / place name -> its city (e.g. CAT LAI -> HO CHI MINH CITY), None when the name is not known."""
    return _lookup(place, cities())


def _one_typo(a: str, b: str) -> bool:
    """One letter wrong, missing, extra, or two neighbours swapped."""
    if len(a) > len(b):
        a, b = b, a
    i = next((n for n, (x, y) in enumerate(zip(a, b)) if x != y), len(a))
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:] or (a[i:i + 2] == b[i:i + 2][::-1] and a[i + 2:] == b[i + 2:])
    return len(b) - len(a) == 1 and a[i:] == b[i + 1:]


def misspelled(place) -> str | None:
    """The city an unknown name is a misspelling of: one typo away from a name of exactly one city. Short names
    (under 7 letters) are never matched: another real place can be one letter away."""
    p = key(place)
    if len(p) < 7 or city(place):
        return None
    hits = {c for c, names in cities().items() for n in [c] + names if len(key(n)) >= 7 and _one_typo(p, key(n))}
    return hits.pop() if len(hits) == 1 else None


def _save(rows: dict, what: dict):
    master.data_dir().mkdir(parents=True, exist_ok=True)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_file())
    _cache["key"] = ""
    with open(master.data_dir() / "places_log.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps(dict(at=datetime.now().isoformat(timespec="seconds"), **what), ensure_ascii=False) + "\n")


def add(name, to_city, docs=(), by: str = "") -> None:
    """Add one name the user confirmed. ValueError: no usable name / city, or the name already belongs to a city."""
    name, to_city = str(name or "").strip(), re.sub(r"\s+", " ", str(to_city or "")).strip().upper()
    if len(key(name)) < 2 or len(key(to_city)) < 2 or city(name):
        raise ValueError(f"{name}: {to_city}")
    to_city = city(to_city) or to_city                     # 'HCM' typed as the city: its full name
    row = dict(name=name, city=to_city, added_at=datetime.now().isoformat(timespec="seconds"), by=by, docs=list(docs))
    _save({**added(), key(name): row}, dict(added=name, city=to_city, by=by, docs=list(docs)))


def remove(k) -> None:
    rows = added()
    if rows.pop(k, None):
        _save(rows, dict(removed=k))


def suggest(sessions: list) -> list:
    """Place names on the B/Ls of the saved reviews that belong to no known city, with the city of the same B/L's place of
    delivery / port of discharge as a suggestion. B/Ls that point to different cities: conflict, no suggestion."""
    groups, out = cities(), {}
    for s in sessions:
        for d in s.get("docs", []):
            if d.get("kind") != "BL":
                continue
            val = lambda k: ((d.get("fields") or {}).get(k) or {}).get("value")
            known = next((c for c in (_lookup(val(k), groups) for k in ("delivery", "pod")) if c), None)
            for k in ("final_dest", "delivery", "pod"):
                name = val(k)
                if not isinstance(name, str) or len(key(name)) < 2 or _lookup(name, groups):
                    continue
                r = out.setdefault(key(name), dict(key=key(name), name=name.strip(), cities={}, docs=[]))
                if d["name"] not in r["docs"]:
                    r["docs"].append(d["name"])
                    if known:
                        r["cities"][known] = r["cities"].get(known, 0) + 1
    for r in out.values():
        r["conflict"] = sorted(r["cities"]) if len(r["cities"]) > 1 else []
        r["city"] = next(iter(r["cities"])) if len(r["cities"]) == 1 else ""
    return sorted(out.values(), key=lambda r: (not r["city"], r["name"]))
