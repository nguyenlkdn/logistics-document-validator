"""Typo sweep: does a one-character typo in any value LDV reads ever go unreported? (developer tool)

  python tools/typo_sweep.py tests/baseline/SET.zip [more sets…] [--kinds lower,swap,digit] [--jobs N] [--json OUT]

For every value LDV reads from a document (each field, list entry and item cell that has a place on the page),
a copy of that PDF is made with the printed value changed by one character, the package is checked again, and
the result compared with the check of the unchanged package:

  lower  one capital letter written in lowercase      AB-X10(W1)VN  -> AB-x10(W1)VN
  swap   a letter/digit look-alike                    ACME2611E001  -> ACME26l1E001 (0<->O, 1<->I, 5<->S, 8<->B)
  digit  one digit changed                            1,043         -> 1,053

Each typo ends in one of:

  CAUGHT   a new finding (or a new "could not read" entry) appears: the user sees the problem
  SILENT   nothing new: the typo would go through unnoticed. Shown with what happened to the value:
             dropped  LDV no longer reads the value (a reading gap: the pattern is too strict)
             typo     LDV reads the value with the typo, but no rule compares it (a rule gap)
             same     LDV reads the same value as before (the typo is in a part that does not count)
  CRASH    the check stops with an error on this typo
  SKIPPED  the value could not be found on the page to change it

The documents are confidential: run this only on the test sets in tests/baseline/ and never commit its output.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LDV_DATA_DIR", tempfile.mkdtemp(prefix="ldv_sweep_data_"))
from engine import _dllpath  # noqa: E402,F401
import pymupdf  # noqa: E402
from engine import master  # noqa: E402
from engine.extract import Field, load  # noqa: E402
from engine.rules import unrecognised, validate_checks  # noqa: E402

SWAP = {"0": "O", "O": "0", "1": "I", "I": "1", "5": "S", "S": "5", "8": "B", "B": "8"}


def typo(s: str, kind: str) -> str | None:
    """One-character typo of the printed text s, in the middle of the value where possible."""
    idx = list(range(len(s)))
    idx = idx[len(idx) // 2:] + idx[:len(idx) // 2][::-1]           # start in the middle, the most telling place
    for i in idx:
        c = s[i]
        if kind == "lower" and c.isupper() and (i > 0 and s[i - 1].isalnum()):
            return s[:i] + c.lower() + s[i + 1:]
        if kind == "swap" and c in SWAP and (i > 0 or len(s) > 1):
            return s[:i] + SWAP[c] + s[i + 1:]
        if kind == "digit" and c.isdigit():
            return s[:i] + str((int(c) + 1) % 10) + s[i + 1:]
    return None


def walk(obj, path):
    """Every Field inside a document's f / lists / items, with a readable path."""
    if isinstance(obj, Field):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, path + (k,))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from walk(v, path + (i,))


def fields(d):
    seen = set()
    for top in ("f", "lists", "items", "pl_items"):
        for path, f in walk(getattr(d, top), (top,)):
            if not isinstance(f.raw, str) or len(f.raw.strip()) < 2:
                continue
            key = (f.page, round(f.line.y, 1), f.start, f.end, f.raw)
            if key in seen:
                continue
            seen.add(key)
            yield path, f


def get(d, path):
    obj = d
    for p in path:
        try:
            obj = getattr(obj, p) if isinstance(p, str) and p in ("f", "lists", "items", "pl_items") and obj is d \
                else obj[p]
        except (KeyError, IndexError, TypeError):
            return None
    return obj


def place(page, f: Field):
    """The rectangle of the value's printed text on the page."""
    spans = f.line.spans_for(f.start, f.end) if f.line.spans else []
    if spans:
        clip = pymupdf.Rect(spans[0].bbox)
        for s in spans[1:]:
            clip |= pymupdf.Rect(s.bbox)
        clip = clip + (-2, -1, 2, 1)
        hits = page.search_for(f.raw.strip(), clip=clip)
        if hits:
            return hits[0]
        return None
    hits = page.search_for(f.raw.strip())            # a value without a line position (Form D box 6 marks)
    return hits[0] if hits else None


def size_at(page, rect):
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                if pymupdf.Rect(sp["bbox"]).intersects(rect):
                    return sp["size"]
    return 9.0


def write_typo(src: Path, dst: Path, f: Field, new: str) -> bool:
    doc = pymupdf.open(src)
    page = doc[f.page]
    r = place(page, f)
    if r is None:
        doc.close()
        return False
    size = size_at(page, r)
    band = pymupdf.Rect(r.x0, r.y0 + r.height * 0.35, r.x1, r.y1 - r.height * 0.35)
    page.add_redact_annot(band, fill=(1, 1, 1))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    page.insert_text((r.x0, r.y1 - (r.height - size) / 2 - size * 0.18), new, fontname="helv", fontsize=size)
    doc.save(dst, garbage=3, deflate=True)
    doc.close()
    return True


def sig(docs):
    """(findings, unread entries, checks not run). A rule that fails is isolated by the check runner (LDV 2.3);
    here it still counts as a CRASH, so the sweep keeps seeing it."""
    fs, checks = validate_checks(docs)
    err = [c for c in checks if c.reason == "internal_error"]
    if err:
        raise RuntimeError(f"rule error in {err[0].detail.get('rule')} ({err[0].detail.get('error')})")
    return ({f"{f.severity}|{f.key}|{f.doc_names[0]}|{f.current}->{f.suggested}" for f in fs},
            {f"{u['doc']}: {u['what']}" for u in unrecognised(docs, [])},
            {f"{c.check_id}|{c.group_id}|{c.doc}" for c in checks if c.status == "NOT_RUN"})


def plain(v):
    if isinstance(v, Field):
        return plain(v.value)
    return v if isinstance(v, (str, int, float, type(None))) else repr(v)


_STATE = {}


def _init(pdfs):
    from engine.extract import EXCEL, load_excel
    docs = []
    for p in map(Path, pdfs):
        if p.suffix.lower() in EXCEL:        # invoice / contract workbooks: read as context, typos not planted
            docs += load_excel(p, Path(tempfile.mkdtemp(prefix="ldv_sweep_xl_")))
        else:
            docs.append(load(p))
    _STATE["pdfs"] = [Path(p) for p in pdfs]
    _STATE["docs"] = [d for d in docs if d]
    _STATE["base"] = sig(_STATE["docs"])


def _one(job):
    di, path, kind = job
    docs = _STATE["docs"]
    d = docs[di]
    f = get(d, path)
    new_raw = typo(f.raw.strip(), kind)
    out = dict(doc=d.name, kind_doc=d.kind, field=".".join(map(str, path)), typo=kind,
               before=f.raw.strip(), after=new_raw, page=f.page + 1)
    if new_raw is None:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="ldv_typo_"))
    try:
        dst = tmp / d.path.name
        if not write_typo(d.path, dst, f, new_raw):
            return out | dict(result="SKIPPED")
        try:
            nd = load(dst, d.kind)
        except Exception as e:                            # reading the document fails on this typo
            return out | dict(result="CRASH", value="-", how=f"reading: {type(e).__name__}: {e}")
        if nd is None:
            return out | dict(result="CAUGHT", how="document no longer recognised")
        nd.path = d.path                                  # same name as before, so findings compare
        new_docs = docs[:di] + [nd] + docs[di + 1:]
        try:
            fs, un, nr = sig(new_docs)
        except Exception as e:                            # the check itself fails on this typo: worst case
            return out | dict(result="CRASH", value="-", how=f"{type(e).__name__}: {e}")
        base_fs, base_un, base_nr = _STATE["base"]
        added = sorted(fs - base_fs) + sorted(un - base_un)
        nf = get(nd, path)
        if nf is None or not isinstance(nf, Field):
            what = "dropped"
        elif plain(nf) == plain(f):
            what = "same"
        else:
            what = "typo"
        if added:
            return out | dict(result="CAUGHT", how=added[0], value=what)
        # not CAUGHT by the old measure (no new finding); a check that stopped running is still visible (AMBER)
        new_nr = sorted(nr - base_nr)
        return out | dict(result="SILENT", value=what, read=plain(nf) if isinstance(nf, Field) else None,
                          not_run=new_nr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def sweep(set_path: Path, kinds, jobs: int, master_xlsx):
    work = Path(tempfile.mkdtemp(prefix="ldv_sweep_"))
    if set_path.suffix.lower() == ".zip":
        zipfile.ZipFile(set_path).extractall(work)
    else:
        shutil.copytree(set_path, work / set_path.name)
    pdfs = sorted(str(p) for p in work.rglob("*") if p.suffix.lower() in (".pdf", ".xlsx", ".xlsm"))
    if master_xlsx:                                     # once, here: the workers only read it
        master.import_xlsx(Path(master_xlsx))
    _init(pdfs)
    todo = [(di, path, k) for di, d in enumerate(_STATE["docs"]) if not getattr(d, "source_file", "")
            for path, _f in fields(d) for k in kinds]
    with ProcessPoolExecutor(jobs, initializer=_init, initargs=(pdfs,)) as ex:
        res = [r for r in ex.map(_one, todo, chunksize=4) if r]
    shutil.rmtree(work, ignore_errors=True)
    return res


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opt = dict(a.split("=", 1) if "=" in a else (a, "1") for a in sys.argv[1:] if a.startswith("--"))
    kinds = opt.get("--kinds", "lower,swap,digit").split(",")
    jobs = int(opt.get("--jobs", os.cpu_count() or 4))
    mx = ROOT / "tests" / "baseline" / "master_hs.xlsx"
    allres = []
    for a in args:
        res = sweep(Path(a), kinds, jobs, str(mx) if mx.exists() else None)
        for r in res:
            r["set"] = Path(a).name
        allres += res
        n = {k: sum(r["result"] == k for r in res) for k in ("CAUGHT", "SILENT", "SKIPPED", "CRASH")}
        vis = sum(r["result"] == "SILENT" and bool(r.get("not_run")) for r in res)
        print(f"== {Path(a).name}: {len(res)} typos  caught {n['CAUGHT']}  silent {n['SILENT']}  skipped {n['SKIPPED']}  "
              f"crash {n['CRASH']}  (silent but a check shows NOT_RUN: {vis})")
        for r in sorted(res, key=lambda r: (r["result"], r["value"] if "value" in r else "", r["field"])):
            if r["result"] == "CRASH":
                print(f"  CRASH            {r['typo']:5} {r['kind_doc']:2} p{r['page']} {r['field']:40} "
                      f"{r['before']!r} -> {r['after']!r}  {r['how']}")
            if r["result"] == "SILENT":
                print(f"  SILENT [{r['value']:7}] {r['typo']:5} {r['kind_doc']:2} p{r['page']} {r['field']:40} "
                      f"{r['before']!r} -> {r['after']!r}" + (f"  read {r['read']!r}" if r['value'] == 'typo' else "")
                      + (f"  NOT_RUN: {', '.join(r['not_run'][:3])}" if r.get("not_run") else ""))
    if "--json" in opt:
        Path(opt["--json"]).write_text(json.dumps(allres, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
