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
| Shipping-mark models (invoice, packing list, B/L, Form D box 6) | whole on one line `AB-X10(W1)VN`; split before the colour code `CD-Y20PE` / `(BM)VN`; split after it `EF-Z30(BK)` / `VN` ; a lowercase typo (`AB-xX10(W1)VN`) is read too, so it is reported | `run_reader` marks ×4 |
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
| Numbers (all readers, `engine/grammar.py`) | whole tokens only: `357` = `357.00`, `1,250` = `1,250.00`, `0.481`, `48,316.250`. A number is never read from the middle of another (`357.00` is never `00`). `1,25` and `1.250,00` are ambiguous: not read, reported | `run_grammar` |
| Quantity / carton units | `SET(S)` = `SET (S)` = `SETS` = `SET`, `PCS` = `PC` = `PIECE(S)`, `UNIT(S)`; cartons `CARTON(S)` = `CARTON (S)` = `CARTONS` = `CTNS` | `run_grammar`, `run_reader` P2 |
| Invoice number | letters / digits with `-` `/` `.` inside: `ACME2611E001`, `ABC26-XYZ021`; on the invoice, page headers and the B/L invoice list | `run_reader` P2 |
| Invoice date | `DATE : 05/10/2026`, `Invoice Date: …`, or the date printed after the invoice number without a label | `run_reader` P2 |
| Sailing label | `SAILING ON OR ABOUT` = `SAILING ON/OR ABOUT` = `Sailing On Or About` | `run_grammar`, `run_reader` P2 |
| FOB place | `FOB PORT A`, `FOB PORT A   IN USD`, `FOB PORT A,COUNTRY` / `FOB PORT A, COUNTRY` (the country is not part of the place) | `run_reader` P2 |
| B/L with several invoices | one **cargo block** per invoice in the description column: goods (`"…" BRAND …` or a quoted description), `HS CODE`, `n CARTON(S) m PCS`, `INVOICE NO. x`, read cell by cell so the shipping-mark column beside it does not matter. Each block is compared with its own invoice (`BL_CARGO_BLOCK`); the B/L quantity is their sum | `run_reader` P3 |
| Parties on the invoice | `CONSIGNEE : NAME`, `CONSIGNEE NAME`, `CONSIGNEENAME` (no space), or the name on the next line; the shipper from its `SHIPPER :` label (only without a label: the company signing the invoice) | `run_reader` P3 |
| Packing list: one carton, several lines | the first line prints qty, N.W., G.W., CBM; the next lines only qty and N.W. They are lines of one **carton** (`CARTON/NO.1-1`), which holds G.W. and CBM once; a line without them gets none (not zero). The carton may continue on the next page after a TTL row | `run_reader` P4 |
| Goods lines without a model | identified by the **part number** printed below (`100000000001@AB`); goods type from the description (`config.json "goods_categories"`: label, packaging, part). The HS master list (finished-goods models) does not apply to them | `run_reader` P4 |
| Goods name without a brand | the quoted description of the invoice (`"SPARE PARTS OF …"`) when there is no `"…" BRAND …` line | `run_reader` P4 |

### Other layouts (LDV 2.7)

| Document | How it is read | Test |
|---|---|---|
| Excel invoice / packing list / contract (`.xlsx`, `.xlsm`) | `engine/xlsx.py`: every **visible** sheet's print area is drawn as a PDF page (`<file> [Invoice+PL].pdf`, `<file> [Contract].pdf`, one contract per sheet) so the viewer and highlights work; values are read from the **cells** (label cell -> value cell, table header -> column). Hidden working sheets are not documents. Freight / insurance rows are charges: total = lines + charges. A packing list written container by container is compared per model (`PL_MODEL_QTY`), not line by line. | `run_reader` Excel ×4 |
| Form E (ASEAN-China) | `engine/form_e.py`: the goods table is read column by column (box headings + the column rules on the page). Box 7 words cut at the column edge (`SE-` / `VEN`) and figures split over lines (`(12` / `5)`) are joined; an item may go on at the top of the next page; box 10 printed once covers the items under it; `TOTAL PACKED IN … (n) CARTONS`; third-party operator = the seller, box 1 = the maker. Form E prints no quantity / value total (not applicable). Findings say "Form E". | `run_reader` Form E ×2 |
| B/L without label text (labels in the background picture) | `engine/bl_plain.py`: shipper / consignee / notify = the three name blocks at the top left; receipt, vessel + loading port, discharge port + delivery = the rows under them (by column); containers, cartons + KGS + CBM, the said-to-contain column, `TOTAL: n×40HC`. | `run_reader` plain B/L |

## 3. "Not read" or "not printed"

A Cross-check cell is **yellow (not read)** when the document should have the value and LDV did not find it, and
**`·` (not printed)** when the label itself is not on the document (this document type, or this layout, does not
carry it). The labels looked for are listed per document in `extract_net.py` (`absent`): for example a B/L without
`FINAL DESTINATION :` or `MADE IN` / `ORIGIN`, an invoice without a container line. A yellow cell on a real
document is a reading gap; a `·` is normal.

## 4. Typos: nothing may pass silently

A value LDV cannot read is a value it cannot check, so a typo must never make a value simply disappear. Three
safeguards, in this order:

1. **`TEXT_TYPO`** looks at every word of every page, whether LDV reads that field or not: a lowercase letter among
   capitals (`HAIPhONG`, `SEtS`, `xX10`, `20l`), a digit for a letter (`C0LLECT`, `1NDUSTRIES`), a letter for a
   digit (`2O26`, `1,O43`, `36.O0`, `I2/11/2026`), and typos only their place shows (`(2S) CARTON`, `ONE (I)
   CONTAINER`, `CARTON I-1250`, `Page : I of 2`, `1x4OHQ`, `1x41HQ`, `U.5 Dollars`). A short doubtful word (`PC5`,
   `TW0`, `LA1`) counts only when its correction is written elsewhere in the package, so product codes stay quiet.
2. **`VALUE_UNREADABLE`**: a value found at its label but not understood (an impossible date such as month 13)
   is reported; it never stands in as text for a date or a number.
3. **`required_fields`** in `config.json`: fields every real document of that type has; one that is not read is
   listed under "could not read".

Plus rules for typos that look valid: `DATE_FAR` (a date more than 300 days from the invoice date: a mistyped
year), `PL_LINE` / `CI_LINE_DESC` (line description), `CNTR_ATTACH_SUM` to the last decimal.

**Proof:** `python tools/typo_sweep.py tests/baseline/SET.zip …` puts a one-character typo into every value LDV reads
(lowercase letter, look-alike, changed digit), checks the package again and lists each typo that gives no new
finding (`SILENT`) or stops the check (`CRASH`). Run it after any change to the readers or rules. Known limits:
the B/L number (no other document prints it) and two-letter words in Title case (`Hp` for `HP`: `By`, `No.` are
written that way on purpose).

## 5. When LDV reads something wrongly

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
7. `python tools/typo_sweep.py tests/baseline/<set>`: no `CRASH`, no new `SILENT`.
8. Add the layout to the table in section 2.

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
| Wrong shipping-mark model not reported | the model had a lowercase typo (`AB-xX10(W1)VN`), so it was not read as a model and nothing was checked | marks accept lowercase letters after the first one |
| Check crashed on a mistyped date (`21-NOV-2O26`, month 13) | an unreadable date was kept as text and compared with dates | the date stays empty and is reported (VALUE_UNREADABLE) |
| A typo in a capital word matched anyway (`HAIPhONG` = `HAIPHONG`) | names are compared without case | TEXT_TYPO on the word itself |
| A look-alike typo made the value disappear (`C0LLECT`, `10S3`) | the pattern did not match, nothing was said | TEXT_TYPO + required fields |
| `I2/11/2026` read as 2 November | the date was found inside the longer text | a day glued to a letter is no date |
| Form D package figure not read when split in pieces | pieces joined as `( 500 )` | spaces allowed inside the brackets |
| Invoice line description not checked | only the packing list's was read | description read per invoice line, compared with the packing list |
| B/L final destination `Hcm, VIETNAM` shown as not read | only capitals were accepted | the value is read as written |

### HS master list: suggestions (LDV 2.8)

- Reference data page: models of checked invoices that the list lacks, with the HS code printed on their certificates
  and what supports it (`engine/hs_suggest.py`). The user confirms each one; nothing is added by itself.
- Added models are kept in `master_hs_added.json`; the company Excel is never changed and always wins.
- A Form E prints 6 digits: the 8-digit master code must begin with them. A Form D is compared on all digits.

### Place names

- Ports and terminals belong to a city: the general list in config "cities" plus the names the user confirms on the
  Reference data page (`engine/places.py`). A name of no known city is not guessed: its check does not run.
- Confirmed names are kept in `places_added.json` in the data folder, never in the repository.

### Carrier B/Ls and several shipments (LDV 2.8)

- Labelled boxes (`engine/bl_box.py`): carrier B/Ls and sea waybills whose box labels are text. Each value is the text
  under its label; cargo is read from the typed rows (with footnotes such as `++COUNTRY`) or from the columns.
- Plain B/Ls with containers written with slashes (`engine/bl_plain.py`), description on an attached sheet included.
- Excel goods names printed beside each model are read per line.
- Several B/Ls in one package: each is checked with the invoices it names (and their contracts and certificates).
  A draft and the final B/L of one invoice are both checked. Files with one name in several folders stay apart.
- `CNTR_VS_PL`: container numbers, cartons, weight and volume per container = packing list.
  `SC_CHARGES`: freight / insurance on all contracts together = invoice.
