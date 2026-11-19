"""Stored review session: everything the UI needs to show a finished check again, without re-running it.

check() writes review.json into the report folder next to report.xlsx, documents/ and evidence/.
Opening an old review reads this file (load) instead of analysing the PDFs again. Folders written by
LDV <= 1.3 have no review.json; from_history() rebuilds what it can from the history database.

The file only holds results (findings, check records, verdict, document inventory, extracted values, highlight
boxes). Schema 2 only adds keys, so LDV <= 2.2 still opens it (it ignores what it does not know).
The reviewer's decisions (status, note) stay in history.db, so automated results and human decisions
are never mixed and the analysis result is never overwritten.
"""
import json
from datetime import datetime
from pathlib import Path

SCHEMA = 2          # 2 (LDV 2.3): + "checks" (one record per check and group) + "verdict"; findings + "check"
FILE = "review.json"


def _plain(v):
    from .report import plain
    return plain(v)


def _page(v):
    from .extract import Field
    return v.page + 1 if isinstance(v, Field) and v.end > v.start else None


def app_version() -> str:
    f = Path(__file__).resolve().parent.parent / "VERSION"
    return f.read_text(encoding="utf-8").strip() if f.exists() else "dev"


def _item(it: dict) -> dict:
    """A line item as plain values, with the page of the line ("_page", 1-based) for the comparison view."""
    out = {k: _plain(v) for k, v in it.items()}
    out["_page"] = next((_page(v) for v in it.values() if _page(v)), None)
    return out


def build(res) -> dict:
    """Serialise a Result (call after the report folder is complete)."""
    import pymupdf
    from .evidence import locations
    from .history import History
    out = Path(res.out_dir)
    rel = lambda p: str(Path(p).resolve().relative_to(out.resolve())).replace("\\", "/")
    docs = []
    for d in res.docs:
        copy = res.doc_files.get(d.name)
        try:
            with pymupdf.open(copy or d.path) as pdf:
                pages = pdf.page_count
        except Exception:
            pages = None
        docs.append(dict(
            name=d.name, kind=d.kind, kind_set_by_user=d.name in (res.kinds or {}), pages=pages, is_draft=d.is_draft,
            file=rel(copy) if copy else None,
            fields={k: dict(value=_plain(v), page=_page(v)) for k, v in d.f.items()},
            items=[_item(it) for it in d.items], pl_items=[_item(it) for it in d.pl_items]))
    findings, locs = [], locations(res.findings)
    for i, (f, sig) in enumerate(zip(res.findings, History.sigs(res.findings)), 1):
        findings.append(dict(
            no=i, sig=sig, key=f.key, severity=f.severity,
            doc=f.doc_names[0] if f.docs else "", doc_kind=f.docs[0].kind if f.docs else "",
            related=f.doc_names[1:], page=f.page, current=f.current, suggested=f.suggested,
            msg_en=f.text("en"), msg_vi=f.text("vi"), note_en=f.note("en"), note_vi=f.note("vi"),
            evidence=[rel(p) for p in f.evidence], locs=locs[i - 1], check=getattr(f, "check", "")))
    return dict(schema=SCHEMA, name=res.name, shipment=History.shipment_of(res),
                created=datetime.now().isoformat(timespec="seconds"), version=app_version(),
                fingerprint=res.fingerprint, docs=docs, findings=findings,
                skipped=[Path(p).name for p in res.skipped], unrecognised=res.unrecognised,
                checks=[c.to_dict() for c in res.checks], verdict=res.verdict,
                marks={k: [list(m) for m in v] for k, v in res.marks.items()},
                excel=rel(res.excel) if res.excel else None)


def save(res) -> Path:
    path = Path(res.out_dir) / FILE
    path.write_text(json.dumps(build(res), ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load(out_dir) -> dict | None:
    """The stored session of a report folder, with absolute paths resolved; None if there is none."""
    out = Path(out_dir)
    f = out / FILE
    if not f.exists():
        return None
    s = json.loads(f.read_text(encoding="utf-8"))
    return _resolve(s, out)


def _resolve(s: dict, out: Path) -> dict:
    s["out_dir"] = str(out)
    for d in s["docs"]:
        d["path"] = str(out / d["file"]) if d.get("file") else None
    for f in s["findings"]:
        f["evidence_paths"] = [str(out / p) for p in f.get("evidence", [])]
    s["excel_path"] = str(out / s["excel"]) if s.get("excel") else None
    return s


def from_history(check: dict, findings: list[dict]) -> dict:
    """Best-effort session for a check saved before review.json existed (no highlights, no extracted values)."""
    from .rules import CONFIG
    note = lambda k, l: CONFIG["messages"].get(k, {}).get(f"note_{l}", "")
    out = Path(check["out_dir"]) if check.get("out_dir") else None
    names = json.loads(check.get("files") or "[]")
    kinds = {f["doc"]: f["doc_kind"] for f in findings}
    docs = []
    for n in names:
        copy = out / "documents" / n if out else None
        docs.append(dict(name=n, kind=kinds.get(n, ""), pages=None, is_draft=None,
                         file=f"documents/{n}" if copy and copy.exists() else None, fields={}, items=[], pl_items=[]))
    evid = {}
    if out and (out / "evidence").exists():
        for p in sorted((out / "evidence").glob("*.png")):
            no = p.name.split("_", 1)[0]
            if no.isdigit():
                evid.setdefault(int(no), []).append(f"evidence/{p.name}")
    s = dict(schema=0, name=check.get("name") or check["shipment"], shipment=check["shipment"],
             created=check["ts"], version=check.get("version", ""), fingerprint=check.get("fingerprint", ""),
             docs=docs, skipped=[], unrecognised=[], marks={}, legacy=True,
             excel="report.xlsx" if out and (out / "report.xlsx").exists() else None,
             findings=[dict(no=f["no"], sig=f["sig"], key=f["key"], severity=f["severity"], doc=f["doc"],
                            doc_kind=f["doc_kind"], related=[], page=f["page"], current=f["current"] or "",
                            suggested=f["suggested"] or "", msg_en=f["msg_en"], msg_vi=f["msg_vi"],
                            note_en=note(f["key"], "en"), note_vi=note(f["key"], "vi"), evidence=evid.get(f["no"], [])) for f in findings])
    return _resolve(s, out) if out else s | dict(out_dir="", excel_path=None)
