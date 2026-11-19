# P3 + P4 report: columns, B/L cargo blocks, parties, cartons, part numbers

Date 2026-11-19 · branch `p3-p4-structure` (from P2) · not merged, not released. All values in tests and docs are invented.

## P3: columns, B/L cargo blocks, parties

- `Line.cells()` (`engine/pdftext.py`): a text line split into the columns it crosses; `Line.text` unchanged.
- **B/L cargo blocks** (`CargoBlock`, `Doc.cargo_blocks`): goods / HS heading / cartons + quantity / invoice no. per
  invoice, read cell by cell. The B/L quantity, cartons and unit come from the blocks when the old one-phrase
  reader finds nothing.
- **New core check `BL_CARGO_BLOCK`**: each block against its own invoice (finding `BL_BLOCK`). With several blocks the
  B/L goods description and HS heading are taken from the invoice's own block. One block: NOT_APPLICABLE (the old
  checks compare it).
- **Parties**: consignee label with or without colon / space; shipper from its `SHIPPER` label before the old
  "signing company" fallback.
- Dashboard: repeated unread items grouped ("16 goods lines not read (pages 4-6)").

## P4: cartons, part numbers, FOC goods, per-invoice cross-check

- **Packing list cartons** (`Package`, `Doc.packages`): lines after a full row that print only qty + N.W. belong to its
  carton; the carton holds G.W. / CBM / cartons, the lines get none (missing is not zero). `CARTON/NO.1-1` is a range.
  Totals, G.W. ≥ N.W. and the line-sum logic (`true_total`) work per carton; old layouts (one line = one unit) unchanged.
- **Item identity** (`ItemId`, `Doc.item_ids` / `pl_item_ids`): model, or the part number printed below the line;
  goods type from `config.json "goods_categories"`. Lines with part numbers are no longer "model not found"; the line
  comparison also compares part numbers.
- **HS for parts**: when every line is a part, `HS_MASTER`, `BL_HS` and `MARKS` are NOT_APPLICABLE (evidence: every
  line has a part number). The B/L block keeps its own HS heading.
- **FOC goods name**: the quoted description when there is no `BRAND` line (invoice and packing list).
- **Cross-check with several invoices**: a contract / Form D number is compared with the invoices of its own group
  (from the check records); a column where only some documents give the value is shown but not compared ("incomplete").

## Results (all 21 local sets; findings of the 19 approved sets)

| Gate | Result |
|---|---|
| 19 approved sets | extracted values identical; findings identical except **one new finding**: `BL_BLOCK` on `Synthetic_multi_G`. It is the planted error of that synthetic set (a B/L block quantity changed), now reported for the invoice whose block is wrong, next to the existing total `BL_QTY` |
| Check statuses of the approved sets | new check `BL_CARGO_BLOCK` on every set (PASS on multi-block B/Ls, NOT_APPLICABLE otherwise); nothing else changed |
| FOC-parts set | **ERRORs 8 → 1**: only the real Form D departure date is left. "Not read" list empty. Parts invoice: 48 checks PASS, 18 NOT_APPLICABLE with evidence, 0 internal errors |
| Refrigerator set | unchanged since P2 (AMBER: HS master entry missing) |
| `run_unit` | **ALL PASS, incl. both new sets** (first time) |
| Other gates | see the gate run below |

## Still open

1. **Invoices without a contract / Form D** (FOC parts): their 29 contract / Form D checks stay NOT_RUN
   `requirement_unknown` (AMBER) until you approve a rule, e.g. "an invoice marked F.O.C / NO COMMERCIAL VALUE needs
   no contract and no Form D". Not added on my own: the owner rule says FOC must not exempt checks automatically.
2. `RoHS` typo warning → P6 (vocabulary). `PL_HEADER.payment` not printed on the FOC invoice (non-core).
3. `BL_QTY` (total) and `BL_BLOCK` (per invoice) both report one wrong block; keep both, or hide the total when a
   block finding explains it? (Owner choice; both kept now.)
4. Approve the new check statuses / the one new finding into `expected_checks.json` / `expected.json`; add the two new
   sets to `expected.json`.

**Owner decisions (2026-11-19):** 1A: an invoice marked F.O.C / NO COMMERCIAL VALUE / FREE OF CHARGE needs no contract
and no Form D (NOT_APPLICABLE, evidence `foc_invoice`). 2A: a wrong B/L block is reported once (`BL_BLOCK`); the
total check is `blocked_by BL_CARGO_BLOCK`. 3: baselines approved (`expected.json` incl. the two new sets,
`expected_checks.json`; previous copy `expected.before_2.5.json`). 4A: P1–P4 released together as 2.5.0.
