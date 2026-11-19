# P1 implementation report: check runner and verification traceability

Date 2026-11-19 · branch `p1-check-runner` · target version 2.3.0 (not released, not pushed)
Design: `docs/P1_DESIGN.md` (approved) · user guide to the new model: `docs/CHECKS.md`.
No real shipment value appears in this report. The real test sets are labelled R01–R11, and the label-to-file mapping
is kept outside the repository.

## A. Baseline

| | |
|---|---|
| Baseline commit | `9013811` (LDV 2.2.3), confirmed before any change |
| Branch | `p1-check-runner` (from `main` at `9013811`) |
| Version | `VERSION` 2.2.3 → 2.3.0 on the branch only |
| Environment | Linux 7.0, Python 3.12.3 (dev venv), streamlit 1.67.0, pymupdf 1.28.2, openpyxl 3.1.5, Chrome via Playwright for the UI test |
| Pre-existing state | `run_baseline`: 19 approved sets PASS, 2 new sets not in `expected.json`. `run_unit`: 1 failure on the new FOC-parts set (B/L carton total not compared, which is the silent skip this phase is about). `run_reader`: ALL PASS. |

## B. Implementation

### Files

| Created | Purpose |
|---|---|
| `engine/checks.py` | registry (98 `CheckDef`), `CheckResult`, `Run` (groups, applicability, closure, exception isolation), `Ck` check context, `FieldStatus` / `CheckStatus` / `Applicability`, `field_state`, `verdict`, `effective` |
| `tests/run_checks.py` | T0–T18 (+ T3b, T4b, T6b, T17b) on an invented in-memory package; `--local` adds T1 / T4 / T2 on every local set |
| `ui/views/checks.py` | Checks page (filters: status, reason type, core only; detail with inputs and links to findings) |
| `docs/CHECKS.md` | check / field status, reasons, verdict, how to add a rule, limits |

| Modified | Change |
|---|---|
| `engine/rules.py`, `engine/rules_net.py` | every guard clause records its outcome through `ck`; `out.append(Finding)` → `ck.add(Finding)`; rule calls go through `_call()` (isolation); `validate_checks()` returns findings + records; `validate()` unchanged for callers. **Comparisons, severities and texts are unchanged.** |
| `engine/__init__.py` | `Result.checks`, `.verdict`, `.diagnostics`; `diagnostics.log` in the report folder when a rule fails |
| `engine/session.py` | `review.json` schema 2: `checks`, `verdict`, `findings[].check` (additive) |
| `engine/report.py` | new Excel sheet "Checks - Kiem tra" (added **last**, the other sheets unchanged); report.md "Verification" section |
| `engine/review_report.py` | verdict line from the check records (legacy wording for old reviews) |
| `engine/history.py` | `sign(..., verdict=)`: plain approval refused unless GREEN; no schema change |
| `ui/views/dashboard.py`, `ui/views/report.py`, `app.py`, `ui/i18n.py` | three-state banner + detail line, "Checks not run" tile, unread items linked to the checks they block, Checks page in the navigation, sign-off gate, EN / VI strings |
| `config.json` | additive only: `checks` (98 EN/VI names), `core_checks` (52), `check_reasons` (EN/VI) |
| `tools/typo_sweep.py` | a rule error isolated by the runner still counts as CRASH; SILENT typos that make a check NOT_RUN are flagged |
| `tests/ui_smoke.py`, `README.md` | verdict, Checks page, sign-off gate, legacy review |

### Registry inventory (reconciled with the code)

44 code units (42 `r_*` + `_bl_invoices` + the multi-invoice B/L block; `_bl_qty` is instrumented as part of its two callers),
**98 check IDs**, 52 core. Scopes: 54 document, 37 invoice, 5 invoice-or-shipment (B/L totals and cargo), 2 shipment.
8 are scans (they look at all text and have no required input). The design inventory (98 IDs in 79 rows) matched.

Discrepancies found in the code and how they were resolved (no business rule changed):

| Found | Before P1 | Now |
|---|---|---|
| `CONTAINERS` is dropped for multi-invoice packages (`_SHARED_TOTALS`) and never run at shipment level | silent | NOT_RUN `scope_unsupported` (new reason code, "LDV does not make this check here") |
| `INVOICE_REF` is dropped for multi-invoice packages | silent | NOT_APPLICABLE, evidence: several invoices; `BL_INVOICE_REFS` checks the B/L list |
| `_bl_invoices` deletes the B/L total findings when the B/L names an invoice that is not in the package | silent | those checks NOT_RUN `document_missing` (naming the invoice) |
| Several invoices, B/L and invoices both read but no invoice number in common | silent (nobody reports it) | `BL_INVOICE_REFS` NOT_RUN `items_not_comparable` |
| Invoice without P/O numbers + contract | silent PASS | NOT_RUN / the existing WARNING |
| Contract and invoice with no lines read | silent PASS (two empty lists are "equal") | NOT_RUN `items_not_read` |
| Form D items vs invoice lines via `zip()` when the counts differ | the extra lines are silently not compared | NOT_RUN `items_not_comparable` (CO_ITEMS = FAIL reports the count) |
| A rule exception aborted the whole check | crash | NOT_RUN `internal_error` for that rule's checks, the others run, traceback in `diagnostics.log` |

**Deviation from the severity mapping, needs owner confirmation:** `HS_MASTER` / `BL_HS` with a model missing from the HS
master list gives NOT_RUN `master_data_missing`, and the existing `HS_MASTER_MISSING` WARNING is attached. The mapping table would make it
REVIEW_REQUIRED. Both give AMBER; NOT_RUN keeps "missing master data" in its own category (owner §9). A reviewer closing
the warning does not turn it GREEN: the master list has to be completed and the package checked again.

**Addition (effective verdict):** a check `blocked_by` another one (it would report the same difference) follows that
check once the reviewer has closed all of its findings. Without this, accepting an error could never give GREEN.

### Field status

`Field.status` is not stored yet: `field_state()` derives READ / UNREADABLE / ABSENT / NOT_FOUND from the readers'
existing conventions (value None + printed text, `absent` list, missing key). No reader was changed. SUSPECT is defined
and never set. `Missing` has no `.value`, so it cannot be compared or summed. FieldStatus and CheckStatus are separate classes.

### Applicability

Pre-pass per group, before the rules run. Invoice and B/L: required (`document_missing`). Contract: `requirement_unknown` when
absent (no document states when one is required). Form D: required when the contract lists it or a Form D names the
invoice; NOT_APPLICABLE only when every contract lists its documents and none is a Form D; otherwise
`requirement_unknown`. FOC exempts nothing. Inside the rules, NOT_APPLICABLE comes only from independent text evidence (no
`FOB <place>`, no `CARTON n-m`, no totals row with figures, no `ETA`, `absent` list of the reader, …). It never comes from
the failed extraction itself.

## C. Verification

| Suite | Result |
|---|---|
| `tests/run_checks.py` | ALL PASS: T0–T18 + T3b / T4b / T6b / T17b (23 tests) |
| `tests/run_checks.py --local` | ALL PASS: closure + declared inputs + blank-out sweep on all 21 local sets; **4,041 inputs removed, 0 false PASS, 0 vanished checks** |
| `tests/run_baseline.py` | 19 approved sets PASS: **findings and extracted values byte-identical**; 2 new sets not approved (as before) |
| `tests/run_unit.py` | same single pre-existing failure as at `9013811` (new FOC-parts set), no new failure |
| `tests/run_reader.py` | ALL PASS |
| `tests/ui_smoke.py` (Chrome) | ALL PASS: 13 steps, incl. three-state banner, Checks page from the tile + filters, plain approval refused on RED, old schema-1 review opens with the legacy verdict, every page in EN / VI / both |
| Typo sweep, 9 approved real sets, 2.2.3 vs P1 | identical: 3,464 typos, 3,405 caught, **15 silent** (gate ≤ 16), 0 crash, same SILENT list |
| Runtime, 21 sets, median of 3, same machine | full `check()` 4.68–4.79 s → 5.13–5.19 s (**+7.8 % to +8.8 %**); rule phase alone 0.27 → 0.30 s (+8 % to +11 %, about 6 % of the total). The first version was +24 % (Excel styling, a quadratic lookup); both fixed. |
| Confidential-data scan | 158 identifiers from the 21 local sets (invoice, P/O, B/L, container, model, contract numbers, file names) + names / ports / figures from the 2026-11-19 report, against every changed and new file: **0 hits** |
| Rollback | T10 loads a schema-2 `review.json` with the `engine/session.py` of commit `9013811` (taken from git): opens, findings and documents intact, extra keys passed through. No database change. |

Test details: T1 closure, T2 blank-out, T3 exception isolation (+ BaseException not swallowed), T4 declared inputs (+ every
finding produced through a registered check whose keys include it), T5 empty lists, T6 Form D applicability (required / not
listed / unknown / named by another group's Form D), T7 layout trace, T8 multi-invoice B/L cartons, T9 verdict table,
T10 sessions both directions, T11 severity mapping, T12 UI smoke, T13 non-core ERROR → RED, T14 WARNING-only core → AMBER,
T15 unknown requirement (also with "F.O.C" on the invoice) never NOT_APPLICABLE, T16 duplicate invoice numbers keep
separate groups, T17 reviewer acceptance (stored FAIL unchanged, mark logged with who / when, effective verdict follows)
+ sign-off gate, T18 core rule exception never GREEN.

## D. Exceptions and limitations

1. **Not run on the office PC** (Windows, Python 3.15). P1 adds no dependency (stdlib only), but the release must be
   checked there.
2. **Invoices without contract / Form D** (e.g. FOC parts under the same B/L): AMBER `requirement_unknown` until P4 brings an
   approved rule.
3. **`CONTAINERS` not made for multi-invoice packages** (`scope_unsupported`, non-core); a follow-up decision is needed.
4. **Reading gaps now visible, not fixed** (P2/P3): page headers in the invoice layout that prints `Invoice No.:` without `DATE :` (`DOC_HEADER`, non-core);
   contract `FOB PORT,COUNTRY` (`INCOTERM_PORT`, core); Form D box 6 model without a suffix after the colour code
   (`CO_MARKS_MODEL`, non-core); everything listed for the FOC-parts set in the 2026-11-19 report.
5. **Field status is derived**, not set by the readers (P2).
6. **`expected_checks.json` not created.** Approving the check statuses as a baseline needs the owner's OK on table E.
   `expected.json` was not touched.
7. The History page and the PDF/HTML review report show only the verdict line, not the check list (history.db unchanged by design).
8. All 98 checks are instrumented; no rule branch could not be isolated. Missing master data in the 21 sets: R07 (1 model).
9. UI tested in Chrome on Linux only; Edge on Windows not tested.

## E. Per-package verdicts (21 local sets, automated, no reviewer decisions)

| Package | Verdict | Open ERROR | Core FAIL | Core NOT_RUN | Core REVIEW | Non-core NOT_RUN | Master data | Reading | Package | Reviewer dispositions |
|---|---|---|---|---|---|---|---|---|---|---|
| R01 | RED | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| R02 (new, FOC parts) | RED | 8 | 8 | 31 | 0 | 21 | 1 | 9 | 21 | 0 |
| R03 | **GREEN** | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| R04 | RED | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| R05 | RED | 5 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| R06 | RED | 13 | 10 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |
| R07 (new) | **AMBER** | 0 | 0 | 3 | 0 | 1 | 2 | 1 | 0 | 0 |
| R08 | **GREEN** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| R09 | RED | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| R10 | RED | 10 | 3 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| R11 | RED | 4 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Synthetic_multi_D | RED | 2 | 2 | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| Synthetic_multi_E | RED | 1 | 1 | 5 | 0 | 4 | 0 | 0 | 5 | 0 |
| Synthetic_multi_F | **AMBER** | 0 | 0 | 5 | 1 | 1 | 0 | 0 | 5 | 0 |
| Synthetic_multi_G | RED | 1 | 1 | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| Synthetic_multi_H | RED | 2 | 1 | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| Synthetic_net_A | RED | 15 | 10 | 1 | 2 | 1 | 0 | 1 | 0 | 0 |
| Synthetic_net_B | RED | 17 | 14 | 1 | 0 | 0 | 0 | 1 | 0 | 0 |
| Synthetic_net_C (no invoice / contract) | RED | 2 | 1 | 43 | 1 | 32 | 0 | 0 | 43 | 0 |
| Synthetic_net_I | RED | 6 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Synthetic_ranges | RED | 6 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Reading the table: R03 is GREEN with 4 open findings, all on the non-core "documents required" check (insurance policy
under FOB: WARNING; Form D not listed: INFO). R07's AMBER = one model missing from the HS master (two HS checks) + the contract FOB place
not read. Synthetic_multi_E / F: the B/L names an invoice that is not in the package, so its totals are NOT_RUN
`document_missing` (before P1 they silently vanished). R10's core NOT_RUN is `blocked_by INVOICE_REF` (which is FAIL).
R02 keeps its false ERRORs until P2–P4. Its new NOT_RUNs are the silent skips listed in the 2026-11-19 report (B/L cartons
vs both invoices, B/L invoice list, B/L cargo quantity) plus `requirement_unknown` for the parts invoice's contract / Form D checks.

## F. Recommendation

**P1 ACCEPTED WITH DOCUMENTED LIMITATIONS.** Every acceptance gate passed. The limitations above are either
visible on purpose (gaps now reported instead of hidden) or belong to P2–P4. Before release 2.3.0: owner approval of
this report, the HS-master deviation (§B), the table E statuses as `expected_checks.json`, and a check on the office PC.
P2 has not been started.

**Owner decision (2026-11-19):** accepted. The HS-master handling (§B) is kept, the table E statuses are approved as
`tests/baseline/expected_checks.json` (local, compared by `tests/run_baseline.py`), and 2.3.0 is released.
