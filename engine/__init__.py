"""LDV engine: check one shipment's document set and write a bilingual report (documents are never modified)."""
import hashlib
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import _dllpath  # noqa: F401  (must come before anything that imports pymupdf)
from . import evidence, master, report
from .extract import load
from .rules import CONFIG, unrecognised, validate


@dataclass
class Result:
    name: str
    docs: list
    skipped: list
    findings: list
    unrecognised: list
    out_dir: Path | None = None
    excel: Path | None = None
    markdown: str = ""
    workdir: Path | None = field(default=None, repr=False)
    doc_files: dict = field(default_factory=dict)
    marks: dict = field(default_factory=dict)      # document name -> finding locations (preview highlights)  # document name -> its copy in the report folder (preview)
    fingerprint: str = ""          # hash of the PDF contents: same files -> same fingerprint (history)


def report_root() -> Path:
    return Path(os.environ.get("LDV_REPORT_DIR") or os.path.expanduser(CONFIG["report_dir"]))


def _safe_extract(zf: Path, dest: Path):
    with zipfile.ZipFile(zf) as z:
        for m in z.infolist():
            target = (dest / m.filename).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError(f"Unsafe path in zip: {m.filename}")
        z.extractall(dest)


def collect(inputs: list[Path], workdir: Path) -> list[Path]:
    """Copy/extract inputs (zip, folder or files) into workdir and return every file found."""
    for p in inputs:
        if p.is_dir():
            shutil.copytree(p, workdir / p.name, dirs_exist_ok=True)
        elif p.suffix.lower() == ".zip":
            _safe_extract(p, workdir / p.stem)
        else:
            shutil.copy2(p, workdir / p.name)
    junk = lambda x: x.name.startswith(".") or x.name.lower() == "thumbs.db" or "__MACOSX" in x.parts
    return sorted(x for x in workdir.rglob("*") if x.is_file() and not junk(x))


def check(inputs: list[Path], name: str | None = None, out_root: Path | None = None,
          with_evidence: bool = True, keep_workdir: bool = False) -> Result:
    master.refresh()                               # the HS master Excel may have been edited since last time
    workdir = Path(tempfile.mkdtemp(prefix="ldv_"))
    pdfs = collect(inputs, workdir)
    fp = hashlib.sha1("".join(sorted(hashlib.sha1(p.read_bytes()).hexdigest() for p in pdfs
                                     if p.suffix.lower() == ".pdf")).encode()).hexdigest()
    docs, skipped = [], []
    for p in pdfs:
        if p.suffix.lower() != ".pdf":
            skipped.append(p)
            continue
        d = load(p)
        (docs if d else skipped).append(d or p)
    findings = validate(docs)
    if not name:
        ci = next((d for d in docs if d.kind == "CI" and d.f.get("invoice_no")), None)
        name = ci.f["invoice_no"].value if ci else (inputs[0].stem if inputs else "shipment")
    name = re.sub(r"[^\w\-. ]", "_", name).strip() or "shipment"
    res = Result(name, docs, skipped, findings, unrecognised(docs, skipped), workdir=workdir, fingerprint=fp)

    out = (out_root or report_root()) / f"{name}_{datetime.now():%Y%m%d-%H%M%S}"
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    if with_evidence:
        for i, f in enumerate(findings, 1):
            f.evidence = evidence.render(f, out / "evidence", i)
    res.out_dir, res.excel = out, out / "report.xlsx"
    res.marks = evidence.marks(findings)
    (out / "documents").mkdir(exist_ok=True)       # copies of the checked PDFs, for the preview and later look-up
    for d in docs:
        shutil.copy2(d.path, out / "documents" / d.name)
        res.doc_files[d.name] = out / "documents" / d.name
    report.excel(res, res.excel)
    res.markdown = report.markdown(res)
    (out / "report.md").write_text(res.markdown, encoding="utf-8")
    if not keep_workdir:
        shutil.rmtree(workdir, ignore_errors=True)
    return res
