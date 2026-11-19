# P1 design: check runner, check statuses, field status, three-state verdict

Status: **design for owner approval. No source code has been changed.**
Scope: P1 only, as approved on 2026-11-19. P2–P5 are not started.
All examples are invented. No real shipment values appear here.

---

## 0. Correction to the Step A review

Step A said "45 rule functions". The exact count is **42 `r_*` functions** (21 in `engine/rules.py`, 21 in
`engine/rules_net.py`), plus **2 rule blocks** inside the validator (`_bl_invoices`, and the B/L-totals block in `_validate_multi`), plus
the shared helper `_bl_qty`. Many functions hold several independent checks (for example `r_co` holds 5). The registry is therefore
defined **per check, not per function**: 44 code units give **98 check IDs** in 79 table rows (§2.2).

---

## 1. Exact list of existing rule functions

| # | Function | File | Finding keys it emits |
|---|---|---|---|
| 1 | `r_line_math` | rules.py | LINE_AMOUNT, TOTAL_AMOUNT, TOTAL_QTY |
| 2 | `r_pl_sums` | rules.py | PL_TOTAL, CI_PL_QTY |
| 3 | `r_bl_vs_pl` | rules.py | BL_VS_PL, CONTAINERS, INVOICE_REF |
| 4 | `r_incoterm` | rules.py | INCOTERM |
| 5 | `r_po_coverage` | rules.py | SC_PO_TYPO, SC_PO_MISSING, SC_PO_EXTRA |
| 6 | `r_sc_vs_ci` | rules.py | SC_VS_CI, SC_NUMBERING |
| 7 | `r_dates` | rules.py | DEPARTURE_DATE, CO_INVOICE_DATE, SHIPMENT_LATE, SHIPMENT_SLACK, SC_DATE |
| 8 | `r_vessel` | rules.py | VESSEL |
| 9 | `r_co` | rules.py | CO_QTY, CO_INVOICE_NO, CO_ITEMS, CO_TOTAL |
| 10 | `r_hs` | rules.py | HS_MASTER_MISSING, CO_HS_MASTER, BL_HS_CODE, HS_CODE, BL_HS_MASTER |
| 11 | `r_containers` | rules.py | CNTR_WORDS, CNTR_COUNT, CNTR_TYPE, CNTR_TYPE_CBM, CNTR_SUMMARY, CNTR_CAPACITY, CNTR_ATTACH_SUM |
| 12 | `r_bl_cargo` (+ `_bl_qty`) | rules.py | BL_MARKS_MODEL, BL_DESC_QTY, BL_QTY, BL_DESC_CTN, BL_UNIT, BL_GOODS_DESC, BL_DESTINATION |
| 13 | `r_co_marks` | rules.py | CO_MARKS_MODEL |
| 14 | `r_pl_ranges` | rules.py | PL_RANGE_ORDER/START/GAP/OVERLAP/COUNT, PL_RANGE_TOTAL |
| 15 | `r_co_packages` | rules.py | CO_PKG_COUNT, CO_SET_PER_CTN, PL_SET_PER_CTN, CO_GOODS_DESC, CO_TOTAL (ctn) |
| 16 | `r_pod` | rules.py | PORT_NAME |
| 17 | `r_words` | rules.py | WORDS_VS_FIGURES |
| 18 | `r_text_fixes` | rules.py | (config `text_fixes` ids) |
| 19 | `r_broken_wrap` | rules.py | WORD_WRAP |
| 20 | `r_documents` | rules.py | SC_DOCS_INSURANCE, SC_DOCS_FORMD |
| 21 | `r_draft_status` | rules.py | ISSUED_DOC |
| 22 | `_bl_invoices` | rules.py | BL_INVOICE_EXTRA, BL_INVOICE_MISSING |
| 23 | `_validate_multi` B/L block | rules.py | DOC_UNPAIRED, BL_VS_PL, BL_QTY, BL_DESC_CTN, BL_DESC_QTY (shipment level) |
| 24 | `r_cover_totals` | rules_net.py | CI_COVER_TOTAL, PL_COVER_TOTAL |
| 25 | `r_gw_nw` | rules_net.py | PL_GW_NW |
| 26 | `r_eta` | rules_net.py | ETA_DATE |
| 27 | `r_headers` | rules_net.py | DOC_HEADER |
| 28 | `r_cover_pos` | rules_net.py | CI_PO_LIST |
| 29 | `r_co_self` | rules_net.py | CO_SUM, CO_NUMBERING, CO_PAGES |
| 30 | `r_ci_pl_ctn` | rules_net.py | CI_PL_CTN |
| 31 | `r_lines` | rules_net.py | LINE_COUNT, PL_LINE, CI_LINE_DESC |
| 32 | `r_co_model` | rules_net.py | CO_MODEL |
| 33 | `r_marks` | rules_net.py | CI_MARKS_MODEL, PL_MARKS_MODEL, MARKS_MISSING |
| 34 | `r_origin` | rules_net.py | ORIGIN |
| 35 | `r_import_country` | rules_net.py | CO_IMPORT_COUNTRY |
| 36 | `r_parties` | rules_net.py | PARTY_NAME |
| 37 | `r_currency` | rules_net.py | CURRENCY |
| 38 | `r_payment` | rules_net.py | PAYMENT_TERMS |
| 39 | `r_sc_goods` | rules_net.py | SC_GOODS_DESC |
| 40 | `r_pl_header` | rules_net.py | PL_HEADER |
| 41 | `r_freight` | rules_net.py | FREIGHT_TERM |
| 42 | `r_date_far` | rules_net.py | DATE_FAR |
| 43 | `r_text_typo` | rules_net.py | TEXT_TYPO |
| 44 | `r_unreadable` | rules_net.py | VALUE_UNREADABLE |

---

## 2. Check registry and input dependencies

### 2.1 Mechanism (`engine/checks.py`, new)

```python
@dataclass
class CheckDef:              # one entry per check id, all in REGISTRY (engine/checks.py)
    id: str                  # "BL_VS_PL.ctn"
    scope: str               # "invoice" (once per invoice group) | "shipment" (once per package) | "document" (once per doc of `kinds`)
    kinds: tuple             # documents the check reads, e.g. ("BL", "CI")
    needs: tuple             # declared inputs, e.g. ("BL.ctn", "CI.true_total.ctn")
    applies: str             # applicability rule name (§2.3)
    absent_is: str           # what a field "not printed on this layout" means here: "NOT_APPLICABLE" | "NOT_RUN"
    kind: str                # "compare" (needs inputs) | "scan" (looks at all text; runs whenever its document exists)
    keys: tuple              # finding keys it may emit

@dataclass
class CheckResult:           # one per (check id, group) in every run
    id: str; group: str      # group = invoice no. / document name / "shipment"
    status: str              # PASS | FAIL | REVIEW_REQUIRED | NOT_RUN | NOT_APPLICABLE
    reason: str | None       # machine code (§3), None for PASS/FAIL
    detail: dict             # {"doc": ..., "field": ..., "field_status": ...}, used for the EN/VI text
    findings: list           # indexes of the findings it produced
    core: bool
```

The rule bodies are not rewritten. Each guard clause is replaced by a call that **records why** it stops:

```python
# today                                          # P1
if not (ci and bl):                              ck = run.begin("BL_VS_PL.ctn", group)
    return                                       if not ck.need_doc(bl, ci): ...        # records NOT_RUN(document_missing)
b, p = bl.f.get("ctn"), true_total(ci, "ctn")    b = ck.need(bl, "ctn"); p = ck.need_total(ci, "ctn")
if b and p and not _close(...):                  if ck.ok and not _close(...):
    out.append(Finding(...))                         ck.add(Finding(...))               # appends to out + links it
                                                 ck.end()                               # PASS / FAIL / NOT_RUN
```

Guarantees, enforced by the runner and not by rule discipline:
1. **Closure.** After all rules have run, every registered check without a result for an applicable group gets
   `NOT_RUN(reason="not_reported")`. A test fails if this ever happens on a synthetic set, so it is a safety net, not normal behaviour.
2. **Exceptions.** Each rule function runs inside `try/except`. On an exception, every check of that function still open gets
   `NOT_RUN(internal_error, detail=exception type + message)`. The other rules continue, and the error is written to the log.
   (Today one exception aborts the whole check, as with the KeyError fixed in v2.1.3.)
3. **Declared vs used inputs.** `ck.need()` records each field it reads. A unit test checks that every field read through `need()` is
   listed in `CheckDef.needs`, so the registry cannot drift from the code.
4. **No PASS without inputs.** `ck.end()` gives PASS only when every needed input has status READ (P5 will add: and not SUSPECT) and at least one
   comparison was actually made (`ck.compared()` is called inside the loop). An empty list (no items, no P/O numbers) gives NOT_RUN, not PASS.

Mapping from findings to the check status: an ERROR finding gives **FAIL**. A WARNING finding gives **REVIEW_REQUIRED**. MINOR and INFO
findings give **PASS** (with the findings attached). The finding severities themselves do not change.

### 2.2 The check IDs (98 IDs in 79 rows)

Legend: **C** = core (configurable, `config.json "core_checks"`), core group number from the owner list in brackets. Scope: I = per invoice group,
S = per shipment, D = per document. Inputs written `KIND.field`; `CI.Σ` = `true_total` (line sum or printed total).

| # | Check ID | Core | Scope | Inputs (needs) | From function |
|---|---|---|---|---|---|
| 1 | LINE_MATH.ci | | D(CI) | CI.items[qty,price,amount] | r_line_math |
| 2 | LINE_MATH.sc | | D(SC) | SC.items[qty,price,amount] | r_line_math |
| 3 | TOTAL_AMOUNT.ci | C(1) | D(CI) | CI.total_amount, CI.items | r_line_math |
| 4 | TOTAL_AMOUNT.sc | C(7) | D(SC) | SC.total_amount, SC.items | r_line_math |
| 5 | TOTAL_QTY.ci | C(1) | D(CI) | CI.total_qty, CI.items | r_line_math |
| 6 | TOTAL_QTY.sc | C(7) | D(SC) | SC.total_qty, SC.items | r_line_math |
| 7 | PL_TOTAL.qty | C(1) | D(CI) | CI.pl_total_qty, CI.pl_items[qty] | r_pl_sums |
| 8 | PL_TOTAL.nw | C(2) | D(CI) | CI.pl_total_nw, CI.pl_items[nw] | r_pl_sums |
| 9 | PL_TOTAL.gw | C(2) | D(CI) | CI.pl_total_gw, CI.pl_items[gw] | r_pl_sums |
| 10 | PL_TOTAL.cbm | C(3) | D(CI) | CI.pl_total_cbm, CI.pl_items[cbm] | r_pl_sums |
| 11 | PL_TOTAL.ctn | C(1) | D(CI) | CI.pl_total_ctn, CI.pl_items[ctn] | r_pl_sums |
| 12 | CI_PL_QTY | C(1) | D(CI) | CI.items[qty], CI.pl_items[qty] | r_pl_sums |
| 13 | BL_VS_PL.gw | C(4) | I or S | BL.gw, CI.Σgw (all invoices for S) | r_bl_vs_pl / multi |
| 14 | BL_VS_PL.cbm | C(4) | I or S | BL.cbm, CI.Σcbm | r_bl_vs_pl / multi |
| 15 | BL_VS_PL.ctn | C(4) | I or S | BL.ctn, CI.Σctn | r_bl_vs_pl / multi |
| 16 | CONTAINERS | | I | BL.containers, CI.containers | r_bl_vs_pl |
| 17 | INVOICE_REF | C(5) | I | BL.invoice_no / BL.invoice_nos, CI.invoice_no | r_bl_vs_pl |
| 18 | BL_INVOICE_REFS | C(5) | S | BL.invoice_nos, every CI.invoice_no | _bl_invoices |
| 19 | INCOTERM_PORT | C(7) | D(each) | BL.pol or CI.pol, doc.fob | r_incoterm |
| 20 | SC_PO_COVERAGE | C(7) | I | CI.pos (non-empty), SC.sc_no/pos | r_po_coverage |
| 21 | SC_VS_CI | C(7) | I | CI.items, SC.items (both non-empty) | r_sc_vs_ci |
| 22 | SC_NUMBERING | | D(SC) | SC.items[no] | r_sc_vs_ci |
| 23 | DEPARTURE_DATE | C(8) | I | CO.departure, CI.sailing | r_dates |
| 24 | CO_INVOICE_DATE | C(8) | I | CO.items[inv_date], CI.invoice_date | r_dates |
| 25 | SHIPMENT_DATE | C(7) | I | SC.shipment_by, CI.sailing | r_dates |
| 26 | SC_DATE | | I | SC.sc_date, CI.invoice_date | r_dates |
| 27 | VESSEL.ci | | I | BL.vessel, CI.vessel | r_vessel |
| 28 | VESSEL.co | C(8) | I | BL.vessel, CO.vessel | r_vessel |
| 29 | CO_QTY | C(8) | I | CO.items[qty], CI.items[qty] | r_co |
| 30 | CO_INVOICE_NO | C(8) | I | CO.items[inv_ref], CI.invoice_no | r_co |
| 31 | CO_ITEMS | C(8) | I | CO.items, CI.items | r_co |
| 32 | CO_TOTAL.value | C(8) | I | CO.total_value, CI.Σamount | r_co |
| 33 | CO_TOTAL.qty | C(8) | I | CO.total_qty, CI.Σqty | r_co |
| 34 | HS_MASTER | C(9) | I | master list, CI.items[model] | r_hs |
| 35 | CO_HS | C(9) | I | CO.items[hs], master or BL.hs | r_hs |
| 36 | BL_HS | C(9) | S | BL.hs, master HS of invoice models | r_hs |
| 37 | CNTR_WORDS | | D(BL) | BL.cntr_words, BL.cntr / BL.containers | r_containers |
| 38 | CNTR_COUNT | | D(BL) | BL.containers, BL.cntr | r_containers |
| 39 | CNTR_TYPE | | I | BL.cntr, CI.cntr_types or BL.cntr_summary | r_containers |
| 40 | CNTR_SUMMARY | | I | BL.cntr_summary, CI.cntr_types | r_containers |
| 41 | CNTR_CAPACITY | | D(BL) | BL.cntr, BL.cntr_load | r_containers |
| 42 | CNTR_ATTACH_SUM | | D(BL) | BL.cntr_load, BL.ctn/gw/cbm | r_containers |
| 43 | BL_MARKS_MODEL | | I | BL.marks_models, CI models | r_bl_cargo |
| 44 | BL_CARGO_QTY | C(6) | I or S | BL.bl_qty, CI.Σqty | r_bl_cargo / multi (_bl_qty) |
| 45 | BL_CARGO_CTN | C(6) | I or S | BL.bl_qty_ctn, CI.Σctn | r_bl_cargo / multi (_bl_qty) |
| 46 | BL_UNIT | | I | BL.bl_unit, CI unit | r_bl_cargo |
| 47 | BL_GOODS_DESC | | I | BL.goods, CI.goods | r_bl_cargo |
| 48 | BL_DESTINATION | | D(BL) | BL.final_dest, BL.delivery/pod | r_bl_cargo |
| 49 | CO_MARKS_MODEL | | I | CO.marks_models, CI models | r_co_marks |
| 50 | PL_RANGES | C(1) | D(CI) | CI.pl_items[rng] | r_pl_ranges |
| 51 | PL_RANGE_TOTAL | C(1) | D(CI) | CI.pl_items[rng], CI.pl_total_ctn | r_pl_ranges |
| 52 | CO_PKG | C(8) | I | CO.items[pkg_fig, pkg_words, per_ctn], CI.pl_items paired | r_co_packages |
| 53 | CO_GOODS_DESC | | I | CO.items[goods], CI.pl_items[desc] | r_co_packages |
| 54 | CO_TOTAL.ctn | C(8) | I | CO.total_ctn (+words), CI.Σctn | r_co_packages |
| 55 | PORT_NAME | | D scan | doc.pod list | r_pod |
| 56 | WORDS_VS_FIGURES | | D scan | amount words + total; Form D/B/L "WORDS (n)" | r_words |
| 57 | TEXT_FIXES | | D scan | all text | r_text_fixes |
| 58 | WORD_WRAP | | D(BL) scan | all text | r_broken_wrap |
| 59 | SC_DOCS | | D(SC) | SC.docs_required | r_documents |
| 60 | DRAFT_STATUS | | D(BL,CO) | is_draft | r_draft_status |
| 61 | DOC_PAIRING | C(8) | S | every SC/CO paired to one invoice | _validate_multi |
| 62 | CI_COVER_TOTAL | C(1) | D(CI) | CI.ci_ttls (≥2 rows), CI.Σ | r_cover_totals |
| 63 | PL_COVER_TOTAL | C(2) | D(CI) | CI.pl_ttls (≥2 rows), CI.Σ | r_cover_totals |
| 64 | PL_GW_NW | C(2) | D(CI) | CI.pl_items[nw,gw], CI.pl_total_nw/gw | r_gw_nw |
| 65 | ETA_DATE | | D(CI) | CI.eta, CI.sailing | r_eta |
| 66 | DOC_HEADER | | D(CI) | CI.headers (≥2) | r_headers |
| 67 | CI_PO_LIST | | D(CI) | CI.cover_pos, CI.items[po] | r_cover_pos |
| 68 | CO_SUM | C(8) | D(CO) | CO.items, CO.total_qty / total_ctn | r_co_self |
| 69 | CO_NUMBERING | | D(CO) | CO.items[no] | r_co_self |
| 70 | CO_PAGES | | D(CO) | CO.pages | r_co_self |
| 71 | CI_PL_CTN | C(1) | D(CI) | CI.ci_ttls[-1].ctn, CI.Σctn | r_ci_pl_ctn |
| 72 | LINES | C(1) | D(CI) | CI.items, CI.pl_items | r_lines (LINE_COUNT, PL_LINE, CI_LINE_DESC) |
| 73 | CO_MODEL | C(8) | I | CO.items[model], CI.items[model] (same count) | r_co_model |
| 74 | MARKS | | I | marks on CI/PL/BL/CO, CI models | r_marks |
| 75 | ORIGIN | | S | origin on ≥2 documents | r_origin |
| 76 | CO_IMPORT_COUNTRY | C(8) | I | CO.import_country, BL.dest_country | r_import_country |
| 77 | PARTY.consignee / PARTY.shipper | C(10) | S | ≥2 documents with the name | r_parties |
| 78 | CURRENCY · PAYMENT_TERMS · SC_GOODS_DESC · FREIGHT_TERM | C(7) for the first 3 | I | see function | r_currency, r_payment, r_sc_goods, r_freight |
| 79 | PL_HEADER.<field> ×13 · DATE_FAR · TEXT_TYPO · VALUE_UNREADABLE | C(10) for PL_HEADER.consignee/.shipper | D | see function | r_pl_header, r_date_far, r_text_typo, r_unreadable |

(Rows 77–79 group several IDs to keep the table short. The registry lists each one separately: 2 + 4 + 16 IDs. The 13 `PL_HEADER` fields
are one ID each because a missing field on one part must not hide the others.)

### 2.3 Applicability (when a check is NOT_APPLICABLE)

A check is NOT_APPLICABLE only when there is **positive evidence** that it does not apply, never just because the input is missing:

| Rule | NOT_APPLICABLE when | Otherwise |
|---|---|---|
| `has_doc(K)` (SC, CO, BL checks) | document K is not in the package **and** nothing requires it. Form D is required when: the group's SC lists "Form D / certificate of origin" in its documents required, **or** a Form D in the package names the invoice in box 10. A B/L is always required. An SC is required unless config `sc_optional` lists the case (none today). | NOT_RUN(`document_missing`) when required but absent. NOT_RUN(`requirement_unknown`) when no document says whether it is required (e.g. an invoice with no SC and no Form D). **FOC does not make anything NOT_APPLICABLE in P1.** |
| `layout_has(X)` (cover totals, carton ranges, ETA, attach sheet, P/O list on the cover, repeated headers, container types on the invoice) | the document text contains **no trace** of X at all. The test is the same kind as the existing `absent` detection: no `TTL` row on the cover, no `CARTON n-m`, no `ETA`, no `//` attach row … | NOT_RUN(`field_not_found` / `field_unreadable`) when a trace exists but was not read. This is how `FOB PORT,COUNTRY` on a contract becomes NOT_RUN instead of being silently treated as "no FOB on this contract". |
| `two_sources` (ORIGIN, PARTY, CURRENCY, DOC_HEADER) | fewer than 2 documents print the value **and** the others do not print it at all (`absent`) | NOT_RUN(`too_few_values`) when another document prints it but it was not read |
| `master` (HS_MASTER, CO_HS with master) | — (always applicable when the invoice has a finished-goods model) | NOT_RUN(`master_data_missing`) when the master list is not loaded or a model is not in it. **Category "master data", shown apart from reading problems.** |

---

## 3. Guard clauses → NOT_RUN reasons

Machine codes (`reason`) with one EN/VI message each in `config.json "check_reasons"`:

| Code | Category | Meaning (EN) |
|---|---|---|
| `document_missing` | package | The {kind} needed for this check is not in the package. |
| `requirement_unknown` | package | No document in the package says whether a {kind} is required for invoice {inv}. |
| `field_not_found` | reading | {field} was not found on {doc}. |
| `field_unreadable` | reading | {field} on {doc} was found but could not be understood ("{raw}"). |
| `field_absent_required` | reading | {field} is not printed on {doc}, but this check needs it. |
| `items_not_read` | reading | The goods lines of {doc} were not read. |
| `items_not_comparable` | reading | The lines of {a} and {b} cannot be paired (different counts: {n} vs {m}); see {check}. |
| `too_few_values` | reading | Only {n} document(s) gave a value; {doc} prints it but it was not read. |
| `master_data_missing` | master data | No HS code in the master list for {model} (or the master list is not loaded). |
| `blocked_by` | dependency | Not meaningful because {check} already failed (e.g. CO_MODEL when CO_ITEMS differ). |
| `internal_error` | system | LDV error while running this check: {error}. Please report it. |
| `not_reported` | system | The check did not report a result (LDV fault; safety net). |

Mapping of today's guards (every guard in the 44 units; the line refers to the current file):

| Function | Guard today | P1 record |
|---|---|---|
| r_line_math | `d.kind not in (CI, SC)` | (check not applicable to that kind; no record) |
| | `if tot and d.items` / `if tq and d.items` | no items → NOT_RUN `items_not_read`; total not printed → NOT_APPLICABLE when `absent` has it, else `field_not_found` |
| r_pl_sums | `not d.pl_items` | NOT_RUN `items_not_read` for PL_TOTAL.*, CI_PL_QTY |
| | `if tot and …` per measure | `field_not_found` / `field_unreadable` |
| | ctn: `all(it["ctn"])` and no ranges | ranges present → NOT_APPLICABLE (PL_RANGE_TOTAL owns it); a line without cartons → `field_not_found` |
| r_bl_vs_pl | `not (ci and bl)` | `document_missing` |
| | `if b and p` per measure | `field_not_found` (which document, which field) |
| | containers `c1 and c2` | invoice has no container line (`absent`) → NOT_APPLICABLE; else `field_not_found` |
| | invoice ref `b and c` | `field_not_found` (B/L or invoice no.) |
| r_incoterm | `not src[1]` (no POL) | `field_not_found` POL |
| | doc without `fob` | NOT_APPLICABLE if no `FOB` in its text, else `field_unreadable` |
| r_po_coverage | `not (ci and scs)` | `document_missing` / `requirement_unknown` |
| | (no guard) empty `ci.pos` | **new:** NOT_RUN `field_not_found` (today: a silent PASS) |
| r_sc_vs_ci | `not (ci and scs)` | as above |
| | (no guard) empty items | **new:** NOT_RUN `items_not_read` (today: PASS when both empty) |
| r_dates | `co and sail and departure` | CO missing → applicability rule; sailing / departure → `field_*` |
| | `co and inv_date`, per item `if f` | `field_*` per item (detail lists the item numbers) |
| | `by and sail`, `scd and inv_date` | `field_*` |
| r_vessel | `not ref` (B/L vessel) | `field_not_found` for both VESSEL checks |
| | `if f` per doc | `field_*` for that check |
| r_co | `not (ci and co)` | applicability rule |
| | `zip(co.items, ci.items)` (silently cuts to the shorter list) | counts differ → CO_QTY / CO_INVOICE_NO `items_not_comparable` (CO_ITEMS = FAIL reports it) |
| | `if a and bv is not None` | `field_*` |
| r_hs | `have` (master loaded) | `master_data_missing` |
| | model `None` | HS_MASTER: `items_not_read` (model) |
| | `hs_bl` None | CO_HS without master + BL_HS: `field_not_found` B/L HS |
| r_containers | `not bl` | `document_missing` |
| | `w and ref_n`, `fig and n_lines`, `expect and lines`, `summ and ci_types`, `loads` | layout trace test: not printed → NOT_APPLICABLE; printed, not read → `field_*` |
| r_bl_cargo / _bl_qty | `not (ci and bl)` | `document_missing` |
| | `q and qty is not None`, `c and ctn is not None` | `field_*`. **The 2-cargo-block case gives NOT_RUN `field_not_found` (bl_qty), so it is visible. P3 replaces it with per-block checks.** |
| | `u and ci_unit`, `g and cg`, `fd` / `a and b` | `field_*` |
| r_co_marks | `not (ci and co)`, empty marks | applicability; marks not printed as models → NOT_APPLICABLE |
| r_pl_ranges | `not ci`, no ranges | NOT_APPLICABLE when no `CARTON n-m` text; else `field_unreadable` |
| | `tot and …` | `field_*` |
| r_co_packages | `not (ci and co)` | applicability |
| | `_pairs()` empty | `items_not_comparable` |
| | `tot and ref` | `field_*` |
| r_pod, r_words, r_text_fixes, r_broken_wrap, r_text_typo, r_date_far, r_unreadable | scans | PASS / FAIL when the document exists; r_date_far without an invoice date → `field_not_found` |
| r_documents | (SC loop) | NOT_APPLICABLE without SC; `docs_required` empty → `field_not_found` |
| r_draft_status | — | always PASS/INFO |
| _bl_invoices | `not listed or not inv or no overlap` | `field_not_found` (B/L invoice list / invoice no.); no overlap at all → FAIL is decided by INVOICE_REF (unchanged) |
| _validate_multi | `listed - known` (B/L covers more) | BL_VS_PL.* shipment: NOT_RUN `field_not_found` "invoice {n} on the B/L is not in the package" |
| | `not b or not all(ps)` | `field_*` naming **each** invoice whose total is missing (the case seen on 2026-11-19) |
| | `scores[0][0] == 0 or tie` | DOC_PAIRING REVIEW_REQUIRED (DOC_UNPAIRED is a WARNING today; unchanged) |
| r_cover_totals | `len(rows) < 2` | NOT_APPLICABLE (no second TTL row in the text) / `field_unreadable` |
| r_gw_nw | `nw and gw` | `field_*` |
| r_eta | `eta and sail` | NOT_APPLICABLE without ETA text; `field_*` |
| r_headers | < 2 headers | NOT_APPLICABLE for a 1-page file; else `field_not_found` (page header not read) |
| r_cover_pos | no cover P/O, no line P/O | NOT_APPLICABLE / `field_*` |
| r_co_self | `not co.items` | `items_not_read` |
| r_ci_pl_ctn | no `ci_ttls` | `field_not_found` |
| r_lines | no items / pl_items | `items_not_read`; LINE_COUNT = FAIL stops PL_LINE → PL_LINE `blocked_by` |
| r_co_model | counts differ | `blocked_by` CO_ITEMS |
| r_marks | no models / no marks list | `items_not_read` / NOT_APPLICABLE (marks not written as models) |
| r_origin, r_parties, r_currency | `_odd_ones` < 2 values | rule `two_sources` |
| r_import_country | no `dest_country` | `field_*` |
| r_payment, r_sc_goods, r_freight | missing value | `field_*` / NOT_APPLICABLE when not printed |
| r_pl_header | either side empty | per field: `absent` on both parts → NOT_APPLICABLE; one side missing → `field_*` |

The findings these functions produce stay **byte-identical**. Only records are added.

---

## 4. Field status migration design

**P1 adds a status without changing any reader.**

- `Field` gets an optional attribute `status: str = "READ"` (a dataclass field with a default, so every existing
  `Field(value, raw, line, start, end)` call keeps working). `F(..., value=None)` sets `UNREADABLE`.
- New accessor `field_state(doc, name) -> Field | Missing`. `Missing(name, status, doc)` has the status:
  - `UNREADABLE`: a Field with `value is None` and printed text (today's VALUE_UNREADABLE convention),
  - `ABSENT`: the name is in the document's `absent` list (today's comma-joined field, unchanged in P1),
  - `NOT_FOUND`: anything else (the key is missing or `None`).
  - `SUSPECT`: defined in the enum and the reason table, **never set in P1** (P5, after its own design review).
- Rules only see inputs through `ck.need()`, which calls `field_state` and records the status in the check detail.
  There is no second store: the status is derived from what the readers already write. The `absent` field, the `_RAW` sentinel and missing keys stay
  where they are until P2/P3 move the readers. Then the readers set `status` directly, and the derivation is deleted. (This is a migration adapter, not a second source of truth.)
- Field status and check status are two separate enums (`FieldStatus`, `CheckStatus`), as the owner required.
- `Missing` is not a number. A rule cannot compare it (it has no `.value`), so "missing becomes zero" cannot happen by accident.

---

## 5. Session and review.json compatibility

- `review.json` `schema` 1 → **2**. New top-level keys only:
  `checks: [{id, group, status, reason, category, msg_en, msg_vi, core, findings: [no…], inputs: [{doc, field, status}]}]` and
  `verdict: {state: GREEN|AMBER|RED, core_failed, core_open, master_data, reading, package}` (computed when the check runs).
- **Old sessions (schema 0/1, LDV ≤ 2.2.3)** open as today. There is no check list, and the verdict banner says
  "*Checked with LDV {version}: no check list. Run the check again to see which checks ran.*" The old verdict is shown with the label "legacy".
- **2.2.3 reading a schema-2 file** (after a rollback): the loader reads only the keys it knows and does not test `schema`,
  so the extra keys are ignored. This will be verified by opening a 2.3 review.json with the 2.2.3 code in a test.
- `history.db`: **unchanged in P1** (no migration on the office PC). The verdict lives in review.json. The History page keeps its
  current columns.
- Reviewer decisions stay in history.db. The displayed verdict is computed from the automated check results **and** the open/closed
  state of the findings (a finding marked "not an error" no longer makes its check FAIL for the verdict). Stored results are never rewritten.

---

## 6. UI and Excel changes

**Verdict (dashboard banner, Excel summary sheet, report.md, review PDF):**

| State | Rule | Banner |
|---|---|---|
| RED: DOCUMENT ERROR | a core check is FAIL with an open ERROR finding | "Document errors: n core checks failed" |
| AMBER: INCOMPLETE / REVIEW | otherwise, a core check is NOT_RUN or REVIEW_REQUIRED | "Not verified: n core checks could not run / need review", with the categories counted apart: *reading*, *master data*, *package* |
| GREEN: VERIFIED | every applicable core check PASS (NOT_APPLICABLE does not block) | "Verified: all n applicable core checks passed" |

**Proposed addition, needs owner decision (§11 Q1):** an **open ERROR finding from a non-core check** (e.g. VESSEL on the invoice)
also gives RED. Without it, a package with a real document error outside the core list would show GREEN, which is worse than
today (today any open error is red).

**Checks view.** A new "Checks" section on the Dashboard (tile *"Checks not run (n)"*) and a filterable table (status, core, category) on the
Findings page: each row shows the check, group (invoice), status, the reason in the user's language, and links to its findings and to the
document/page of a missing field. Core NOT_RUN rows are listed first.

**Unread list.** The current "unrecognised" list stays. Each entry is linked to the checks it blocked ("blocks: BL_VS_PL.ctn, BL_CARGO_QTY").

**Sign-off.** Plain approval is allowed only on GREEN. On AMBER or RED, the existing *exception* sign-off (with a reason) is required. This is a
change: today approval is refused only while errors are open.

**Excel.** New sheet "Checks - Kiem tra": check ID, name EN/VI, core, group, status, reason EN/VI, finding numbers.
The summary sheet gets the verdict line. The Findings sheet is unchanged.

**i18n.** All new texts in EN and VI in `config.json` / `ui/i18n.py`.

---

## 7. Synthetic test cases (new `tests/run_checks.py`, invented values, committed)

| # | Test | Proves |
|---|---|---|
| T1 | Registry closure: every synthetic set of `run_reader` + `tests/baseline/Synthetic_*`: every registered check has exactly one record per applicable group, and none has `not_reported` | no check disappears |
| T2 | **Blank-out sweep:** for each check that reached PASS or FAIL, remove each of its READ inputs in turn (delete the key, set `value=None`, empty the list) and re-validate. Expect NOT_RUN with the right reason, **never PASS**, record still present | missing input can never give PASS (owner §3.2) |
| T3 | Exception isolation: patch one rule to raise. Its checks → NOT_RUN `internal_error`; all other findings and checks unchanged | exceptions cannot hide checks |
| T4 | Declared vs used inputs: every `need()` call during T1 is listed in `CheckDef.needs` | registry does not drift |
| T5 | Empty lists: invoice without P/O numbers + contract → SC_PO_COVERAGE NOT_RUN; invoice and contract without items → SC_VS_CI NOT_RUN | the two silent-PASS cases found in §3 |
| T6 | Applicability: (a) no Form D, contract requires Form D → `document_missing`; (b) no Form D, contract does not ask for it → NOT_APPLICABLE; (c) invoice with no contract and no Form D → `requirement_unknown`; (d) Form D box 10 names an invoice that is not in the package | Form D applicability is not assumed |
| T7 | Layout trace: cover TTL row absent → NOT_APPLICABLE; present but unreadable (`1,O50 SET(S)`) → NOT_RUN `field_unreadable` | NOT_APPLICABLE needs positive evidence |
| T8 | Multi-invoice: 2 invoices, the 2nd without a readable carton total → BL_VS_PL.ctn (shipment) NOT_RUN naming the 2nd invoice; gw/cbm still PASS | the 2026-11-19 silent skip is now visible |
| T9 | Verdict table: combinations of core PASS/FAIL/NOT_RUN/REVIEW/NA, findings open/closed, master-data-only gaps | verdict rules exactly as in §6 |
| T10 | Session: schema-2 round trip; a schema-1 file opens with the "legacy" banner; a schema-2 file loads with the 2.2.3 loader code | backward compatibility |
| T11 | Severity mapping: ERROR → FAIL, WARNING → REVIEW_REQUIRED, MINOR/INFO → PASS | check status from findings |
| T12 | `ui_smoke` additions: banner shows the 3 states; the Checks table opens; old review opens | UI |

---

## 8. P1 acceptance criteria

1. **Findings unchanged:** `run_baseline` findings + extracted values identical on all 19 approved sets (no `--update`).
2. T1–T12 pass. `run_unit`, `run_reader`, `ui_smoke` pass. `typo_sweep` SILENT count not higher than today (16).
3. Blank-out sweep on all 21 local sets (19 + 2 new, run locally, results not committed): 0 PASS after removal, 0 vanished checks.
4. Every check record has a machine reason and an EN + VI text. Every core check has an applicability rule.
5. Per-set table of verdicts and NOT_RUN core checks for the 21 sets, presented to the owner with the reason for every AMBER (§9).
6. The check-status snapshot is stored in a **new** file `tests/baseline/expected_checks.json`, created only after owner approval.
   `expected.json` is not modified.
7. Old sessions open. A rollback to 2.2.3 can read new sessions.
8. Run time per package: ≤ 10 % slower (measured with `LDV_PROFILE=1`).
9. Confidential-data check: grep of the diff, the new tests and docs for real numbers (invoice/PO/B/L/container patterns from the local sets) = 0.

---

## 9. Expected changes to the baseline output

- **Findings: none.** P1 adds records only. Any finding difference is a P1 bug.
- **New output:** check records + verdict per set. Expected pattern:
  - Sets with open ERROR findings on core checks → RED (most real and synthetic sets have such findings).
  - The one set with 0 findings → GREEN only if every applicable core check reaches PASS. Any core NOT_RUN found there is a reading gap
    that is invisible today and will be listed.
  - `Synthetic_net_C` (no invoice, no contract) → AMBER/RED with `document_missing` for the invoice-based checks.
- **The 2 new sets (not yet approved):**
  - FOC-parts set: stays RED (in P1 the false errors are still there; they go in P2–P4, and the Form D departure-date FAIL is real).
    **New and visible:** BL_VS_PL.ctn (shipment) NOT_RUN naming the parts invoice; BL_INVOICE_REFS NOT_RUN (invoice no. not read);
    BL_CARGO_QTY/CTN NOT_RUN; for the parts invoice group, Form D and SC checks NOT_RUN `requirement_unknown`.
  - Refrigerator set: AMBER. HS_MASTER is NOT_RUN `master_data_missing` (category master data), and INCOTERM_PORT for the SC is NOT_RUN
    `field_unreadable` (the `FOB PORT,COUNTRY` gap). Today this set shows 1 warning and looks almost clean.
- Exact lists are produced by the implementation and presented before anything is approved.

---

## 10. Risks and rollback

| Risk | Effect | Mitigation |
|---|---|---|
| A guard classified NOT_APPLICABLE that should be NOT_RUN | false GREEN | NOT_APPLICABLE only with positive text evidence (§2.3); T2/T7; owner reviews the §3 table |
| Too many AMBER sets | users stop reading the banner | categories shown apart; non-core NOT_RUN never affects the verdict; review of the per-set table before release |
| Rule edits change findings | baseline regression | findings must stay byte-identical (hard gate 1); guard changes are mechanical |
| `try/except` hides real crashes | errors unseen | `internal_error` is a core-level AMBER, shown in red text with the error, and logged |
| Sign-off becomes stricter | users blocked | exception sign-off with reason already exists |
| Session format | old LDV can't open new reviews | additive keys only; T10 |
| Office PC | — | no new dependency, no DB migration |

**Rollback:** P1 is one commit and one release (proposed 2.3.0, released only with owner OK). The updater keeps `_backup/`. Reverting the commit
restores 2.2.3 behaviour, and review.json files written by 2.3.0 stay readable by 2.2.3. No data migration has to be undone.

---

## 11. Owner decisions needed before coding

1. **Verdict:** should an open ERROR finding from a **non-core** check also give RED (recommended), or only core FAIL as written in §3.6?
2. **WARNING → REVIEW_REQUIRED:** a core check whose only findings are WARNINGs (e.g. PARTY_NAME, which is a WARNING today) gives AMBER, not RED. OK?
3. **Requirement unknown:** an invoice with no contract and no Form D (e.g. a parts/FOC invoice under the same B/L) gives AMBER `requirement_unknown`
   for the SC and Form D checks, until a rule for such invoices is approved (P4). OK?
4. **Sign-off:** plain approval only on GREEN (exception sign-off otherwise). OK?
5. Core list as in §2.2 (C markers). Any check to add or remove?
