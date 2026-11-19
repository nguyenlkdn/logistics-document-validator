# P2 report: value grammar

Date 2026-11-19 · branch `p2-value-grammar` (from `main` with P1) · not merged, not released.
All values are invented; the real sets are only counted, never quoted.

## What changed

- **`engine/grammar.py`**: one place for how values are written: whole-token numbers (`NUM`, `DEC`, `DEC2`), quantity
  and carton units (`QTY_UNIT`, `CTN_UNIT`, spaces allowed: `CARTON (S)`), document numbers with `-` `/` `.`
  (`DOC_ID`), dates (`DATE_DMY`) and the sailing label (`SAILING ON OR ABOUT` = `ON/OR ABOUT`). A number is never read
  from the middle of a larger one; ambiguous forms (`1,25`, `1.250,00`) are not read (reported) instead of guessed.
- **Readers moved onto it** (`engine/extract.py`, `engine/extract_net.py`): all 30+ hand-written number patterns,
  the 5 invoice-number patterns, totals rows, packing-list rows, page headers, B/L quantity / cartons / invoice list,
  Form D quantities and totals, sailing, ETA, dates. No `[\d,]+` pattern is left in the readers.
- **New formats accepted:** invoice date printed after the invoice number without `DATE :`; `FOB PORT,COUNTRY`.
- **Field status set by the reader:** `F(value=None)` gives `status="UNREADABLE"`; `field_state` uses it.
- **Cross-check:** the Form D column may name a subset of the invoice numbers (it certifies the invoices it lists; the
  B/L must still list all of them). Without this, reading the second invoice number would show a false mismatch.
- Tests: `tests/run_grammar.py` (number / unit / id / label forms, traps, metamorphic spacing / case), 3 new reader
  cases in `tests/run_reader.py` on invented PDFs. Docs: `docs/READING.md` accepted formats, `README.md`.

## Results

| Gate | Result |
|---|---|
| 19 approved sets | findings, extracted values **and all check statuses identical** |
| FOC-parts set (not approved) | false ERRORs `TOTAL_QTY` and `CI_COVER_TOTAL` gone (8 → 6 ERRORs). Now **run and pass**: B/L cartons vs both invoices, the B/L invoice list, invoice vs packing-list cartons, page headers, packing-list sailing date, far dates |
| Refrigerator set (not approved) | contract FOB read; `INCOTERM_PORT` NOT_RUN → PASS; "not read" list empty |
| `run_grammar`, `run_reader`, `run_checks` | ALL PASS |
| `run_checks --local` | ALL PASS: 4,053 inputs removed on 21 sets, 0 false PASS, 0 vanished |
| `run_unit` | 1 failure on the FOC-parts set (was 1 before): see below |
| Typo sweep, 9 approved real sets | identical to P1: 3,464 typos, 3,405 caught, 15 silent, 0 crash |
| UI smoke | ALL PASS |
| Runtime, 21 sets | full `check()` +8.0 % against 2.2.3 (P1 alone: +8.4 to +8.8 %) |

## Still open (later phases)

- **Cross-check for several invoices** adds up all invoices and compares the total with the contract / Form D,
  which cover only their own invoice (FOC-parts set: amount, quantity, cartons). The rules compare per invoice and
  are right; the table is not. This was already the case before P2 (the unit test stopped earlier). → **P4**, with the
  rule for invoices that have no contract / Form D. This is the remaining `run_unit` failure.
- FOC-parts set, remaining false ERRORs: packing list with one shared carton (`LINE_COUNT`, `CI_PL_QTY`,
  `PL_TOTAL` ×2) → **P4**; shipper read from the wrong column (`PL_HEADER`) → **P3**. `RoHS` → **P6**.
  `DEPARTURE_DATE` is a real difference in the documents.
- Not done in P2: money as `Decimal` (comparisons keep their tolerances), separate kinds for estimated vs actual dates
  (it would change how `DEPARTURE_DATE` is judged: an owner decision).

## Needs owner approval

1. Approve the new check statuses of the two new sets in `expected_checks.json` (the 14 changes listed above, all
   NOT_RUN / FAIL → PASS). Their findings stay outside `expected.json` until P3 / P4.
2. Merge P2 and release it together with P1 (2.3.0) or as 2.4.0.
