"""Check registry and runner (LDV 2.3, P1): every check of every rule leaves an execution record.

A *check* is one verification a rule makes (e.g. "B/L total cartons = packing-list cartons"). A rule function can hold
several checks. For every document group the runner records one CheckResult per applicable check:

    PASS             the inputs were read and compared, nothing wrong (MINOR / INFO findings may be attached)
    FAIL             an ERROR finding
    REVIEW_REQUIRED  a WARNING finding (and no ERROR)
    NOT_RUN          the check could not be made; `reason` says why (machine code + EN/VI text in config.json)
    NOT_APPLICABLE   positive evidence that the check does not apply (never just "a field was not read")

Rules keep their comparisons; their guard clauses go through a check context (`ck`), which records why a check stops:

    ck = begin("DEPARTURE_DATE", out)
    dep, sail = ck.need(co, "departure"), ck.need(ci, "sailing")
    if dep and sail:
        ck.compared()
        if dep.value != sail.value:
            ck.add(Finding(...))
    ck.end()

Guarantees (tests/run_checks.py):
  - a check without a record at the end of its group gets NOT_RUN(not_reported) (safety net, a test fails on it);
  - an exception in a rule gives NOT_RUN(internal_error) for its unfinished checks; the other rules still run;
  - PASS needs every input READ and at least one comparison made; an empty list never passes;
  - every input a check reads is declared in its CheckDef.needs.

Field status (FieldStatus) and check status (CheckStatus) are separate. Results are immutable once the check has run;
reviewer decisions stay in history.db and only the *effective* verdict (verdict(..., open_sig)) takes them into account.
"""
from __future__ import annotations

import contextvars
import logging
import re
import traceback
from dataclasses import dataclass, field

from .util import form_text

LOG = logging.getLogger("ldv.checks")


class FieldStatus:
    READ = "READ"
    UNREADABLE = "UNREADABLE"        # printed at its label, not understood ("21-NOV-2O26")
    ABSENT = "ABSENT"                # not printed on this layout at all (no label anywhere)
    NOT_FOUND = "NOT_FOUND"          # expected, not found
    SUSPECT = "SUSPECT"              # read, but the reading shows a defect (engine/plausibility.py, P5)


class CheckStatus:
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_RUN = "NOT_RUN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ALL = ("FAIL", "REVIEW_REQUIRED", "NOT_RUN", "NOT_APPLICABLE", "PASS")


class Applicability:
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "APPLICABILITY_UNKNOWN"


# reason code -> category (shown apart in the UI: a reading problem is not master data is not a package gap)
REASONS = {
    "document_missing": "package", "requirement_unknown": "package",
    "field_not_found": "reading", "field_unreadable": "reading", "field_absent_required": "reading",
    "items_not_read": "reading", "items_not_comparable": "reading", "too_few_values": "reading",
    "master_data_missing": "master_data", "blocked_by": "dependency", "suspect_reading": "reading",
    "scope_unsupported": "system", "internal_error": "system", "not_reported": "system",
}
_FIELD_REASON = {FieldStatus.UNREADABLE: "field_unreadable", FieldStatus.ABSENT: "field_absent_required",
                 FieldStatus.NOT_FOUND: "field_not_found"}
_SEV_STATUS = {"ERROR": CheckStatus.FAIL, "WARNING": CheckStatus.REVIEW_REQUIRED}      # MINOR / INFO: PASS


# ----------------------------------------------------------------------------------------------------- field status
@dataclass(frozen=True)
class Missing:
    """A field that is not there: has no .value, so it can never be compared (missing is not zero)."""
    name: str
    status: str
    doc: str = ""

    def __bool__(self):
        return False


def _absent(doc, name: str) -> bool:
    a = doc.f.get("absent")
    return bool(a and isinstance(a.value, str) and name in [x.strip() for x in a.value.split(",")])


def field_state(doc, name: str):
    """The Field of doc.f[name], or Missing(status) when it is not usable. UNREADABLE is set by the reader on the
    Field (LDV 2.4); ABSENT comes from the reader's 'absent' list; a missing key or an empty value is NOT_FOUND.
    (Fields made without F() and value None + printed text are still UNREADABLE.)"""
    f = doc.f.get(name) if doc is not None else None
    if f is not None and getattr(f, "status", "READ") not in (None, FieldStatus.READ, FieldStatus.SUSPECT):
        return Missing(name, f.status, doc.name)            # set by the reader (UNREADABLE); SUSPECT stays a value
    if f is not None and hasattr(f, "value"):
        v = f.value
        if v is not None and v != "" and v != []:
            return f
        if v is None and str(getattr(f, "raw", "") or "").strip():
            return Missing(name, FieldStatus.UNREADABLE, doc.name)
    if doc is not None and _absent(doc, name):
        return Missing(name, FieldStatus.ABSENT, doc.name)
    return Missing(name, FieldStatus.NOT_FOUND, doc.name if doc is not None else "")


def status_of(doc, name: str) -> str:
    f = field_state(doc, name)
    return f.status if isinstance(f, Missing) else (getattr(f, "status", None) or FieldStatus.READ)


def has_text(doc, pattern: str, flags=re.I) -> bool:
    """Layout trace: the document's text contains pattern (positive evidence that a section exists)."""
    if doc is None:
        return False
    run = _RUN.get()
    key = (id(doc), pattern, flags)
    if run is not None and key in run.traces:
        return run.traces[key]
    rx = re.compile(pattern, flags)
    hit = any(rx.search(l.text) for l in doc.lines)
    if run is not None:
        run.traces[key] = hit
    return hit


# ----------------------------------------------------------------------------------------------------- registry
@dataclass(frozen=True)
class CheckDef:
    id: str
    rule: str                    # function / block that runs it
    scope: str                   # invoice | document | shipment | invoice* (invoice with one invoice, shipment with several)
    kinds: tuple                 # documents it needs; for scope document the first is the document it runs on ("*" = any)
    needs: tuple                 # declared inputs ("BL.ctn", "CI.Σctn", "CI.items", "CO.items[inv_date]", "BL.lists.cntr" …)
    keys: tuple                  # finding keys it may emit
    kind: str = "compare"        # compare | scan
    multi: str = ""              # behaviour with several invoices: "" (per invoice group) | "replaced" | "unsupported"


def _d(id, rule, scope, kinds, needs, keys, kind="compare", multi=""):
    return CheckDef(id, rule, scope, tuple(kinds.split()), tuple(needs.split()), tuple(keys.split()), kind, multi)


_PLH = ("consignee", "shipper", "vessel", "pol", "pod", "sailing", "payment", "origin", "goods_full", "pos",
        "containers", "incoterm", "freight")

REGISTRY_ROWS = [
    # --- rules.py
    _d("LINE_MATH.ci", "r_line_math", "document", "CI", "CI.items", "LINE_AMOUNT"),
    _d("LINE_MATH.sc", "r_line_math", "document", "SC", "SC.items", "LINE_AMOUNT"),
    _d("TOTAL_AMOUNT.ci", "r_line_math", "document", "CI", "CI.total_amount CI.items", "TOTAL_AMOUNT"),
    _d("TOTAL_AMOUNT.sc", "r_line_math", "document", "SC", "SC.total_amount SC.items", "TOTAL_AMOUNT"),
    _d("TOTAL_QTY.ci", "r_line_math", "document", "CI", "CI.total_qty CI.items", "TOTAL_QTY"),
    _d("TOTAL_QTY.sc", "r_line_math", "document", "SC", "SC.total_qty SC.items", "TOTAL_QTY"),
    *[_d(f"PL_TOTAL.{k}", "r_pl_sums", "document", "CI", f"CI.pl_total_{k} CI.pl_items", "PL_TOTAL")
      for k in ("qty", "nw", "gw", "cbm", "ctn")],
    _d("CI_PL_QTY", "r_pl_sums", "document", "CI", "CI.items CI.pl_items", "CI_PL_QTY"),
    *[_d(f"BL_VS_PL.{k}", "r_bl_vs_pl", "invoice*", "BL CI", f"BL.{k} CI.Σ{k}", "BL_VS_PL") for k in ("gw", "cbm", "ctn")],
    _d("CONTAINERS", "r_bl_vs_pl", "invoice", "BL CI", "BL.containers CI.containers", "CONTAINERS", multi="unsupported"),
    _d("INVOICE_REF", "r_bl_vs_pl", "invoice", "BL CI", "BL.invoice_no CI.invoice_no", "INVOICE_REF", multi="replaced"),
    _d("INCOTERM_PORT", "r_incoterm", "document", "*", "BL.pol CI.pol *.lists.fob", "INCOTERM"),
    _d("SC_PO_COVERAGE", "r_po_coverage", "invoice", "SC CI", "CI.pos SC.pos", "SC_PO_TYPO SC_PO_MISSING SC_PO_EXTRA"),
    _d("SC_DUPLICATE_PO_NUMBER", "r_sc_po_numbers", "document", "SC", "SC.sc_no SC.lists.po_refs", "SC_DUPLICATE_PO_NUMBER"),
    _d("SC_PO_COUNT_EXCEEDED", "r_sc_po_numbers", "document", "SC", "SC.sc_no SC.lists.po_refs", "SC_PO_COUNT_EXCEEDED"),
    _d("SC_VS_CI", "r_sc_vs_ci", "invoice", "SC CI", "CI.items SC.items", "SC_VS_CI"),
    _d("SC_CHARGES", "r_sc_vs_ci", "invoice", "SC CI", "SC.lists.charges CI.lists.charges", "SC_CHARGES SC_CHARGES_TWICE"),
    _d("SC_NUMBERING", "r_sc_vs_ci", "document", "SC", "SC.items", "SC_NUMBERING"),
    _d("DEPARTURE_DATE", "r_dates", "invoice", "CO CI", "CO.departure CI.sailing", "DEPARTURE_DATE"),
    _d("CO_INVOICE_DATE", "r_dates", "invoice", "CO CI", "CO.items CO.items[inv_date] CI.invoice_date", "CO_INVOICE_DATE"),
    _d("SHIPMENT_DATE", "r_dates", "invoice", "SC CI", "SC.shipment_by CI.sailing", "SHIPMENT_LATE SHIPMENT_SLACK SHIPMENT_BLANK"),
    _d("SC_DATE", "r_dates", "invoice", "SC CI", "SC.sc_date CI.invoice_date", "SC_DATE"),
    _d("VESSEL.ci", "r_vessel", "invoice", "BL CI", "BL.vessel CI.vessel", "VESSEL"),
    _d("VESSEL.co", "r_vessel", "invoice", "BL CO", "BL.vessel CO.vessel", "VESSEL"),
    _d("CO_QTY", "r_co", "invoice", "CO CI", "CO.items CI.items", "CO_QTY"),
    _d("CO_INVOICE_NO", "r_co", "invoice", "CO CI", "CO.items CI.items CI.invoice_no", "CO_INVOICE_NO"),
    _d("CO_ITEMS", "r_co", "invoice", "CO CI", "CO.items CI.items", "CO_ITEMS"),
    _d("CO_TOTAL.value", "r_co", "invoice", "CO CI", "CO.total_value CI.Σamount", "CO_TOTAL"),
    _d("CO_TOTAL.qty", "r_co", "invoice", "CO CI", "CO.total_qty CI.Σqty", "CO_TOTAL"),
    _d("HS_MASTER", "r_master_models", "invoice", "CI", "master CI.items CI.items[model]", "HS_MASTER_MISSING"),
    _d("MASTER_NAME", "r_master_goods", "invoice", "CI", "master CI.items CI.items[model]", "MASTER_NAME MASTER_NAME_EXTRA MASTER_NAME_MISSING"),
    _d("MASTER_UNIT", "r_master_goods", "invoice", "CI", "master CI.items CI.items[model]", "MASTER_UNIT"),
    _d("CO_HS", "r_hs", "invoice", "CO", "CO.items master BL.hs", "CO_HS_MASTER BL_HS_CODE HS_CODE HS_NOT_IN_MASTER"),
    _d("BL_HS", "r_hs", "invoice", "BL CI", "BL.hs master CI.items[model]", "BL_HS_MASTER HS_NOT_IN_MASTER"),
    _d("CNTR_WORDS", "r_containers", "document", "BL", "BL.cntr_words BL.cntr_words_n BL.lists.cntr BL.containers", "CNTR_WORDS"),
    _d("CNTR_COUNT", "r_containers", "document", "BL", "BL.containers BL.lists.cntr", "CNTR_COUNT"),
    _d("CNTR_TYPE", "r_containers", "invoice", "BL", "BL.lists.cntr CI.lists.cntr_types BL.cntr_summary", "CNTR_TYPE CNTR_TYPE_CBM"),
    _d("CNTR_SUMMARY", "r_containers", "invoice", "BL CI", "BL.cntr_summary CI.lists.cntr_types", "CNTR_SUMMARY"),
    _d("CNTR_CAPACITY", "r_containers", "document", "BL", "BL.lists.cntr BL.lists.cntr_load", "CNTR_CAPACITY"),
    _d("CNTR_ATTACH_SUM", "r_containers", "document", "BL", "BL.lists.cntr_load BL.ctn BL.gw BL.cbm", "CNTR_ATTACH_SUM"),
    _d("CNTR_VS_PL", "r_cntr_vs_pl", "shipment", "BL CI", "BL.lists.cntr BL.lists.cntr_load CI.pl_items",
       "CNTR_NO CNTR_NO_MISSING CNTR_LOAD CNTR_LOAD_UNREAD"),
    _d("BL_MARKS_MODEL", "r_bl_cargo", "invoice", "BL CI", "BL.lists.marks_models CI.items[model]", "BL_MARKS_MODEL"),
    _d("BL_CARGO_QTY", "r_bl_cargo", "invoice*", "BL CI", "BL.bl_qty CI.Σqty", "BL_QTY BL_DESC_QTY"),
    _d("BL_CARGO_CTN", "r_bl_cargo", "invoice*", "BL CI", "BL.bl_qty_ctn CI.Σctn", "BL_DESC_CTN BL_DESC_QTY"),
    _d("BL_UNIT", "r_bl_cargo", "invoice", "BL CI", "BL.bl_unit CI.unit", "BL_UNIT"),
    _d("BL_GOODS_DESC", "r_bl_cargo", "invoice", "BL CI", "BL.goods BL.cargo_blocks[goods] CI.goods", "BL_GOODS_DESC"),
    _d("BL_DESTINATION", "r_bl_cargo", "document", "BL CI", "BL.final_dest BL.delivery BL.pod CI.pod", "BL_DESTINATION"),
    _d("CO_MARKS_MODEL", "r_co_marks", "invoice", "CO CI", "CO.lists.marks_models CI.items[model]", "CO_MARKS_MODEL"),
    _d("PL_RANGES", "r_pl_ranges", "document", "CI", "CI.pl_items CI.pl_items[rng]", "PL_RANGE_ORDER PL_RANGE_START PL_RANGE_GAP "
                                                                          "PL_RANGE_OVERLAP PL_RANGE_COUNT"),
    _d("PL_RANGE_TOTAL", "r_pl_ranges", "document", "CI", "CI.pl_items[rng] CI.pl_total_ctn", "PL_RANGE_TOTAL"),
    _d("CO_PKG", "r_co_packages", "invoice", "CO CI", "CO.items CI.pl_items", "CO_PKG_COUNT CO_SET_PER_CTN PL_SET_PER_CTN"),
    _d("CO_GOODS_DESC", "r_co_packages", "invoice", "CO CI", "CO.items CO.items[goods] CI.pl_items CI.pl_items[desc] CI.items[desc] CI.pl_goods_full CI.goods_full",
       "CO_GOODS_DESC"),
    _d("CO_TOTAL.ctn", "r_co_packages", "invoice", "CO CI", "CO.total_ctn CI.Σctn", "CO_TOTAL"),
    _d("PORT_NAME", "r_pod", "document", "*", "*.lists.pod", "PORT_NAME", kind="scan"),
    _d("WORDS_VS_FIGURES", "r_words", "document", "*", "*.amount_words *.total_amount", "WORDS_VS_FIGURES", kind="scan"),
    _d("TEXT_FIXES", "r_text_fixes", "document", "*", "", "", kind="scan"),          # keys: config text_fixes ids
    _d("WORD_WRAP", "r_broken_wrap", "document", "BL", "", "WORD_WRAP", kind="scan"),
    _d("SC_DOCS", "r_documents", "document", "SC", "SC.docs_required", "SC_DOCS_INSURANCE SC_DOCS_FORMD"),
    _d("DRAFT_STATUS", "r_draft_status", "document", "*", "", "ISSUED_DOC", kind="scan"),
    _d("DOC_PAIRING", "_validate_multi", "shipment", "", "", "DOC_UNPAIRED"),
    _d("BL_CARGO_BLOCK", "r_bl_blocks", "shipment", "BL CI", "BL.cargo_blocks BL.cargo_blocks[qty] BL.cargo_blocks[ctn] "
                                                              "CI.Σqty CI.Σctn", "BL_BLOCK"),
    _d("BL_INVOICE_REFS", "_bl_invoices", "shipment", "BL CI", "BL.lists.invoice_nos CI.invoice_no",
       "BL_INVOICE_EXTRA BL_INVOICE_MISSING"),
    # --- rules_net.py
    _d("CI_COVER_TOTAL", "r_cover_totals", "document", "CI", "CI.lists.ci_ttls CI.Σqty CI.Σamount CI.Σctn", "CI_COVER_TOTAL"),
    _d("PL_COVER_TOTAL", "r_cover_totals", "document", "CI", "CI.lists.pl_ttls CI.Σpl_qty CI.Σctn CI.Σnw CI.Σgw CI.Σcbm",
       "PL_COVER_TOTAL"),
    _d("PL_GW_NW", "r_gw_nw", "document", "CI", "CI.pl_items CI.pl_total_nw CI.pl_total_gw", "PL_GW_NW"),
    _d("ETA_DATE", "r_eta", "document", "CI", "CI.eta CI.sailing", "ETA_DATE"),
    _d("DOC_HEADER", "r_headers", "document", "CI", "CI.lists.headers", "DOC_HEADER"),
    _d("CI_PO_LIST", "r_cover_pos", "document", "CI", "CI.lists.cover_pos CI.items[po]", "CI_PO_LIST"),
    _d("CO_SUM", "r_co_self", "document", "CO", "CO.items CO.total_qty CO.total_ctn", "CO_SUM"),
    _d("CO_NUMBERING", "r_co_self", "document", "CO", "CO.items", "CO_NUMBERING"),
    _d("CO_PAGES", "r_co_self", "document", "CO", "CO.lists.pages", "CO_PAGES"),
    _d("CI_PL_CTN", "r_ci_pl_ctn", "document", "CI", "CI.lists.ci_ttls CI.Σctn", "CI_PL_CTN"),
    _d("LINES", "r_lines", "document", "CI", "CI.items CI.pl_items", "LINE_COUNT PL_LINE CI_LINE_DESC"),
    _d("CO_MODEL", "r_co_model", "invoice", "CO CI", "CO.items CI.items", "CO_MODEL"),
    _d("CO_ITEM_VALUE", "r_co_values", "invoice", "CO CI", "CO.items[fob] CI.items[amount]", "CO_ITEM_VALUE"),
    _d("CO_CRITERION", "r_co_values", "document", "CO", "CO.items[criterion]", "CO_CRITERION"),
    _d("MARKS", "r_marks", "invoice", "CI", "CI.items CI.items[model] CI.lists.marks_models CI.lists.pl_marks_models "
                                             "BL.lists.marks_models CO.lists.marks_models", "CI_MARKS_MODEL PL_MARKS_MODEL MARKS_MISSING MARKS_NONE"),
    _d("ORIGIN", "r_origin", "invoice", "", "*.origin CO.lists.origin", "ORIGIN"),
    _d("CO_IMPORT_COUNTRY", "r_import_country", "invoice", "CO BL", "BL.dest_country CO.lists.import_country", "CO_IMPORT_COUNTRY"),
    _d("PARTY.consignee", "r_parties", "invoice", "", "CI.consignee SC.buyer CO.consignee BL.consignee", "PARTY_NAME"),
    _d("PARTY.shipper", "r_parties", "invoice", "", "SC.seller CO.exporter CO.third_party BL.shipper", "PARTY_NAME"),
    _d("CURRENCY", "r_currency", "invoice", "", "*.lists.currency", "CURRENCY"),
    _d("PAYMENT_TERMS", "r_payment", "invoice", "SC CI", "CI.payment SC.payment", "PAYMENT_TERMS"),
    _d("SC_GOODS_DESC", "r_sc_goods", "invoice", "SC CI", "CI.goods_full CI.goods SC.goods_full", "SC_GOODS_DESC"),
    _d("FREIGHT_TERM", "r_freight", "invoice", "CI", "CI.incoterm CI.freight CI.pl_freight BL.freight", "FREIGHT_TERM"),
    *[_d(f"PL_HEADER.{k}", "r_pl_header", "document", "CI", f"CI.{k} CI.pl_{k}", "PL_HEADER") for k in _PLH],
    _d("DATE_FAR", "r_date_far", "document", "*", "CI.invoice_date", "DATE_FAR", kind="scan"),
    _d("TEXT_TYPO", "r_text_typo", "document", "*", "", "TEXT_TYPO", kind="scan"),
    _d("VALUE_UNREADABLE", "r_unreadable", "document", "*", "", "VALUE_UNREADABLE", kind="scan"),
]
REGISTRY = {d.id: d for d in REGISTRY_ROWS}
assert len(REGISTRY) == len(REGISTRY_ROWS), "duplicate check id"


def core_ids() -> set:
    from .rules import CONFIG
    return set(CONFIG.get("core_checks", []))


# ----------------------------------------------------------------------------------------------------- results
@dataclass
class CheckResult:
    check_id: str
    group_id: str                 # stable internal id: "inv1", "inv2" … (order of the invoices), "shipment"
    group_type: str               # invoice | shipment
    group_label: str              # what the user sees (invoice no. or file name); not unique
    doc: str                      # the document a document-scope check ran on ("" otherwise)
    input_documents: list
    status: str
    reason: str | None = None
    detail: dict = field(default_factory=dict)
    inputs: list = field(default_factory=list)     # [{doc, kind, name, status}] the inputs the check read
    finding_indexes: list = field(default_factory=list)
    core: bool = False

    @property
    def category(self):
        return REASONS.get(self.reason) if self.reason else None

    def to_dict(self):
        return dict(id=self.check_id, group=self.group_id, group_type=self.group_type, group_label=self.group_label,
                    doc=self.doc, documents=list(self.input_documents), status=self.status, reason=self.reason,
                    category=self.category, detail=self.detail, inputs=self.inputs, findings=list(self.finding_indexes),
                    core=self.core)


@dataclass
class Group:
    id: str
    type: str
    label: str
    docs: list
    multi: bool = False           # the package has several invoices


_RUN: contextvars.ContextVar = contextvars.ContextVar("ldv_run", default=None)


class Run:
    """The records of one validate() call."""

    def __init__(self, docs: list):
        self.docs = docs
        self.results: list[CheckResult] = []
        self.group: Group | None = None
        self.rule: str = ""
        self.open: list[Ck] = []
        self.done: set = set()                    # (check id, group id, doc)
        self.done_ids: set = set()                # (check id, group id)
        self.diagnostics: list[str] = []
        self.part = 0                             # first record of the shipment being checked (several B/Ls)
        self.traces: dict = {}                    # has_text() results of this run
        self._names: list = []                    # document names of the current group
        self.core = core_ids()
        self._token = None

    def __enter__(self):
        self._token = _RUN.set(self)
        return self

    def __exit__(self, *exc):
        _RUN.reset(self._token)
        return False

    # -- groups
    def set_group(self, g: Group):
        self.group = g
        self._names = [d.name for d in g.docs]
        self._applicability(g)

    def _record(self, cid, status, reason=None, detail=None, doc="", inputs=None, fids=None):
        g = self.group
        key = (cid, g.id, doc)
        if key in self.done:
            return None
        self.done.add(key)
        self.done_ids.add(key[:2])
        r = CheckResult(cid, g.id, g.type, g.label, doc, self._names, status, reason, detail or {},
                        inputs or [], [], cid in self.core)
        r._fids = list(fids or [])
        self.results.append(r)
        return r

    def applies_here(self, d: CheckDef) -> bool:
        g = self.group
        if d.scope == "shipment":
            return g.type == "shipment"
        if d.scope == "invoice*":
            return g.type == ("shipment" if g.multi else "invoice")
        return g.type == "invoice"

    def _applicability(self, g: Group):
        """Before the rules run: a check whose documents are not in the group gets its record now, from what the
        package says about them (never NOT_APPLICABLE just because something was not read)."""
        for d in REGISTRY_ROWS:
            if not self.applies_here(d):
                continue
            if g.multi and g.type == "invoice" and d.multi:
                if d.multi == "replaced":
                    self._record(d.id, CheckStatus.NOT_APPLICABLE,
                                 detail=dict(evidence="several_invoices", by="BL_INVOICE_REFS",
                                             invoices=sum(x.kind == "CI" for x in self.docs)))
                else:
                    self._record(d.id, CheckStatus.NOT_RUN, "scope_unsupported",
                                 dict(invoices=sum(x.kind == "CI" for x in self.docs)))
                continue
            for k in [k for k in d.kinds if k != "*"]:
                if any(x.kind == k for x in g.docs):
                    continue
                app, reason, detail = requirement(k, g, self.docs)
                if app == Applicability.NOT_APPLICABLE:
                    self._record(d.id, CheckStatus.NOT_APPLICABLE, detail=detail)
                else:
                    self._record(d.id, CheckStatus.NOT_RUN, reason, detail)
                break

    def close_group(self):
        """Safety net: an applicable check with no record for this group -> NOT_RUN(not_reported)."""
        g = self.group
        for ck in list(self.open):
            ck.end()
        for d in REGISTRY_ROWS:
            if not self.applies_here(d):
                continue
            if d.scope == "document":
                docs = [x for x in g.docs if d.kinds[0] == "*" or x.kind == d.kinds[0]]
                for x in docs:
                    if (d.id, g.id, x.name) not in self.done and (d.id, g.id, "") not in self.done:
                        self._record(d.id, CheckStatus.NOT_RUN, "not_reported", dict(rule=d.rule), doc=x.name)
            elif (d.id, g.id) not in self.done_ids:
                self._record(d.id, CheckStatus.NOT_RUN, "not_reported", dict(rule=d.rule))

    # -- rule calls with exception isolation
    def call(self, fn, *args, **kw):
        self.rule = fn.__name__
        try:
            return fn(*args, **kw)
        except Exception as e:                        # noqa: BLE001 — isolate one rule; BaseException propagates
            self.internal_error(fn.__name__, e)
        finally:
            self.rule = ""

    def internal_error(self, rule: str, e: Exception):
        tb = traceback.format_exc()
        LOG.error("rule %s failed in group %s:\n%s", rule, self.group.id if self.group else "-", tb)
        self.diagnostics.append(f"rule {rule} (group {self.group.id if self.group else '-'}):\n{tb}")
        detail = dict(rule=rule, error=type(e).__name__)          # no message text: it can quote document content
        for ck in [c for c in self.open if c.defn.rule == rule]:
            ck.error(detail)
        for d in REGISTRY_ROWS:                      # checks of this rule that had not started yet
            if d.rule != rule or not self.applies_here(d):
                continue
            g = self.group
            if d.scope == "document":
                for x in [x for x in g.docs if d.kinds[0] == "*" or x.kind == d.kinds[0]]:
                    if (d.id, g.id, x.name) not in self.done:
                        self._record(d.id, CheckStatus.NOT_RUN, "internal_error", dict(detail), doc=x.name)
            elif (d.id, g.id) not in self.done_ids:
                self._record(d.id, CheckStatus.NOT_RUN, "internal_error", dict(detail))

    # -- after the rules
    def override(self, ids, status, reason, detail, group_id=None):
        """Change records of the current run before it is finished (e.g. the B/L covers an invoice that is not in
        the package: its totals cannot be compared, and the findings about them were withdrawn)."""
        for r in self.results[self.part:]:
            if r.check_id in ids and (group_id is None or r.group_id == group_id) and r.status != CheckStatus.NOT_APPLICABLE:
                r.status, r.reason, r.detail = status, reason, {**r.detail, **detail}
                r._fids = []

    def finish(self, findings: list):
        """Link each record to the final finding numbers (1-based, after sorting / de-duplication)."""
        from .rules import _sig
        pos = {id(f): i for i, f in enumerate(findings, 1)}
        by_sig = {}
        for i, f in enumerate(findings, 1):
            by_sig.setdefault(_sig(f), i)
        for r in self.results:
            idx = []
            for f in r._fids:
                i = pos.get(id(f)) or by_sig.get(_sig(f))
                if i and i not in idx:
                    idx.append(i)
            r.finding_indexes = sorted(idx)
        out = CheckList(self.results)
        out.diagnostics = list(self.diagnostics)
        return out


class CheckList(list):
    """The check results of one run, plus the tracebacks of rules that failed (diagnostics)."""
    diagnostics: list = []


def current_run() -> Run | None:
    return _RUN.get()


_FOC = r"\bF\.?\s?O\.?\s?C\b\.?|NO COMMERCIAL VALUE|FREE OF CHARGE"


def requirement(kind: str, g: Group, docs: list):
    """Is a document of `kind` required for group g? -> (Applicability, NOT_RUN reason, detail). Only documents in
    the package decide; FOC or the goods type exempt nothing in P1."""
    if kind in ("CI", "BL"):
        return Applicability.APPLICABLE, "document_missing", dict(kind=kind)
    # owner rule 2026-11-19: an invoice marked F.O.C / NO COMMERCIAL VALUE needs no contract and no Form D
    ci = next((d for d in g.docs if d.kind == "CI"), None)
    if kind in ("SC", "CO") and ci is not None and has_text(ci, _FOC, re.I):
        return Applicability.NOT_APPLICABLE, None, dict(kind=kind, evidence="foc_invoice", doc=ci.name)
    if kind == "SC":                                 # no document of the package says when a contract is required
        return Applicability.UNKNOWN, "requirement_unknown", dict(kind=kind, inv=g.label)
    if kind == "CO":
        scs = [d for d in g.docs if d.kind == "SC"]
        reqs = [d.f.get("docs_required") for d in scs]
        texts = [str(r.value).upper() for r in reqs if r is not None and str(r.value).strip()]
        if any(re.search(r"CERTIFICATE OF ORIGIN|FORM D", t) for t in texts):
            return Applicability.APPLICABLE, "document_missing", dict(kind=kind, evidence="sc_requires")
        inv_no = next((d.f["invoice_no"].value for d in g.docs if d.kind == "CI" and d.f.get("invoice_no")), None)
        for co in (d for d in docs if d.kind == "CO"):
            if inv_no and any(e["no"].value == inv_no for e in co.lists.get("invoices", [])):
                return Applicability.APPLICABLE, "document_missing", dict(kind=kind, evidence="co_names_invoice")
        if texts and len(texts) == len(scs):          # every contract lists its documents, none asks for a Form D
            return Applicability.NOT_APPLICABLE, None, dict(kind=kind, evidence="sc_docs_without_formd")
        return Applicability.UNKNOWN, "requirement_unknown", dict(kind=kind, inv=g.label)
    return Applicability.UNKNOWN, "requirement_unknown", dict(kind=kind)


# ----------------------------------------------------------------------------------------------------- check context
class Ck:
    """One execution of one check in the current group (and document, for document-scope checks)."""

    def __init__(self, cid: str, out: list | None, doc=None):
        self.defn = REGISTRY[cid]
        self.out = out
        self.doc = doc
        self.run = current_run()
        self.inputs: list = []
        self.missing: list = []
        self.suspect: list = []                # inputs read with a detectable defect (P5)
        self.fids: list = []
        self.sevs: list = []
        self.n_compared = 0
        self.state = None                      # NOT_APPLICABLE / NOT_RUN set explicitly
        self.reason = None
        self.detail: dict = {}
        self.ended = False
        self.off = False
        if self.run is not None and self.run.group is not None:
            g = self.run.group
            dn = doc.name if doc is not None else ""
            if (not self.run.applies_here(self.defn) or (cid, g.id, dn) in self.run.done
                    or (cid, g.id, "") in self.run.done):
                self.off = True                # resolved before the rules ran (documents missing) or out of scope
            else:
                self.run.open.append(self)

    # -- inputs
    def _input(self, doc, name, status, why=""):
        if status == FieldStatus.READ and doc is not None:      # P5: a value read with a detectable defect
            f = doc.f.get(name) if hasattr(doc, "f") else None
            if getattr(f, "status", None) == FieldStatus.SUSPECT:
                status, why = FieldStatus.SUSPECT, getattr(f, "why", "") or why
            elif getattr(doc, "suspect_lines", 0) and (name in ("items", "pl_items") or name.startswith("Σ")):
                status, why = FieldStatus.SUSPECT, "S2"          # worked out from lines while some lines were not read
        e = dict(doc=doc.name if doc is not None else "", kind=doc.kind if doc is not None else "", name=name, status=status)
        if why:
            e["why"] = why
        self.inputs.append(e)
        if status == FieldStatus.SUSPECT:
            self.suspect.append(e)
        elif status != FieldStatus.READ:
            self.missing.append(e)

    def need(self, doc, name: str, absent_ok: bool = False, trace: str | None = None):
        """doc.f[name] when it was read, else None (the reason is recorded). absent_ok: a field the reader marked as
        not printed on this layout makes the check NOT_APPLICABLE. trace: a pattern; when the field was not found and
        the document text has no trace of it at all, the check is NOT_APPLICABLE (positive evidence), else NOT_RUN."""
        if doc is None:
            return None
        f = field_state(doc, name)
        st = f.status if isinstance(f, Missing) else FieldStatus.READ
        if st == FieldStatus.READ:
            self._input(doc, name, st)                      # SUSPECT values are detected there
            return f
        self._missing_or_na(doc, name, st, absent_ok, trace)
        return None

    def _missing_or_na(self, doc, name, st, absent_ok, trace):
        if (absent_ok and st == FieldStatus.ABSENT) or (
                trace is not None and st == FieldStatus.NOT_FOUND and not has_text(doc, trace, 0)):
            self.inputs.append(dict(doc=doc.name, kind=doc.kind, name=name, status=st))
            self.na(evidence="not_printed", field=name, doc=doc.name)
        else:
            self._input(doc, name, st)

    def need_total_val(self, ci, k: str, value):
        """Record the input of a true_total() value the rule computed itself (the rule keeps using its own value)."""
        src = {"qty": "total_qty", "amount": "total_amount", "pl_qty": "pl_total_qty"}.get(k, f"pl_total_{k}")
        return self.need_value(ci, f"Σ{k}", value, src)

    def need_value(self, doc, name: str, value, source: str | None = None):
        """A value worked out by the rule (true_total, a list entry …): missing -> status of its source field."""
        if doc is None:
            return value
        if value is None or (hasattr(value, "value") and value.value is None):
            st = status_of(doc, source) if source else FieldStatus.NOT_FOUND
            self._input(doc, name, st if st != FieldStatus.READ else FieldStatus.NOT_FOUND)
            return None
        self._input(doc, name, FieldStatus.READ)
        return value

    def need_total(self, ci, k: str):
        from .rules import true_total
        if ci is None:
            return None
        src = {"qty": "total_qty", "amount": "total_amount", "pl_qty": "pl_total_qty"}.get(k, f"pl_total_{k}")
        return self.need_value(ci, f"Σ{k}", true_total(ci, k), src)

    def need_items(self, doc, attr: str = "items"):
        if doc is None:
            return []
        rows = getattr(doc, attr)
        self._input(doc, attr, FieldStatus.READ if rows else FieldStatus.NOT_FOUND)
        if not rows:
            self.reason = self.reason or "items_not_read"
        return rows

    def need_list(self, doc, name: str, absent_ok: bool = False, trace: str | None = None):
        if doc is None:
            return []
        rows = doc.lists.get(name) or []
        if rows:
            self._input(doc, f"lists.{name}", FieldStatus.READ)
        else:
            st = FieldStatus.ABSENT if _absent(doc, name) else FieldStatus.NOT_FOUND
            self._missing_or_na(doc, f"lists.{name}", st, absent_ok, trace)
        return rows

    def need_item(self, doc, it: dict, key: str):
        """A field of one line item (e.g. a Form D item's invoice date)."""
        v = it.get(key)
        ok = v is not None and (not hasattr(v, "value") or v.value is not None)
        self._input(doc, f"{attr_of(doc, it)}[{key}]", FieldStatus.READ if ok else FieldStatus.NOT_FOUND)
        return v if ok else None

    def master(self, loaded: bool):
        self.inputs.append(dict(doc="", kind="", name="master", status=FieldStatus.READ if loaded else FieldStatus.NOT_FOUND))
        if not loaded:
            self.not_run("master_data_missing", what="master_list")
        return loaded

    # -- outcome
    def compared(self, n: int = 1):
        self.n_compared += n

    def link(self, finding):
        """A finding added by another check that also answers this one (e.g. one finding over a whole B/L phrase)."""
        self.fids.append(finding)
        self.sevs.append(finding.severity)

    def add(self, finding):
        finding.check = self.defn.id
        if self.out is not None:
            self.out.append(finding)
        self.fids.append(finding)
        self.sevs.append(finding.severity)

    def na(self, **evidence):
        """NOT_APPLICABLE, with the positive evidence (e.g. no carton range printed anywhere on the document)."""
        if not self.state:
            self.state, self.detail = CheckStatus.NOT_APPLICABLE, {**self.detail, **evidence}

    def not_run(self, reason: str, **detail):
        if not self.state:
            self.state, self.reason, self.detail = CheckStatus.NOT_RUN, reason, {**self.detail, **detail}

    def master_missing(self, model: str):
        """A model not in the HS master list: NOT_RUN master_data_missing, naming every such model."""
        self.not_run("master_data_missing", what="model")
        if self.reason == "master_data_missing":
            ms = self.detail.setdefault("models", [])
            if model and model not in ms:
                ms.append(model)

    def blocked(self, by: str):
        self.not_run("blocked_by", by=by)

    def absent_or_missing(self, doc, name: str, trace: str | None = None):
        """A field the check needs is not there: NOT_APPLICABLE when the document shows no trace of it at all
        (and the reader listed it as not printed, when it tracks that field), otherwise NOT_RUN."""
        st = status_of(doc, name)
        if st == FieldStatus.READ:
            return
        if st == FieldStatus.ABSENT or (trace is not None and st == FieldStatus.NOT_FOUND and not has_text(doc, trace)):
            self.na(evidence="not_printed", field=name, doc=doc.name)
        else:
            self._input(doc, name, st)

    def error(self, detail):
        self.state, self.reason, self.detail = CheckStatus.NOT_RUN, "internal_error", {**self.detail, **detail}
        self.end()

    def end(self):
        if self.ended:
            return
        self.ended = True
        if self.run is None or self.off:
            return
        if self in self.run.open:
            self.run.open.remove(self)
        status, reason, detail = None, None, dict(self.detail)
        worst = next((_SEV_STATUS[s] for s in ("ERROR", "WARNING") if s in self.sevs), None)
        if self.state == CheckStatus.NOT_RUN and self.reason == "internal_error":
            status, reason = CheckStatus.NOT_RUN, "internal_error"
        elif self.suspect:                                  # P5: a possibly misread input: review, never confirmed
            detail["suspect"] = [dict(m) for m in self.suspect]
            if worst:
                status, reason = CheckStatus.REVIEW_REQUIRED, "suspect_reading"
                why = sorted({m.get("why", "") for m in self.suspect} - {""})
                for f in self.fids:
                    f.suspect = ", ".join(why) or "S"
            else:
                status, reason = CheckStatus.NOT_RUN, "suspect_reading"
        elif self.state == CheckStatus.NOT_RUN and self.reason == "master_data_missing" and "ERROR" not in self.sevs:
            status, reason = CheckStatus.NOT_RUN, "master_data_missing"    # the WARNING says what to add to the list
        elif worst:                                         # a confirmed finding stands, even with inputs missing
            status = worst
            if self.missing:
                detail["incomplete"] = _missing_reason(self.missing)
        elif self.state == CheckStatus.NOT_RUN:
            status, reason = CheckStatus.NOT_RUN, self.reason
        elif self.missing:
            status, reason = CheckStatus.NOT_RUN, _missing_reason(self.missing)
            detail["missing"] = [dict(m) for m in self.missing]
        elif self.state == CheckStatus.NOT_APPLICABLE:
            status = CheckStatus.NOT_APPLICABLE
        elif self.n_compared:
            status = CheckStatus.PASS
        else:
            status, reason = CheckStatus.NOT_RUN, self.reason or "not_reported"
        if status == CheckStatus.NOT_RUN and reason in {*_FIELD_REASON.values(), "items_not_read"} and "missing" not in detail:
            detail["missing"] = [dict(m) for m in self.missing]
        self.run._record(self.defn.id, status, reason, detail, self.doc.name if self.doc is not None else "",
                         self.inputs, self.fids)


def _missing_reason(missing: list) -> str:
    m = missing[0]
    if m["name"] in ("items", "pl_items"):
        return "items_not_read"
    return _FIELD_REASON.get(m["status"], "field_not_found")


def attr_of(doc, it) -> str:
    return "pl_items" if any(it is x for x in getattr(doc, "pl_items", [])) else "items"


def begin(cid: str, out: list | None = None, doc=None) -> Ck:
    return Ck(cid, out, doc)


# ----------------------------------------------------------------------------------------------------- verdict
VERDICTS = ("RED", "AMBER", "GREEN")


def effective_status(r: dict, open_of) -> str:
    """The status after the reviewer's decisions: a check whose findings are all closed no longer counts as FAIL /
    REVIEW_REQUIRED (the stored result is not changed). open_of(finding no.) -> (severity, is_open)."""
    st = r["status"]
    if r.get("reason") == "suspect_reading":                 # P5: review while a finding is open, else still not run
        if any(o for _s, o in (open_of(i) for i in r.get("findings", []))):
            return CheckStatus.REVIEW_REQUIRED
        return CheckStatus.NOT_RUN
    if st not in (CheckStatus.FAIL, CheckStatus.REVIEW_REQUIRED):
        return st
    sev = [open_of(i) for i in r.get("findings", [])]
    if any(s == "ERROR" and o for s, o in sev):
        return CheckStatus.FAIL
    if any(s == "WARNING" and o for s, o in sev):
        return CheckStatus.REVIEW_REQUIRED
    if r.get("detail", {}).get("incomplete"):
        return CheckStatus.NOT_RUN                   # the failure was closed, but the check had missing inputs
    return CheckStatus.PASS


def _blocked_resolved(r: dict, eff: dict) -> bool:
    """A check NOT_RUN(blocked_by X) is not meaningful on its own: X reports the same difference. When every check X
    of its group had findings and the reviewer closed them all, the blocked check follows X."""
    toks = [t.strip() for t in str((r.get("detail") or {}).get("by", "")).split("/") if t.strip()]
    hits = [(o, s) for (o, s) in eff.values() if o.get("group") == r.get("group") and o is not r
            and any(o["id"] == t or o["id"].startswith(t + ".") for t in toks)]
    return bool(hits) and all(s == CheckStatus.PASS for _, s in hits) and any(
        o["status"] in (CheckStatus.FAIL, CheckStatus.REVIEW_REQUIRED) for o, _ in hits)


def verdict(checks: list[dict], findings: list[dict], is_open=lambda f: True) -> dict:
    """Package verdict. RED: an open ERROR finding (core or not). AMBER: an applicable core check NOT_RUN or
    REVIEW_REQUIRED. GREEN: every applicable core check passed or is NOT_APPLICABLE. is_open(finding dict) -> bool
    (reviewer marks); the default (everything open) gives the automated verdict."""
    fs = {f["no"]: f for f in findings}
    open_of = lambda no: (fs[no]["severity"], is_open(fs[no])) if no in fs else ("", False)
    eff = [(r, effective_status(r, open_of)) for r in checks]
    by_key = {id(r): (r, s) for r, s in eff}
    eff = [(r, CheckStatus.PASS if s == CheckStatus.NOT_RUN and r.get("reason") == "blocked_by"
            and _blocked_resolved(r, by_key) else s) for r, s in eff]
    # an ERROR built on a possibly misread value (P5) is not a confirmed document error: it makes the package AMBER
    open_err = sum(f["severity"] == "ERROR" and is_open(f) and not f.get("suspect") for f in findings)
    core = [(r, s) for r, s in eff if r.get("core")]
    core_failed = sum(s == CheckStatus.FAIL for _, s in core)
    core_not_run = [r for r, s in core if s == CheckStatus.NOT_RUN]
    core_review = sum(s == CheckStatus.REVIEW_REQUIRED for _, s in core)
    cats = {}
    for r in core_not_run:
        c = REASONS.get(r.get("reason"), "system")
        cats[c] = cats.get(c, 0) + 1
    noncore_not_run = sum(s == CheckStatus.NOT_RUN for r, s in eff if not r.get("core"))
    closed = sum(not is_open(f) for f in findings if f["severity"] in ("ERROR", "WARNING"))
    if open_err:
        state = "RED"
    elif core_not_run or core_review:
        state = "AMBER"
    else:
        state = "GREEN"
    return dict(state=state, open_errors=open_err, core_failed=core_failed, core_not_run=len(core_not_run),
                core_review=core_review, core_total=sum(s != CheckStatus.NOT_APPLICABLE for _, s in core),
                noncore_not_run=noncore_not_run, categories=cats, reviewer_closed=closed,
                internal_errors=sum(r.get("reason") == "internal_error" for r in checks))


def effective(s: dict, marks: dict) -> dict | None:
    """The verdict of a stored review (session dict) after the reviewer's decisions; None for a review saved by
    LDV <= 2.2 (no check records). The stored automated results are not changed."""
    if not s.get("checks") and int(s.get("schema") or 0) < 2:
        return None
    from .history import OPEN
    is_open = lambda f: marks.get(f["sig"], {}).get("status", "open") in OPEN
    return verdict(s.get("checks") or [], s["findings"], is_open)


def reason_text(r: dict, lang: str, form: str = "") -> str:
    """The EN / VI explanation of a NOT_RUN / NOT_APPLICABLE record."""
    from .rules import CONFIG
    msgs = CONFIG.get("check_reasons", {})
    d = r.get("detail") or {}
    if r["status"] == CheckStatus.NOT_APPLICABLE:
        key = "na_" + str(d.get("evidence", "")) if d.get("evidence") else "na"
    elif r["status"] == CheckStatus.NOT_RUN:
        key = r.get("reason") or "not_reported"
    elif d.get("incomplete"):
        key = "incomplete"
    else:
        return ""
    if key == "master_data_missing" and d.get("models"):
        key = "master_data_missing_models"
    m = msgs.get(key) or msgs.get("na" if key.startswith("na_") else "not_reported") or {}
    miss = d.get("missing") or []
    fld = ", ".join(f"{x['name']} ({x['doc']})" if x.get("doc") else x["name"] for x in miss) or d.get("field", "")
    vals = dict(kind=_kind_label(d.get("kind", ""), lang), inv=d.get("inv", ""), field=fld, doc=d.get("doc", r.get("doc", "")),
                by=d.get("by", ""), rule=d.get("rule", ""), error=d.get("error", ""), invoices=d.get("invoices", ""),
                what=d.get("what", ""), models=", ".join(d.get("models") or []))
    try:
        out = m.get(lang, m.get("en", key)).format(**vals)
    except (KeyError, IndexError):
        out = m.get(lang, key)
    return out if key == "na_form_e_only" else form_text(out, form)     # that one names the Form D on purpose


def kind_name(k: str, lang: str, form: str = "", short: bool = False) -> str:
    """The document type as the reports show it; a C/O by its form (Form D / Form E) when the review knows it."""
    from .rules import CONFIG
    if not k:
        return ""
    d = CONFIG["doc_kinds"].get(k)
    if not d:
        return k
    f = d.get("forms", {}).get(form)
    if short:
        return f["short"] if f else {"CI": "CI / PL", "SC": "S/C", "BL": "B/L", "CO": "C/O"}.get(k, k)
    return (f or d).get(lang) or d["en"]


_kind_label = kind_name


def check_name(cid: str, lang: str, form: str = "") -> str:
    """The check's name; checks written for the Form D are named for the certificate of the set (form: co_form)."""
    from .rules import CONFIG
    n = CONFIG.get("checks", {}).get(cid, {})
    return form_text(n.get(lang) or n.get("en") or cid, form)
