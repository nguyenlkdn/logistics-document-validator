# Baseline test data (not in git)

The test sets are real shipment documents and are **confidential**, so they are kept only on the
developer machine. This folder is ignored by git (see `.gitignore`).

Layout when present:
- one sub-folder or `.zip` per shipment set (Invoice/PL, Sales Contract, B/L draft, Form D)
- `expected.json`: the approved findings and extracted data (create it with `tests/run_baseline.py --update`)

`Synthetic_ranges` is a copy of `Testnga2` with the packing list edited on purpose
(CARTON 1-250 -> 0-250, 251-525 -> 260-520). Expected: PL_RANGE_START (-> 1-250),
PL_RANGE_GAP (-> 251-525), Form D (50) -> (250).
