# LDV architecture (2.5)

LDV reads a shipment's documents (invoice / packing list, sales contract, B/L, Form D), compares them and reports.
It never changes a document. Everything here is deterministic: the same files give the same result.
Decisions behind this design: `docs/adr/`. Reading formats: `docs/READING.md`. Checks and verdict: `docs/CHECKS.md`.

## 1. Pipeline

```
files (zip / folder / PDF)
  │ engine/__init__.check()        collect, fingerprint, report folder
  ▼
engine/pdftext.py                  spans → visual lines (Line.text) and their columns (Line.cells())
  ▼
engine/extract.py (+ extract_net)  classify (title) → readers per kind → Doc
engine/plausibility.py             P5: readings with a detectable defect → Field.status SUSPECT
        uses engine/grammar.py     whole-token numbers, units, document numbers, dates, labels
  ▼
Doc: f (Field), items / pl_items, lists, cargo_blocks (B/L), packages (packing list), item_ids / pl_item_ids
  ▼
engine/rules.py (+ rules_net)      rules, each check through a check context (engine/checks.py)
engine/checks.py                   registry (99 checks, core list in config), groups (per invoice + shipment),
                                   applicability, field status, closure, exception isolation, verdict
  ▼
findings + check records + verdict
  ▼
report.xlsx / report.md / evidence/*.png / review.json (session) / history.db (reviewer decisions)
  ▼
ui/ (Streamlit): dashboard, review workspace, cross-check (engine/compare.py), checks, findings, report
```

## 2. Canonical data model

| Structure | Where | Holds |
|---|---|---|
| `Field` | extract.py | value, raw text, line, character span (→ page and box), `status` (READ / UNREADABLE / SUSPECT) and `why` |
| `Doc` | extract.py | kind, lines, `f` (scalar fields), `items` / `pl_items` (line dicts), `lists`, `cargo_blocks`, `packages`, `item_ids`, `pl_item_ids` |
| `CargoBlock` | extract.py | one B/L cargo block: goods, HS heading, cartons, quantity, unit, invoice no. |
| `Package` | extract.py | a packing-list carton (range) holding several lines: G.W., CBM, cartons once |
| `ItemId` | extract.py | model or part number + goods type (`config.json "goods_categories"`) |
| `CheckDef` / `CheckResult` | checks.py | a check's definition (scope, documents, declared inputs, finding keys) / one execution record |
| `Finding` | rules.py | message key, severity, documents, current → suggested, locations, `check` |

`items` / `pl_items` dicts are the line view the rules always used. New code reads cartons, blocks and identities from the
structures above (`_units()`, `_bl_block()`, `item_ids`). Missing values are never zero: a `Missing` state has no value.

## 3. Check lifecycle

1. **Groups:** one per invoice (`inv1`, `inv2` …, stable even with equal invoice numbers) + `shipment`.
2. **Applicability before the rules:** documents a check needs but the group lacks give NOT_RUN (`document_missing` /
   `requirement_unknown`) or NOT_APPLICABLE on positive evidence (e.g. the contract lists no Form D; an F.O.C invoice).
3. **Rules:** every guard goes through `ck.need…()`; a comparison is `ck.compared()`; a finding is `ck.add()`.
4. **Closure:** a check without a record → NOT_RUN `not_reported` (tests fail on it). A rule exception → NOT_RUN
   `internal_error` for its checks, traceback in `diagnostics.log`; other rules continue.
5. **Verdict:** RED (open ERROR) / AMBER (core check NOT_RUN or REVIEW_REQUIRED) / GREEN. The effective verdict on screen
   also uses the reviewer's marks (history.db); stored results are never changed.

## 4. Provenance and evidence

Every Field keeps its line and character span; `rules.at()` turns that into a page box. Evidence PNGs (red = wrong,
green = reference) and the on-page highlights in the review workspace come from these boxes. Values worked out from
lines (`Calc`, `true_total`) point at the lines they add up.

## 5. Master data

- HS master: the user's Excel (`MA HS.xlsx`) → `~/Documents/LDV_data/master_hs.json`, re-imported when it changes
  (`engine/master.py`). A model missing from it is **master data** (`master_data_missing`), not a reading problem.
- Ports / cities, typo fixes, technical terms, goods categories, core checks, messages: `config.json`.

## 6. Classification of results

| Shown as | Meaning |
|---|---|
| ERROR / WARNING / MINOR / INFO finding | the document differs (severity per rule) |
| check NOT_RUN, category *reading* | LDV did not read or could not understand an input |
| check NOT_RUN, category *master data* | the HS master or city list lacks an entry |
| check NOT_RUN, category *package* | a required document is missing, or nothing says whether it is required |
| check NOT_APPLICABLE | evidence that the check does not apply |
| check NOT_RUN, category *system* | LDV fault or not supported (`internal_error`, `scope_unsupported`) |

## 7. Testing

| Test | Proves |
|---|---|
| `tests/run_grammar.py` | number / unit / id / label forms, partial-number traps, metamorphic spacing / case |
| `tests/run_reader.py` | every layout variant LDV must read, on invented PDFs |
| `tests/run_checks.py` (`--local`) | closure, declared inputs, blank-out sweep (removing any input never gives PASS), applicability, verdict, sessions, isolation |
| `tests/run_unit.py` | review features, cross-check backed by rule findings |
| `tests/run_baseline.py` | approved findings / extracted values (`expected.json`) and check statuses (`expected_checks.json`) of the local sets |
| `tools/typo_sweep.py` | a one-character typo in any value read is reported |
| `tests/ui_smoke.py` | browser walk-through of every page in EN / VI |

Test documents are confidential and stay out of git; tests in git use invented values only.

## 8. Known limits (2.5)

- Text layer only: a scanned PDF without text is not read (no OCR).
- `CONTAINERS` (B/L vs invoice container count) is not made for packages with several invoices (`scope_unsupported`).
- Money is compared as floats with fixed tolerances (no `Decimal`).
- Estimated (sailing on or about) and actual departure dates are not told apart.
- Plausibility gate (P5, `engine/plausibility.py`): three rules only (S1 cut number, S2 unread goods lines, S3 label before a name); other misreadings are not detected.
