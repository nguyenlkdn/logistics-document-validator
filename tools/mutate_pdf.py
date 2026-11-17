"""Make a synthetic test set: copy a document set and change text in its PDFs, to test that a rule catches an error.

  python tools/mutate_pdf.py SPEC.json [SPEC2.json ...]

SPEC (keep it next to the test sets in tests/baseline/, which git ignores — it names confidential values):
  {"source": "SET.zip or folder (relative to the spec)", "output": "NEW_SET_FOLDER",
   "keep": ["glob", ...],                       # optional: only these files (default: all)
   "edits": [{"file": "glob", "page": 1, "find": "old text", "replace": "new text",
              "nth": 1,                          # optional: which occurrence on that page (default 1; 0 = all)
              "below": "anchor text",            # optional: first occurrence under this text on the page
              "whole_line": true}]}              # optional: blank the whole line through the match

The original text is blanked out (redaction) and the replacement written at the same place, same size, in
Helvetica. Only the copies are changed; each edit must match, or the script stops.
"""
import fnmatch
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import pymupdf


def _size_at(page, rect) -> float:
    best = 9.0
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                if pymupdf.Rect(sp["bbox"]).intersects(rect):
                    return sp["size"]
    return best


def apply(pdf_path: Path, edits: list[dict]):
    doc = pymupdf.open(pdf_path)
    for e in edits:
        page = doc[e.get("page", 1) - 1]
        hits = page.search_for(e["find"])
        if e.get("below"):
            anchor = page.search_for(e["below"])
            if not anchor:
                raise SystemExit(f"{pdf_path.name} p{e.get('page', 1)}: anchor {e['below']!r} not found")
            hits = sorted((h for h in hits if h.y0 > anchor[0].y0 + 1), key=lambda h: (round(h.y0), h.x0))[:1]
        nth = e.get("nth", 1)
        pick = hits if nth == 0 else hits[nth - 1:nth]
        if not pick:
            raise SystemExit(f"{pdf_path.name} p{e.get('page', 1)}: {e['find']!r} (occurrence {nth}) not found")
        for r in pick:
            size = _size_at(page, r)
            new = e["replace"]
            need = pymupdf.get_text_length(new, fontname="helv", fontsize=size)
            box = pymupdf.Rect(r.x0, r.y0, max(r.x1, r.x0 + need + 1), r.y1)
            if e.get("whole_line"):                     # blank the whole text line through the match
                r = pymupdf.Rect(0, r.y0 + 0.5, page.rect.width, r.y1 - 0.5)
            # redact only the middle band of the text: tightly stacked lines (a wrapped number) overlap in height
            band = pymupdf.Rect(r.x0, r.y0 + r.height * 0.35, r.x1, r.y1 - r.height * 0.35)
            page.add_redact_annot(band, fill=(1, 1, 1))
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
            if new:
                page.insert_text((box.x0, r.y1 - (r.height - size) / 2 - size * 0.18), new, fontname="helv", fontsize=size)
    tmp = pdf_path.with_suffix(".tmp.pdf")
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    tmp.replace(pdf_path)


def build(spec_path: Path):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    src = (spec_path.parent / spec["source"]).resolve()
    out = (spec_path.parent / spec["output"]).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    work = Path(tempfile.mkdtemp())
    if src.suffix.lower() == ".zip":
        zipfile.ZipFile(src).extractall(work)
    else:
        shutil.copytree(src, work / src.name)
    files = [p for p in work.rglob("*.pdf")]
    keep = spec.get("keep")
    for p in files:
        if keep and not any(fnmatch.fnmatch(p.name, g) for g in keep):
            continue
        shutil.copy2(p, out / p.name)
    for e in spec["edits"]:
        targets = [p for p in out.glob("*.pdf") if fnmatch.fnmatch(p.name, e["file"])]
        if len(targets) != 1:
            raise SystemExit(f"edit {e} matches {len(targets)} files")
        apply(targets[0], [e])
    shutil.rmtree(work, ignore_errors=True)
    print(f"{out.name}: {len(list(out.glob('*.pdf')))} PDFs, {len(spec['edits'])} edits")


if __name__ == "__main__":
    for a in sys.argv[1:]:
        build(Path(a))
