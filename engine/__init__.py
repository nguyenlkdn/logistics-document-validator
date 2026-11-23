"""LDV engine: check one shipment's document set and write a bilingual report (documents are never modified)."""
import hashlib
import os
import re
import shutil
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import _dllpath  # noqa: F401  (must come before anything that imports pymupdf)
from . import evidence, master, report, session
from .extract import load, load_excel
from .rules import CONFIG, unrecognised, validate, validate_checks


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
    marks: dict = field(default_factory=dict)      # document name -> finding locations (preview highlights)
    fingerprint: str = ""          # hash of the PDF contents: same files -> same fingerprint (history)
    kinds: dict = field(default_factory=dict)      # file name -> document type set by the user
    checks: list = field(default_factory=list)     # one CheckResult per check and group (engine/checks.py)
    verdict: dict = field(default_factory=dict)    # automated package verdict (RED / AMBER / GREEN)
    diagnostics: list = field(default_factory=list)   # tracebacks of rules that failed (written to diagnostics.log)


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
    files = sorted(x for x in workdir.rglob("*") if x.is_file() and not junk(x))
    same = Counter(x.name.lower() for x in files)  # 'DRAFT.pdf' in several folders: 'DRAFT (folder).pdf', because
    out, used = [], set()                          # documents are known by their file name in the whole review
    for x in files:
        if same[x.name.lower()] > 1:
            n, new = 1, x.with_name(f"{x.stem} ({x.parent.name}){x.suffix}")
            while new.name.lower() in used or new.exists():
                n += 1
                new = x.with_name(f"{x.stem} ({x.parent.name} {n}){x.suffix}")
            x = x.rename(new)
        used.add(x.name.lower())
        out.append(x)
    return sorted(out)


def check(inputs: list[Path], name: str | None = None, out_root: Path | None = None,
          with_evidence: bool = True, keep_workdir: bool = False, kinds: dict | None = None) -> Result:
    """kinds: {file name: CI|SC|BL|CO} for documents whose type the user corrected (default: automatic)."""
    kinds = {k: v for k, v in (kinds or {}).items() if v}
    master.refresh()                               # the HS master Excel may have been edited since last time
    workdir = Path(tempfile.mkdtemp(prefix="ldv_"))
    pdfs = collect(inputs, workdir)
    fp = hashlib.sha1("".join(sorted(hashlib.sha1(p.read_bytes()).hexdigest() for p in pdfs
                                     if p.suffix.lower() in (".pdf", ".xlsx", ".xlsm"))).encode()).hexdigest()
    if kinds:                                      # a corrected document type gives a different result: new revision
        fp = hashlib.sha1((fp + repr(sorted(kinds.items()))).encode()).hexdigest()
    docs, skipped, xl_errors = [], [], []
    for p in pdfs:
        if p.suffix.lower() in (".xlsx", ".xlsm"):     # invoice / packing list / contract sheets of a workbook
            try:
                xs = load_excel(p, p.parent)
            except Exception:                          # not a workbook we can read: listed as skipped
                import traceback
                xl_errors.append(f"{p.name}\n{traceback.format_exc()}")
                xs = []
            (docs.extend(xs) if xs else skipped.append(p))
            continue
        if p.suffix.lower() != ".pdf":
            skipped.append(p)
            continue
        d = load(p, kinds.get(p.name))
        (docs if d else skipped).append(d or p)
    from .checks import verdict
    findings, checks = validate_checks(docs)
    if not name:
        ci = next((d for d in docs if d.kind == "CI" and d.f.get("invoice_no")), None)
        name = ci.f["invoice_no"].value if ci else (inputs[0].stem if inputs else "shipment")
    name = re.sub(r"[^\w\-. ]", "_", name).strip() or "shipment"
    res = Result(name, docs, skipped, findings, unrecognised(docs, skipped), workdir=workdir, fingerprint=fp,
                 kinds={k: v for k, v in kinds.items() if any(d.name == k for d in docs)}, checks=checks)
    res.diagnostics = xl_errors + list(getattr(checks, "diagnostics", []))
    res.verdict = verdict([c.to_dict() for c in checks],
                          [dict(no=i, severity=f.severity, suspect=getattr(f, "suspect", ""))
                           for i, f in enumerate(findings, 1)])

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
    if res.diagnostics:                            # rule errors: tracebacks for the developer, not in the report
        (out / "diagnostics.log").write_text("\n\n".join(res.diagnostics), encoding="utf-8")
    report.excel(res, res.excel)
    res.markdown = report.markdown(res)
    (out / "report.md").write_text(res.markdown, encoding="utf-8")
    session.save(res)                              # lets the UI reopen this review without checking again
    if not keep_workdir:
        shutil.rmtree(workdir, ignore_errors=True)
    return res
