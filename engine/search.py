"""Global search over the review history: shipments, document names, reference numbers read from the documents
(invoice, B/L, contract / PO, vessel), finding IDs and finding texts.

The index is built from history.db and each review's review.json (read only). Only the newest revision of each
shipment is indexed for findings and reference numbers, so a search does not return the same item once per revision.
"""
import json
import re
from pathlib import Path

REF_FIELDS = {  # field in review.json -> label
    "invoice_no": ("Invoice no.", "Số hóa đơn"), "bl_no": ("B/L no.", "Số vận đơn"),
    "sc_no": ("Contract no.", "Số hợp đồng"), "pos": ("PO", "PO"), "vessel": ("Vessel", "Tên tàu"),
}


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def build(hist) -> dict:
    """{reviews: [...], refs: [...], findings: [...]} — plain dicts, cheap to search."""
    checks = hist.checks(limit=5000)
    latest = {}
    for c in checks:                                         # newest first
        latest.setdefault(c["shipment"], c)
    reviews = [dict(check_id=c["id"], shipment=c["shipment"], revision=c["revision"], ts=c["ts"], name=c["name"] or "",
                    files=json.loads(c["files"] or "[]"), n_open=c["n_open"]) for c in checks]
    refs, docs = [], []
    for c in latest.values():
        f = Path(c["out_dir"] or "") / "review.json"
        if not f.exists():
            continue
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for d in s.get("docs", []):
            docs.append(dict(check_id=c["id"], shipment=c["shipment"], doc=d["name"], kind=d.get("kind", "")))
            for k, lab in REF_FIELDS.items():
                v = (d.get("fields", {}).get(k) or {}).get("value")
                if v:
                    refs.append(dict(check_id=c["id"], shipment=c["shipment"], doc=d["name"], label=lab, value=str(v),
                                     page=(d["fields"][k] or {}).get("page")))
    findings = [dict(check_id=f["check_id"], shipment=f["shipment"], revision=f["revision"], no=f["no"],
                     severity=f["severity"], doc=f["doc"], msg_en=f["msg_en"], msg_vi=f["msg_vi"],
                     current=f["current"] or "", suggested=f["suggested"] or "", status=f["status"],
                     fid=f"{f['shipment']}-R{f['revision']}-{f['no']:02d}") for f in hist.all_findings(latest_only=True)]
    return dict(reviews=reviews, refs=refs, docs=docs, findings=findings)


def query(index: dict, q: str, limit: int = 8) -> dict:
    """Matches per group, best first (exact / prefix matches before substring matches). All words must match."""
    words = [w for w in _norm(q).split(" ") if w]
    if not words:
        return dict(reviews=[], refs=[], docs=[], findings=[])

    def score(*fields) -> int | None:
        text = " ".join(_norm(x) for x in fields)
        if not all(w in text for w in words):
            return None
        first = _norm(fields[0])
        return 0 if first == _norm(q) else 1 if first.startswith(words[0]) else 2

    def pick(items, fields):
        hits = [(sc, i) for i, it in enumerate(items) if (sc := score(*fields(it))) is not None]
        return [items[i] for _, i in sorted(hits)[:limit]]

    return dict(
        reviews=pick(index["reviews"], lambda r: (r["shipment"], r["name"], " ".join(r["files"]))),
        refs=pick(index["refs"], lambda r: (r["value"], r["shipment"], r["doc"])),
        docs=pick(index["docs"], lambda r: (r["doc"], r["shipment"])),
        findings=pick(index["findings"], lambda r: (r["fid"], r["msg_en"], r["msg_vi"], r["current"], r["suggested"],
                                                    r["doc"])))
