"""HS master list: the company's own Excel (model -> HS code) converted to LDV's internal tracking file.

The Excel stays wherever the user keeps it and can be edited any time. LDV remembers its path and
re-imports it automatically when it changes (checked before every shipment check). Nothing is stored in
the repository: the tracking files live in the data folder (config "data_dir", env LDV_DATA_DIR):

  master_hs.json       current list {model: {hs, row}} + source path, modification time, skipped rows
  master_hs_log.jsonl  one line per import: models added / removed / changed

Command line (also used by Import-HS.bat / import_hs.sh):
  python -m engine.master "path/to/MA HS.xlsx"     import (and remember) this file
  python -m engine.master                          re-import the remembered file if it changed; show status
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

_CFG = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text(encoding="utf-8"))
MODEL_HEAD = re.compile(r"m[aã]\s*(npl|sp)|model|item\s*code|part", re.I)
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
                cells = [str(c or "") for c in row]
                mc = next((i for i, c in enumerate(cells) if MODEL_HEAD.search(c)), None)
                hc = next((i for i, c in enumerate(cells) if HS_HEAD.search(c) and i != mc), None)
                if mc is None or hc is None:
                    continue
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
                    else:
                        items.setdefault(key(model), dict(model=str(model).strip(), hs=d, row=n))
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
    now = datetime.now().isoformat(timespec="seconds")
    data = dict(source=str(path), source_mtime=path.stat().st_mtime,
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
        if src.exists() and src.stat().st_mtime != d["source_mtime"]:
            if hashlib.sha1(src.read_bytes()).hexdigest() != d.get("source_sha1"):
                return import_xlsx(src)
    except Exception:                                     # e.g. the file is open and locked in Excel
        return None
    return None


def hs_for(model) -> str | None:
    d = load()
    it = d["items"].get(key(model)) if d else None
    return it["hs"] if it else None


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
            print(f"  changed {c['model']}: {fmt(c['old'])} -> {fmt(c['new'])}")
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
