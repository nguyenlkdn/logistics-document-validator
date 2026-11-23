"""Suggested additions to the HS master list, from the documents already checked (saved reviews).

A suggestion is never used by itself: the user confirms each one on the Reference data page (engine/master.add).
For every invoice model that the master list does not have: the HS codes printed for it on certificates of origin, the
documents they were read from, and what speaks for or against each code:

  B/L      the B/L of the same invoice lists a heading the code falls under / does not
  series   models of the same series in the master list ('AB-X10' of 'AB-X10(W1)'); when they all have one code that
           begins with the printed one, that longer code is suggested
  conflict the documents print different codes for the model
  single   one certificate prints the code and nothing else speaks for it
  typo     the model is a master model but for look-alike characters (O/0, I/1, S/5, B/8)
"""
import re

from . import master

_LOOKALIKE = str.maketrans("OISB", "0158")


def _val(d: dict, k: str):
    return ((d.get("fields") or {}).get(k) or {}).get("value")


def _base(k: str) -> str:
    return k.split("(")[0]


def suggest(sessions: list, items: dict) -> list:
    """sessions: review dicts (review.json), newest first; items: the master list {key: {model, hs}}."""
    seen, out = {}, {}
    for s in sessions:
        docs = s.get("docs", [])
        bl = {}                                            # invoice no. -> HS headings on its B/L
        for d in docs:
            if d.get("kind") == "BL" and _val(d, "invoice_no"):
                heads = re.findall(r"\d[\d.]{3,}", str(_val(d, "hs_all") or _val(d, "hs") or ""))
                bl.setdefault(_val(d, "invoice_no"), set()).update(master.digits(h) for h in heads)
        invoiced = {}
        for d in docs:
            if d.get("kind") == "CI":
                for it in d.get("items", []):
                    if it.get("model"):
                        invoiced.setdefault(master.key(it["model"]), (str(it["model"]).strip(), d["name"], it.get("_page")))
        for k, (model, doc, page) in invoiced.items():
            if k not in items:
                out.setdefault(k, dict(key=k, model=model, codes={}, invoices=[]))["invoices"].append((doc, page))
        for d in docs:
            if d.get("kind") != "CO":
                continue
            for it in d.get("items", []):
                k, hs = master.key(it.get("model")), master.digits(it.get("hs"))
                if k not in out or k not in invoiced or len(hs) not in (6, 8, 10):
                    continue                               # a model only the certificate names may be its typo
                if (k, hs, d["name"]) in seen:
                    continue
                seen[(k, hs, d["name"])] = True
                c = out[k]["codes"].setdefault(hs, dict(docs=[], bl_ok=0, bl_no=0))
                c["docs"].append((s.get("shipment", ""), d["name"], it.get("_page")))
                heads = bl.get(it.get("inv_ref"))
                if heads:
                    c["bl_ok" if any(hs.startswith(h) or h.startswith(hs) for h in heads) else "bl_no"] += 1
    return sorted((_finish(r, items) for r in out.values()), key=lambda r: (r["state"] != "ok", not r["hs"], r["model"]))


def _finish(r: dict, items: dict) -> dict:
    codes = r["codes"]
    series = sorted({i["hs"] for k, i in items.items() if _base(k) == _base(r["key"])})
    typo = next((i["model"] for k, i in items.items() if k.translate(_LOOKALIKE) == r["key"].translate(_LOOKALIKE)), None)
    # codes that only differ in length (851111 / 85111100) are one code, the longer one says more
    longest = [h for h in codes if not any(x != h and x.startswith(h) for x in codes)]
    r["conflict"] = sorted(codes) if len(longest) > 1 else []
    r["hs"] = "" if len(longest) != 1 else longest[0]
    r["printed"], r["from_series"], r["series"] = r["hs"], False, series
    r["series_differs"] = bool(r["hs"] and series and not any(h.startswith(r["hs"]) or r["hs"].startswith(h) for h in series))
    if r["hs"] and len(series) == 1 and series[0].startswith(r["hs"]) and len(series[0]) > len(r["hs"]):
        r["hs"], r["from_series"] = series[0], True
    r["typo_of"] = typo
    r["n_docs"] = sum(len(c["docs"]) for c in codes.values())
    r["bl_no"] = sum(c["bl_no"] for c in codes.values())
    r["bl_ok"] = sum(c["bl_ok"] for c in codes.values())
    r["state"] = ("none" if not codes else "check" if r["conflict"] or typo or r["bl_no"] or r["series_differs"]
                  else "ok" if r["bl_ok"] or r["from_series"] or r["n_docs"] > 1 else "single")   # one certificate only
    return r
