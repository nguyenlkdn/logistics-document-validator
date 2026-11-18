# How LDV reads the documents

LDV reads the text layer of each PDF (no OCR). This page lists **what it reads, the ways of writing a value it
accepts, and what to do when it reads something wrongly**. All examples are invented (ACME, AB-X10, PORT A…).

## 1. From PDF to lines

`engine/pdftext.py` rebuilds the visual lines of a page from the text pieces (spans) and their positions:

- Pieces at the same height form one line; a wide gap between two pieces becomes three spaces, so
  `\s{2,}` in a pattern means "next column".
- Rotated text (DRAFT watermarks, stamps) is left out of the lines, but still counts for "is this a draft".
- Every value LDV reads remembers its line and character range, so the review page can box it on the page.
  **A value must be boxed on its own text**: when one line holds several figures (`950 CARTONS // 12,290.00 KGS //
  55.00 CBM`), each figure gets its own position.

`engine/extract.py` reads the fields of each document type, `engine/extract_net.py` the extra fields used by the
cross-document rules. The document type comes from its title (Sales Contract, Form D, B/L, Commercial invoice /
Packing list) unless the user sets it.

## 2. Ways of writing a value that LDV accepts

| Value | Accepted layouts | Test |
|---|---|---|
| Vessel / voyage | `ABC STAR V.0123-045A` = `ABC STAR/ 0123-045A` = `ABC STAR / V. 0123-045A` = `ABC STAR VOY. 0123-045A` = `ABC STAR 0123-045A`; a trailing comma is ignored. The separator is a writing style (Form D needs `V.`), the voyage still has to match. | `run_reader` vessel |
| Containers on the invoice | `TOTAL CONTAINER : 1x40HQ,1x20GP` = 2; `2 X 40'HC + 1 X 20'GP` = 3. Every part is added, not only the first. | `run_reader` containers |
| Shipping-mark models (invoice, packing list, B/L, Form D box 6) | whole on one line `AB-X10(W1)VN`; split before the colour code `CD-Y20PE` / `(BM)VN`; split after it `EF-Z30(BK)` / `VN` | `run_reader` marks ×3 |
| Form D box 10 invoice no. | the number may wrap onto the next line in its column (`ACME26` / `11E0001`); the pieces in the same column are joined until the date | baseline |
| Form D totals | `TOTAL : ONE THOUSAND … (1,250) CARTON(S)***` on one line, or `CARTON***` on the next line | `run_reader` Form D total |
| Form D goods (box 7) | the goods name may wrap over several lines in its column; the package count `FIVE HUNDRED (500) CARTON(S)` that follows it is not part of the name; the brand gives the full name `"ACME" BRAND ELECTRIC KETTLE` | baseline |
| B/L goods description quantity | `1,251 CARTONS (1,251 SETS)`: cartons **and** quantity are read; both are checked (cartons against the packing list, quantity against the invoice) | `run_reader` B/L qty |
| B/L total cartons | from the said-to-contain box (`1,250 CARTONS`), never from the description phrase above or an attach-sheet row, whichever comes first in the layout | `run_reader` B/L qty |
| B/L attach sheet | `CNTR // SEAL // 950 CARTONS // 12,290.00 KGS // 55.00 CBM`, one row per container | `run_reader` attach sheet |
| B/L quantity per invoice | one line per invoice (`300 CARTON(S) 1,200 PCS`): the lines are added | baseline (multi-invoice sets) |
| Invoice / packing list header | the packing list repeats the invoice header: it is read on its own (`pl_*` fields) so a difference between the two parts shows | baseline |
| Goods description | the full name with the brand (`"ACME" BRAND RICE COOKER`); quotes, `BRAND`, `AND/OF/THE` and plural `S` do not count when comparing; one name inside the other matches | baseline |
| Dates | `21/11/2026`, `21-NOV-2026`, `Nov 21, 2026`, `21 November 2026` … are the same date | baseline |

## 3. "Not read" or "not printed"

A Cross-check cell is **yellow (not read)** when the document should have the value and LDV did not find it, and
**`·` (not printed)** when the label itself is not on the document (this document type, or this layout, does not
carry it). The labels looked for are listed per document in `extract_net.py` (`absent`): for example a B/L without
`FINAL DESTINATION :` or `MADE IN` / `ORIGIN`, an invoice without a container line. A yellow cell on a real
document is a reading gap; a `·` is normal.

## 4. When LDV reads something wrongly

1. Put the documents in `tests/baseline/` (folder or zip; confidential, never committed).
2. `python tools/find_unread.py tests/baseline/<set>` lists values printed in the PDF but shown as not read.
   `[missing]` is almost always a reading gap; `[na]` needs a look at the line.
3. Compare the findings with the documents. A finding that blames the wrong document or the wrong number is a
   reading (or rule) problem too: check what LDV read (`tests/run_baseline.py` prints the extracted fields).
4. Write the layout as a case in `tests/run_reader.py` with invented values. Run it: it must **fail**.
5. Teach `engine/extract*.py` the new layout, as a general pattern (the separator, the line break, the column),
   not for one document. Run `tests/run_reader.py`: it must pass.
6. `python tests/run_baseline.py`: every other set must give the same results. Review the differences; when they
   are all right, approve them with `--update`.
7. Add the layout to the table in section 2.

### Layouts learned so far (2.1)

| Wrong reading | Cause | Fixed by |
|---|---|---|
| Form D box 10 invoice no. cut short | the number wraps in a centred column | join the pieces in the same column |
| Vessel differs though it is the same | `V.`, `/`, `VOY.`, hyphenated voyage | separator-agnostic vessel / voyage |
| Goods name cut or with extra words | name wraps in box 7; package count follows the name | read the column text, cut before the package count |
| Container count 1 instead of 2 | only the first part of `1x40HQ,1x20GP` was read | add every part |
| Model missing from Form D marks | model written whole on one line (others were split) | accept whole and split models |
| Form D total cartons not read | `CARTON***` on the line below the figure | accept the next-line form |
| Carton count in `1,251 CARTONS (1,251 SETS)` never checked | only the quantity in brackets was read | read both, one finding when both are wrong |
| Gross-weight finding boxed on the CBM | one position per attach-sheet row | one position per figure |
| B/L total cartons could come from the wrong line | first `N CARTONS` on the page | said-to-contain box first |
| Wrong document blamed for the HS code (4 findings) | every Form D item compared with the B/L | when all Form D items agree, the B/L is the odd one out (one finding) |
| Carton ranges blamed after a wrong quantity (3 extra findings) | range expected from the wrong quantity | the range that fits the invoice is right; continue from where it really ends |
| Attach-sheet sum "should be" the wrong B/L total | the sheet agrees with the packing list | no finding; the B/L total is reported once |
