"""HS master list: the company's own Excel (model -> HS code, goods name, unit) converted to LDV's internal tracking file.

The Excel stays wherever the user keeps it and can be edited any time. LDV remembers its path and
re-imports it automatically when it changes (checked before every shipment check). Nothing is stored in
the repository: the tracking files live in the data folder (config "data_dir", env LDV_DATA_DIR):

  master_hs.json       current list {model: {hs, name, unit, row}} + source path, modification time, skipped rows
  master_hs_log.jsonl  one line per import: models added / removed / changed
  master_hs_added.json models the user added from checked documents (engine/hs_suggest.py); used until the Excel lists
                       the model: the Excel always wins, and LDV never changes it

Command line (also used by Import-HS.bat / import_hs.sh):
  python -m engine.master "path/to/MA HS.xlsx"     import (and remember) this file
  python -m engine.master                          re-import the remembered file if it changed; show status
"""
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

_CFG = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text(encoding="utf-8"))
MODEL_HEAD = re.compile(r"m[aã]\s*(npl|sp)|model|item\s*code|part", re.I)
NAME_HEAD = re.compile(r"^\s*t[eê]n\b|name|description|m[oô] t[aả]", re.I)
UNIT_HEAD = re.compile(r"[dđ][oơ]n\s*v[iị]|\b[dđ]vt\b|\bunit\b", re.I)
FORMAT = 2                                   # of master_hs.json; an older one is imported again (2: name and unit)
HS_HEAD = re.compile(r"\bhs\b|m[aã]\s*hs", re.I)
_cache = {"key": None, "data": None}


def data_dir() -> Path:
    return Path(os.environ.get("LDV_DATA_DIR") or os.path.expanduser(_CFG.get("data_dir", "~/Documents/LDV_data")))


def _json() -> Path:
    return data_dir() / "master_hs.json"


def key(model) -> str:
    """Model as a lookup key: upper case, no spaces."""
    return re.sub(r"\s+", "", str(model or "")).upper()


def digits(hs) -> str:
    return re.sub(r"\D", "", str(hs or ""))


def fmt(hs: str) -> str:
    """85166010 -> 8516.60.10 (the way a Form D prints it)."""
    d = digits(hs)
    return ".".join(x for x in (d[:4], d[4:6], d[6:8], d[8:]) if x)


def read_xlsx(path: Path) -> tuple[dict, list]:
    """(items, skipped). Finds the header row by its titles (e.g. 'Mã NPL/SP' and 'Mã HS'), any sheet."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            for h, row in enumerate(rows[:15]):
                cells = [unicodedata.normalize("NFC", str(c or "")) for c in row]
                mc = next((i for i, c in enumerate(cells) if MODEL_HEAD.search(c)), None)
                hc = next((i for i, c in enumerate(cells) if HS_HEAD.search(c) and i != mc), None)
                if mc is None or hc is None:
                    continue
                other = [i for i in range(len(cells)) if i not in (mc, hc)]
                nc = next((i for i in other if NAME_HEAD.search(cells[i])), None)
                uc = next((i for i in other if i != nc and UNIT_HEAD.search(cells[i])), None)
                text = lambda r, c: re.sub(r"\s+", " ", str(r[c])).strip() if c is not None and c < len(r) and r[c] is not None else ""
                items, skipped = {}, []
                for n, r in enumerate(rows[h + 1:], start=h + 2):
                    model = r[mc] if mc < len(r) else None
                    hs = r[hc] if hc < len(r) else None
                    if model in (None, "") and hs in (None, ""):
                        continue
                    d = digits(hs)
                    if isinstance(hs, (int, float)) and 0 < len(d) < 8:
                        d = d.zfill(8)                      # Excel dropped a leading zero
                    if model in (None, ""):
                        skipped.append(dict(row=n, hs=d, reason="no model code"))
                    elif len(d) not in (6, 8, 10):
                        skipped.append(dict(row=n, model=str(model).strip(), hs=str(hs), reason="HS code is not 6, 8 or 10 digits"))
                    elif key(model) in items and items[key(model)]["hs"] != d:
                        skipped.append(dict(row=n, model=str(model).strip(), hs=d,
                                            reason=f"listed twice with different HS (row {items[key(model)]['row']})"))
                    elif key(model) in items and any(
                            text(r, c) and items[key(model)][k] and text(r, c).upper() != items[key(model)][k].upper()
                            for k, c in (("name", nc), ("unit", uc))):
                        skipped.append(dict(row=n, model=str(model).strip(), hs=d,
                                            reason=f"listed twice with different name / unit (row {items[key(model)]['row']})"))
                    else:
                        items.setdefault(key(model), dict(model=str(model).strip(), hs=d, name=text(r, nc), unit=text(r, uc),
                                                          row=n))
                return items, skipped
        raise ValueError("No header row with a model column (e.g. 'Mã NPL/SP') and an HS column (e.g. 'Mã HS') found")
    finally:
        wb.close()


def import_xlsx(path) -> dict:
    """Convert the Excel into master_hs.json, log what changed, remember the path. Returns a summary."""
    path = Path(path).resolve()
    items, skipped = read_xlsx(path)
    old = (load() or {}).get("items", {})
    added = sorted(k for k in items if k not in old)
    removed = sorted(k for k in old if k not in items)
    changed = [dict(model=k, old=old[k]["hs"], new=items[k]["hs"]) for k in sorted(items) if k in old and old[k]["hs"] != items[k]["hs"]]
    if (load() or {}).get("format") == FORMAT:             # the first import with names and units is no change of them
        changed += [dict(model=k, field=c, old=old[k].get(c, ""), new=items[k][c]) for k in sorted(items) if k in old
                    for c in ("name", "unit") if old[k].get(c, "") != items[k][c]]
    now = datetime.now().isoformat(timespec="seconds")
    data = dict(format=FORMAT, source=str(path), source_mtime=path.stat().st_mtime,
                source_sha1=hashlib.sha1(path.read_bytes()).hexdigest(), imported_at=now, items=items, skipped=skipped)
    data_dir().mkdir(parents=True, exist_ok=True)
    tmp = _json().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_json())
    with open(data_dir() / "master_hs_log.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps(dict(imported_at=now, source=str(path), count=len(items), added=added, removed=removed,
                                  changed=changed, skipped=len(skipped)), ensure_ascii=False) + "\n")
    _cache["key"] = None
    return dict(count=len(items), added=added, removed=removed, changed=changed, skipped=skipped, source=str(path))


def load() -> dict | None:
    f = _json()
    if not f.exists():
        return None
    k = (str(f), f.stat().st_mtime)
    if _cache["key"] != k:
        _cache.update(key=k, data=json.loads(f.read_text(encoding="utf-8")))
    return _cache["data"]


def refresh() -> dict | None:
    """Re-import the remembered Excel if it was saved since the last import. Returns the import summary or None.
    A missing or unreadable file keeps the last imported list."""
    d = load()
    if not d:
        return None
    src = Path(d["source"])
    try:
        if src.exists() and d.get("format") != FORMAT:
            return import_xlsx(src)
        if src.exists() and src.stat().st_mtime != d["source_mtime"]:
            if hashlib.sha1(src.read_bytes()).hexdigest() != d.get("source_sha1"):
                return import_xlsx(src)
    except Exception:                                     # e.g. the file is open and locked in Excel
        return None
    return None


def _added_file() -> Path:
    return data_dir() / "master_hs_added.json"


def added(current: bool = True) -> dict:
    """{key: {model, hs, added_at, by, docs}} the user added from documents; current: without those the Excel has now."""
    f = _added_file()
    k = (str(f), f.stat().st_mtime_ns) if f.exists() else None
    if _cache.get("added_key") != k:
        _cache.update(added_key=k, added=json.loads(f.read_text(encoding="utf-8")) if k else {})
    excel = (load() or {}).get("items", {})
    return {m: v for m, v in _cache.get("added", {}).items() if not (current and m in excel)}


def _save_added(rows: dict, what: dict):
    data_dir().mkdir(parents=True, exist_ok=True)
    tmp = _added_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_added_file())
    _cache["added_key"] = ""
    with open(data_dir() / "master_hs_log.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps(dict(at=datetime.now().isoformat(timespec="seconds"), **what), ensure_ascii=False) + "\n")


def add(model, hs, docs=(), by: str = "", name: str = "", unit: str = "") -> None:
    """Add one model the user confirmed. ValueError: not a 6, 8 or 10 digit code, or the Excel already has the model."""
    d, k = digits(hs), key(model)
    if not k or len(d) not in (6, 8, 10) or re.search(r"[^\d.\s]", str(hs)):
        raise ValueError(f"{model}: {hs}")
    if k in (load() or {}).get("items", {}):
        raise ValueError(f"{model}: in Excel")
    row = dict(model=str(model).strip(), hs=d, name=str(name or "").strip(), unit=str(unit or "").strip(), added_at=datetime.now().isoformat(timespec="seconds"), by=by, docs=list(docs))
    _save_added({**added(False), k: row}, dict(document_added=k, hs=d, by=by, docs=list(docs)))


def remove(model) -> None:
    rows = added(False)
    if rows.pop(key(model), None):
        _save_added(rows, dict(document_removed=key(model)))


def added_xlsx() -> bytes:
    """The added models as an Excel with the master list's columns, to copy into the company's list."""
    import io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Mã NPL/SP", "Mã HS", "TÊN", "ĐƠN VỊ"])
    for r in added().values():
        ws.append([r["model"], r["hs"], r.get("name", ""), r.get("unit", "")])
        ws.cell(ws.max_row, 2).number_format = "@"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def row_for(model) -> dict | None:
    """The list's row of a model: {model, hs, name, unit}; the Excel first, then the models the user added."""
    d = load()
    return (d["items"].get(key(model)) or added().get(key(model))) if d else None


def hs_for(model) -> str | None:
    it = row_for(model)
    return it["hs"] if it else None


def has_column(col: str) -> bool:
    """The list gives this ("name" / "unit") for at least one model."""
    return any(r.get(col) for r in [*((load() or {}).get("items", {})).values(), *added().values()])


def agrees(printed, ref: str, model=None, form: str = "D") -> bool:
    """A printed HS code against the master code. The same digits; a Form E prints the 6-digit subheading (ASEAN-China
    rules), so there the master code must begin with it; a 6-digit code the user added from a Form E is compared on its
    6 digits."""
    p = digits(printed)
    if p == ref or (form == "E" and len(p) == 6 and ref.startswith(p)):
        return True
    return len(ref) == 6 and key(model) in added() and p.startswith(ref)


def status() -> dict:
    d = load()
    if not d:
        return dict(loaded=False)
    src = Path(d["source"])
    return dict(loaded=True, count=len(d["items"]), source=d["source"], imported_at=d["imported_at"],
                skipped=d["skipped"], source_found=src.exists(),
                outdated=src.exists() and src.stat().st_mtime != d["source_mtime"])


def _main(argv) -> int:
    if argv:
        s = import_xlsx(argv[0])
        print(f"Imported {s['count']} models from {s['source']}")
        print(f"  added {len(s['added'])}, removed {len(s['removed'])}, changed {len(s['changed'])}")
        for c in s["changed"]:
            print(f"  changed {c['model']}: " + (f"{c['field']} {c['old']} -> {c['new']}" if c.get("field") else
                                               f"{fmt(c['old'])} -> {fmt(c['new'])}"))
    else:
        r = refresh()
        if r:
            print(f"Re-imported {r['count']} models (file changed)")
        st = status()
        if not st["loaded"]:
            print("No HS master list yet. Usage: python -m engine.master \"path/to/MA HS.xlsx\"")
            return 1
        print(f"HS master: {st['count']} models from {st['source']} (imported {st['imported_at']})")
    for sk in (load() or {}).get("skipped", []):
        print(f"  skipped row {sk['row']}: {sk.get('model', '')} {sk['reason']}")
    print(f"Tracking file: {_json()}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
