# LDV architecture review: Step A (review only, no code changed)

Date: 2026-11-19 · Version reviewed: 2.2.3 (commit 9013811)
Input: the 2026-11-19 problem report (two new real sets; that report stays outside the repo).
All examples below are invented (ACME, AB-X10, INV-0001 …). No real shipment values appear here.

---

## 1. Summary

The 2026-11-19 defects are not nine separate bugs. They come from **four design weaknesses**, and each one will keep
producing new defects whenever a supplier changes a layout:

| # | Weakness | Defects it caused on 2026-11-19 |
|---|---|---|
| W1 | **The PDF line has no columns.** `pdftext` joins every text piece at the same height into one line across the whole page. Readers then guess columns with `\s{2,}` and `^`/`$` anchors. | B/L cargo blocks not read (the shipping-mark column sits in the same line), PL shipper read from the shipping mark beside the signature, PL lines without GW/CBM not read |
| W2 | **No shared value grammar.** About 150 regex calls live inline in the readers (`extract.py` + `extract_net.py`). The same idea (a number, an invoice no., a carton count, a sailing label) is written again in each place, with different gaps. | `120.00` read as `00` (one of 41 hand-written `[\d,]+` patterns), hyphenated invoice no. missed (the same regex in 5 places), `SAILING ON/OR ABOUT`, `CARTON (S)` |
| W3 | **A rule that cannot run disappears.** Guard clauses (`if b and p:` …; a rough count finds ~90 in the rule files) skip a check without leaving a trace. The "unread" list is built separately from a `required_fields` list, so it never says *which check* was lost. | B/L cartons vs the sum of both invoices not checked, B/L lists-both-invoices not checked, B/L qty not checked, SC Incoterm not compared. The screen showed nothing about any of these. |
| W4 | **A wrong reading is treated as a document error.** Nothing tests whether an extracted value is plausible before rules use it. A partial number (`00`) or a 1-of-12-lines reading goes straight into ERROR findings. | 6 of the 7 false ERRORs (total qty 0 while the lines add up to 120; "1 line" while the invoice has 12) |

Two smaller weaknesses add to this:
- **W5:** Toshiba finished-goods assumptions are built into the readers: model pattern, `"TOSHIBA" BRAND`, units SET/PCS only, PO `PR` + 12 digits. This hurts parts/FOC invoices.
- **W6:** The typo check has no technical vocabulary (`RoHS`).

**What is already sound and should be kept:** value-level provenance (every `Field` knows its line, character span,
page and box), the evidence images, deterministic report-only behaviour, `true_total` (it falls back to the printed
total when the lines disagree), the "printed but not understood" sentinel, the explicit cell statuses in the
Cross-check (`value / missing / na / nodoc`), the synthetic PDF tools (`mutate_pdf`, `run_reader`), and `typo_sweep`.

**Recommendation:** do not rewrite into the 8-layer, ~17-class design in the master prompt. The engine is about 4,000 lines for
one office, and a full rewrite would put 19 approved baselines at risk for no gain the users would see. Instead, fix W1–W4
at their source with **four targeted layers** (§5), then move the readers onto them one document type at a time. The
baseline must be explained at every step.

---

## 2. Current architecture (map)

```
inputs (zip/folder/PDF)
  └─ engine/__init__.check()            collect files → load each PDF → validate → evidence → report/session
       ├─ extract.load(path, kind)
       │    ├─ pdftext.doc_lines()      spans → visual lines (one line = full page width, 3 spaces for a wide gap)
       │    ├─ classify(text)           title keywords → CI | SC | BL | CO (one invoice+PL per CI doc)
       │    ├─ _extract_ci/sc/bl/co     inline regexes → Doc.f{name: Field}, Doc.items[dict], Doc.pl_items[dict]
       │    └─ extract_net.EXTRA[kind]  more regexes, adds fields (pl_* header copy, parties, currency, absent…)
       ├─ rules.validate(docs)
       │    ├─ 1 invoice  → _validate_group: 25 r_* functions + rules_net.validate_net (20 more)
       │    └─ n invoices → pair SC/CO to an invoice by score, run the group per invoice, B/L totals over all
       ├─ rules.unrecognised()          missing required_fields + unparsed goods rows + missing models
       ├─ compare.py                    Cross-check table from the session (explicit missing / na / nodoc)
       └─ evidence / report / session   PNG crops, Excel/MD, review.json; UI reads only the session
```

Answers to the questions in Phase 0:

| Question | Finding |
|---|---|
| 1. Entry point per document type | `extract.load` for all types; the type comes only from title keywords (`classify`). No layout or variant detection. |
| 2. Who owns extraction / normalisation / validation | Extraction: `extract.py` + `extract_net.py`. Normalisation is **spread out**: `util.num/parse_date`, `rules._canon_port/_city`, `rules_net._party/_terms`, `compare._atoms`. Validation: `rules.py` + `rules_net.py`. |
| 3. Is extraction tied to layouts? | Yes. Each reader is a sequence of patterns fitted to the layouts seen so far (e.g. the invoice item = `qty UNIT␣␣price␣␣amount` at the line end). |
| 4. Same conventions across readers? | No. The same concept is written 5–41 times with different variants (§3 W2). |
| 5. Missing vs mismatch? | Partly. The Cross-check has explicit statuses, and `F(value=None)` means "printed but not understood". Rules do not: missing input = silent skip. |
| 6. Is provenance kept? | Yes for values read (line + span + page). No confidence, no record of which method read it. Calculated totals (`Calc`) keep their source lines. |
| 7. Can the system tell a check was skipped? | **No.** That is W3. |
| 8. Several invoices under one B/L? | At document level, yes (one CI document per invoice; the B/L is compared with the sum). The B/L's own **per-invoice cargo blocks are not modelled** (one `bl_qty`, a fallback list of rows, the first HS code only). |

---

## 3. Root causes of each reported defect

| Report item | Immediate cause (file) | Weakness |
|---|---|---|
| Qty `120.00` → `00` | `extract._extract_ci`: `^(?:TTL|TOTAL)\b.*?([\d,]+)\s*(?:SET\(S\)|PCS)`: the lazy `.*?` lets `[\d,]+` start after the dot. No token boundary. | W2, W4 |
| Invoice no. with a hyphen | `INVOICE NO\.?\s*([A-Z0-9]{8,})` in `extract.py` ×2 and `extract_net.py` ×3 (CI, B/L, page headers) | W2 |
| Invoice date beside the number | the date reader needs a `DATE :` label | W2 |
| `SAILING ON/OR ABOUT` | only the label `Sailing On Or About` / `SAILING ON OR ABOUT` exists | W2 |
| PL n lines → 1 | `pl_rx` needs qty + NW + GW + CBM at the line end; a line in a shared carton shows only qty + NW. The data model has no carton level. | W1, W2, model |
| `CARTON (S)` | `CARTON\(S\)` without an optional space, in 3 places | W2 |
| Shipper on the invoice = consignee line | consignee label needs `CONSIGNEE\s*:`; shipper = "last company line that is not the buyer". With no buyer read, the consignee line wins. | W2, W5 (heuristic) |
| PL shipper = `VIETNAM (THAILAND) CO., LTD.` | the signature `ACME TRADING` / `(THAILAND) CO., LTD.` shares visual lines with the marks column `ACME` / `VIETNAM` | **W1** |
| B/L cargo blocks / 2nd invoice / 2nd HS | `bl_qty_rows` is anchored `^\s*… PCS\s*$`, but the line starts with the shipping-mark column (`MARKS   500 CARTON(S) 500 PCS`). `invoice_no` regex has no hyphen. `hs` = first match only. | **W1**, W2, model |
| Parts lines "model not found" | `MODEL_RE` = finished-goods pattern; part no. on the next line (`…@AB`) is not an identifier the model knows | W5 |
| `RoHS` typo | `typo_words` reads mixed case as a typo; no list of technical terms | W6 |
| SC `FOB PORT,COUNTRY` not read | `_fob_all` needs 2 spaces or the line end after the port | W2 |
| **Checks lost, nothing shown** | guards in `_validate_multi` (`if not b or not all(ps): continue`), `r_bl_vs_pl`, `_bl_invoices` | **W3** |
| **6 false ERRORs** | rules compare values without asking whether the reading is believable (qty total 0 with lines > 0; 1 PL line vs n invoice lines) | **W4** |

---

## 4. Systemic weaknesses in more detail

**W1. Lines without columns.** `pdftext.page_lines` groups spans by y only. Every reader works on full-width strings.
Shipping marks, signatures, stamps and table columns therefore mix freely. Readers protect themselves with anchors,
`\s{2,}` splits and "take the first segment". Those guards fail as soon as a column is added on the left. The
per-span x positions **are already there** (`Line.spans`), but nothing uses them as columns, except `_co_item_details`
and `_co_invoices`, which do it by hand.

**W2. Inline patterns instead of a value grammar.** Each reader writes its own number, date, unit and label
patterns. A fix in one place (e.g. lowercase marks in v2.2.1, ranges in 2.1) leaves the copies elsewhere unfixed.
`util.num()` turns text into a float after the regex has already chosen the text, so it cannot notice that it
was given half a token.

**W3. No record of rule execution.** Rules are plain functions that append findings. When an input is missing they
`return`/`continue`. The UI can show "Field not found: X", but X is a field name; the user is never told
"*the B/L carton total was not checked*". The verdict banner counts these gaps as one amber hint, so a set where the
most important check never ran can look nearly clean.

**W4. No plausibility gate between reading and rules.** A value that was read is trusted completely. There is no
self-consistency test such as "printed total vs its own lines", "the invoice and PL line counts differ by more than
×2", or "total 0 with non-zero lines" that would mark the *reading* as suspect before rules turn it into an
ERROR against the document. Rule 2 ("missing is not zero") is mostly followed (`None` is used), but "**partly read is not
fully read**" is not.

**W5. Domain assumptions in the readers.** `MODEL_RE`, `PO_RE = PR\d{12}`, `"TOSHIBA" BRAND`, units
`SET(S)|PCS`, a CI with one goods kind. Every item must have a model, otherwise it is "not read". There is no notion of goods category
(finished product / part / packaging / label / FOC) or item identifier type (model vs part no.).

**W6. Text checks without vocabulary.** TEXT_TYPO patterns are document-wide with a small package vocabulary.
Technical terms, acronyms and trademarks are not known.

**Other technical debt (lower priority)**
- `Doc.f` is a flat string-keyed dict with `pl_` prefixes and a comma-joined `absent` field. Field state is spread
  over four conventions: missing key, `None`, `value=None`, listed in `absent`.
- The baseline is a golden snapshot of real (confidential, git-ignored) sets. It detects *change*, not
  *correctness*, and `--update` approves everything at once.
- `typo_sweep` only mutates values LDV already reads (already noted after v2.2.1). Unread fields are a blind spot.
- Text layer only: scanned PDFs (no text) are not supported and not detected as such.

---

## 5. Proposed target architecture (incremental, compatible)

Four new pieces, each small, placed between the existing stages. The readers, rules, `Field`, session and UI stay;
they move onto the new pieces step by step.

```
PDF ─► pdftext (lines + NEW columns/cells) ─► classify (+ NEW layout profile)
     ─► readers (use NEW value grammar)  ─► Doc (Field + NEW status; NEW Carton / CargoBlock / item id)
     ─► NEW plausibility gate (reading problems ≠ document errors)
     ─► rules via NEW check runner (every check: PASS / FAIL / NOT_RUN(reason) / NOT_APPLICABLE)
     ─► findings + check list ─► report / session / UI (NEW "checks not run" + finding origin)
```

### L1. Cells and columns (`engine/pdftext.py`): fixes W1
- `Line.cells()`: a line split at wide gaps into cells with x ranges. Spans exist already; this is a view on them.
- `columns(lines, header_line)`: assign cells to the columns of a table header by x overlap. This is the same technique
  that `_co_item_details` already uses by hand, made reusable.
- `region(lines, x0, x1)`: the lines of one column band (e.g. the B/L description column without the marks column,
  the invoice signature without the shipping mark).
- `Line.text` is unchanged, so existing readers keep working until they are moved over.

### L2. Value grammar (`engine/grammar.py`, data in `config.json`): fixes W2
One module that owns **token-level** recognisers. Each returns a `Field` with the whole token and its kind:
- `number(text)`: whole tokens only (`120`, `120.00`, `1,250`, `1,250.00`, `0.512`, `12,345.210`). It rejects `1.250,00`
  and `1,25` as ambiguous (reported as VALUE_UNREADABLE, not guessed). It never matches inside a larger token.
  `Decimal` for amounts. Integer quantity vs decimal quantity is checked against the unit (PCS 120.00 = 120 is fine; PCS 120.5 is flagged).
- `qty_unit(text)`: `120 PCS`, `80 SET(S)`, `1 CARTON (S)`, `80 CARTONS (80 SETS)`; units from one list in config.
- `doc_id(text)`: invoice / B/L / contract identifiers, letters + digits + `-` `/` `.`. Read **in context** (after an
  `INVOICE NO` label, in a header cell, in Form D box 10), never searched page-wide. Dates, HS codes and models are excluded by their own recognisers.
- `labels`: synonyms in config (`SAILING ON OR ABOUT` = `SAILING ON/OR ABOUT` = `Sailing On Or About`;
  `CONSIGNEE` with or without `:`/space). The date field kinds are kept separate: invoice / contract / sailing-on-or-about
  (estimate) / Form D departure / B/L on-board (actual). The rules compare estimate vs estimate, or flag estimate vs actual as REVIEW.
- A label followed by a value on the same line, the next line, or the next cell to the right: one helper replaces `_first` / `_after` / ad-hoc splits.

### L3. Field status + richer model (`engine/extract.py`): fixes W3/W4 inputs and W5
- `Field.status`: `READ | UNREADABLE | ABSENT | NOT_FOUND`, plus `method` (which recogniser/layout read it). This replaces the four
  current conventions. `d.get(name)` returns a Field or a typed "missing" with its reason, so a rule never sees a
  bare `None`.
- Packing list: `Package` (carton no./range, GW, CBM, once) → lines (qty, NW, optional GW/CBM). A line without GW/CBM
  **inherits nothing and is not zero**: the carton holds those values. Totals: qty/NW from the lines, GW/CBM from the packages.
- B/L: `cargo_blocks = [ {invoice_ref, ctn, qty, unit, hs, goods} ]` read from the description column (L1). The shipment
  totals stay as today. The per-invoice figures are compared with each invoice.
- Invoice lines: `item_id` + `id_kind` (`model` | `part_no` | `none`) + `desc` + `category`
  (`finished | part | packaging | label | other`, from config keywords). A finished product needs a model and the HS master. A part needs
  a part no. and its own HS strategy (the B/L/Form D heading only). Missing master data stays a **master-data** item, never "not read".
- The existing `items` / `pl_items` dicts stay as a compatibility view during the move.

### L4. Plausibility gate + check runner (`engine/checks.py`): fixes W3, W4
- **Gate**, before the rules: self-consistency tests per document, e.g. printed total vs its own lines, invoice
  vs PL line count, total 0 with non-zero lines, a number recognised from part of a token, a party name that is
  also a label. A failed test marks the field `SUSPECT`. Rules that use a SUSPECT field give **REVIEW_REQUIRED
  ("LDV may have read this wrongly")**, not ERROR. When the gate is unsure it says so; it does not make the problem go away.
- **Check runner**: each rule is registered with the inputs it needs (`@check("BL_VS_PL.ctn", needs=["bl.ctn", "ci*.true_ctn"])`).
  The runner records one result per check and document group:
  `PASS | FAIL (findings) | REVIEW_REQUIRED | NOT_RUN (missing: …) | NOT_APPLICABLE (e.g. no Form D for an FOC invoice)`.
  Existing rule bodies move under it unchanged, and their guard clauses become `needs`.
- **Finding origin**: `document` (a real inconsistency) | `reading` (LDV could not read or trust it) | `master_data` |
  `layout_unsupported`. These are shown apart in the UI and the report.
- **Verdict:** a set cannot be green while a *core* check (list in config: totals, B/L vs PL, invoice refs, Form D
  vs invoice …) is NOT_RUN or REVIEW_REQUIRED. The dashboard then shows "*3 core checks could not run*" with the reasons.

### What is deliberately not proposed
- No new framework (pydantic, ML, OCR). The office PC has no admin rights, and the documents have a text layer. A scanned PDF gets an
  explicit "no text layer: not supported" result instead.
- No separate class per document (Invoice/PackingList/…) right now. `Doc` with typed sub-structures (Package,
  CargoBlock, item id) is enough for 4 document types, and it keeps the session/UI format stable.
- No per-supplier reader forks. A *layout profile* (detected by header keywords) only chooses grammar options
  and table column names, kept in config.

---

## 6. Migration plan

Each phase ends with: `run_unit`, `run_reader`, `ui_smoke`, `typo_sweep`, the baseline **diff explained finding by finding**,
and no baseline update without your approval.

| Phase | Content | Fixes | Baseline expectation |
|---|---|---|---|
| **P1** Check runner + field status (L4 runner, L3 status) | register the 45 rule functions with `needs`; NOT_RUN/NOT_APPLICABLE recorded; "checks not run" in the UI/Excel; core-check verdict | W3 | Findings unchanged; new check list added. The 2 new sets show their lost checks as NOT_RUN. |
| **P2** Value grammar (L2) | numbers, qty+unit, doc ids, label synonyms, date kinds; move every inline number / invoice-no. / carton / sailing pattern onto it | items 1–4, SC FOB | Old 19 sets: findings unchanged (any difference explained). New set: 3 false ERRORs gone. |
| **P3** Cells/columns (L1) + B/L cargo blocks + parties | column-aware B/L description, signature vs marks, consignee label variants, shipper from the labelled block (not "last company"), cross-document agreement as support only | items 5 (party), 6, 8 | New set: PL_HEADER gone; B/L cartons vs both invoices and both invoice refs now **run** (and pass) |
| **P4** Packing-list packages + goods categories + part numbers | Package level, lines with qty+NW only, `item_id`/`id_kind`/`category`; FOC: Form D NOT_APPLICABLE, HS strategy per category | items 5, 7 | New set: LINE_COUNT / CI_PL_QTY / PL_TOTAL gone, and replaced by real line checks that **run and pass** |
| **P5** Plausibility gate + finding origin | suspect readings → REVIEW_REQUIRED; origin shown in the UI/report | W4 | Old sets: no ERROR may turn into REVIEW unless the reading was really wrong (listed one by one) |
| **P6** Vocabulary + docs + tests | technical terms list (`RoHS` …) in config; docs/ARCHITECTURE.md, READING.md, RULES.md (with check statuses); ADRs | item 9 | RoHS false WARNING gone |

Order rationale: P1 first, because it makes every later step measurable (a check that starts running after a fix
shows up as NOT_RUN → PASS/FAIL in the diff). P2 and P3 remove most false alarms. P5 comes last, because it
needs the better readers to tell real document errors from reading errors.

### Tests added per phase (synthetic only, invented values)
- **Grammar unit tests:** every number form listed in the master prompt, partial-token traps (`120.00` must never give `00`), ambiguous
  forms rejected, ids with `-` `/`, label synonyms, date kinds.
- **Synthetic PDFs** built with `tools/mutate_pdf.py` / new builders: FOC parts invoice with one shared carton; B/L with 2 cargo
  blocks and 2 hyphenated invoice refs; marks column beside a signature; consignee label without colon/space; SC
  `FOB PORT,COUNTRY`.
- **Check-status tests:** remove each input field in turn and assert the dependent check reports NOT_RUN (never PASS, never
  disappears). This is the "no silent skip" guarantee.
- **Metamorphic tests:** add whitespace, change line wrap, add a left column, change case of labels → same extracted values and same
  findings.
- **Mutation:** extend `typo_sweep` to the newly read fields, plus a *"blank-out sweep"*: delete a value and expect NOT_RUN or
  VALUE_UNREADABLE, never PASS.
- **Baseline:** the snapshot also stores the check statuses, so a check that stops running is a visible failure.

### Risks and compatibility
| Risk | Mitigation |
|---|---|
| The new grammar reads values the old one skipped, which gives new findings on old sets | every new finding explained in the diff; real ones kept; you approve |
| Column detection on unusual layouts | `Line.text` stays; a reader only uses columns where a header was found, otherwise the old path |
| Session/review.json format | new keys only (checks, origin, status); old sessions keep opening (they show no check list) |
| Office PC (Py 3.15, no admin) | no new dependencies |
| Effort | P1–P2 about 1 session each, P3–P4 about 2 each, P5–P6 about 1 each, with the 2 new sets added to the baseline at the end of P4 |

### Acceptance criteria (from the master prompt, made testable)
1. Every registered check has a status in every run. The blank-out sweep finds 0 silent PASS and 0 vanished checks.
2. The 9 report items are fixed and each has a synthetic regression test.
3. On the new FOC-parts set: 0 false ERRORs. The Form D departure-date finding is still reported (shown as estimate vs Form D date). B/L
   cartons/qty/invoice refs checked per invoice.
4. The 19 existing sets: every finding change is listed and explained. No real error is lost (checked with the earlier synthetic net_*/multi_* sets).
5. No real shipment value in git (grep of unpushed commits before any push, as for v2.0.0).

---

## 7. Decision needed

1. Approve the **incremental plan (P1–P6)** instead of a full rewrite? Or limit the work to P1–P4 for now?
2. Is **REVIEW_REQUIRED** ("LDV may have read this wrongly") the right treatment for suspect readings, or should they stay ERROR
   with an extra note?
3. Which checks are **core** (they block a green verdict when NOT_RUN)? Proposed: totals CI/PL, B/L vs PL, invoice refs, Form D vs
   invoice qty/value/date, HS.
