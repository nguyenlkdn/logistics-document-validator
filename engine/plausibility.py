"""Plausibility gate (LDV 2.6, P5): values whose reading shows a detectable defect are marked SUSPECT.

A rule that uses a SUSPECT input does not report a confirmed document error: its finding is kept, with its severity,
and marked "LDV may have read this wrongly"; its check is REVIEW_REQUIRED (or NOT_RUN when nothing was found), so the
package is AMBER, never RED and never GREEN. Findings that use no SUSPECT input are not affected.
Approved rules (owner, 2026-11-19; design and evidence: docs/P5_DESIGN.md). Each is a yes/no test, no thresholds:

  S1  partial number   the text right next to a number continues the number: it was cut out of a larger one
  S2  incomplete lines the document has goods rows no reader consumed: every value worked out from its lines
  S3  label in a name  a party name starts with a role label (CONSIGNEE, SHIPPER …): the wrong line was read
"""
import re

SUSPECT = "SUSPECT"
# the name starts with a role label ('CONSIGNEE ACME CO., LTD.'); a company called 'ACME BUYER CO.' is not suspect
_ROLE = re.compile(r"^\s*(CONSIGNEE|SHIPPER|ACCOUNTEE|NOTIFY(?:\s+PARTY)?|SHIP\s+TO|EXPORTER|SELLER|BUYER)\b", re.I)
PARTY_FIELDS = ("shipper", "consignee", "exporter", "seller", "buyer", "pl_shipper", "pl_consignee")


def _fields(obj):
    if hasattr(obj, "raw") and hasattr(obj, "line") and hasattr(obj, "value"):     # a Field (any LDV version)
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _fields(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _fields(v)


def _cut(f) -> bool:
    """S1: the characters around the number's text in its line continue the number."""
    if not isinstance(f.value, (int, float)) or isinstance(f.value, bool) or f.end <= f.start:
        return False
    t = f.line.text
    before = t[f.start - 1] if f.start > 0 else " "
    after = t[f.end:f.end + 2]
    return bool(re.match(r"[\d.,]", before) and (before.isdigit() or (f.start > 1 and t[f.start - 2].isdigit()))) or \
        bool(re.match(r"\d|[.,]\d", after))


_LEGAL = re.compile(r"\b(CO|COMPANY|LTD|LIMITED|INC|CORP|CORPORATION|PTE|PCL|PLC|JSC|LLC)\b\.?", re.I)


def _label_then_name(name: str) -> bool:
    """S3: a role label followed by a company name ('CONSIGNEE ACME VIETNAM CO., LTD.'). A company whose own name is
    such a word ('BUYER CO., LTD.') is not suspect: after the word only the legal form is left."""
    m = _ROLE.match(name)
    if not m:
        return False
    rest = _LEGAL.sub(" ", name[m.end():])
    return bool(re.search(r"[A-Za-z]{2,}", rest))


def mark(d) -> list:
    """Mark the SUSPECT values of one document; returns [(rule, what)] for the record."""
    found = []
    for f in _fields([d.f, d.lists, d.items, d.pl_items]):
        if f.status == "READ" and _cut(f):
            f.status, f.why = SUSPECT, "S1"
            found.append(("S1", f.raw))
    for k in PARTY_FIELDS:
        f = d.f.get(k)
        if f is not None and f.status == "READ" and isinstance(f.value, str) and _label_then_name(f.value):
            f.status, f.why = SUSPECT, "S3"
            found.append(("S3", k))
    if d.lists.get("unparsed"):                 # S2: sums / counts over the lines are not over the printed lines
        d.suspect_lines = len(d.lists["unparsed"])
        found.append(("S2", d.suspect_lines))
    return found
