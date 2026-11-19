# P5 design: plausibility gate ("LDV may have read this wrongly")

Status: **design for owner review. No code written.** (Owner rule: P5 needs its own design review before implementation.)
All examples are invented; the measurements below were made on the local test sets and are only counted.

## 1. Purpose

When LDV misreads a value, the rules compare the misread value and report a document ERROR that is not real. P2–P4 fixed the
readers that caused the 2026-11-19 false errors. P5 is the **safety net for the next unknown layout**: a value whose
reading shows a *detectable* problem is marked `SUSPECT`. A finding built on a SUSPECT input is still shown, but as
"LDV may have read this wrongly: check it", never as a confirmed document error.

## 2. Which fields can become SUSPECT, and why (no thresholds)

Each rule is a yes/no test on how the value was read. None uses a ratio or a tolerance, as you asked.

| Rule | Field becomes SUSPECT when | Why this means "probably misread", not "document wrong" |
|---|---|---|
| **S1 partial number** | the characters right next to a number's text in its line continue the number (a digit, or `.`/`,` followed by a digit) | the number was cut out of a larger number (`357.00` read as `00`). A document cannot print a number that is part of another number |
| **S2 incomplete lines** | the document has goods rows that no reader consumed (the existing "Goods line not read" list) → **every value computed from its lines** (line sums, line counts, `true_total` from lines) | a sum over the lines that were read is not the sum over the lines that are printed |
| **S3 party label inside a name** | a party name (shipper, consignee, exporter, seller, buyer, and their packing-list copies) contains a role label (`CONSIGNEE`, `SHIPPER`, `ACCOUNTEE`, `NOTIFY`, `SHIP TO`, `EXPORTER`, `SELLER`, `BUYER`) | a company name never contains another role's label; the reader took the wrong line |

Not proposed (rejected after review): "line count differs by more than ×N", "a total of 0", "value far from the
other documents". These need thresholds without evidence, or they would also hide real document errors.

## 3. Evidence

| Measurement | Result |
|---|---|
| False alarms today: S1 / S2 / S3 on the 21 local sets with the 2.5.0 readers | **0 / 0 / 0** |
| Recall on the real misreadings: the 2.2.3 readers on the FOC-parts set | S1 flags the 3 cut numbers, S2 the document with 15 unread rows, S3 the shipper that contains "CONSIGNEE". **All 7 false ERRORs of the 2026-11-19 report have a SUSPECT input; the one real ERROR (Form D departure date) has none** |

Tests to add: S1–S3 on invented PDFs; the same 2.2.3 replay as a regression; plus the existing typo sweep and
blank-out sweep (a planted typo must stay CAUGHT; SUSPECT must never turn a FAIL into PASS).

## 4. What a SUSPECT input changes

- **Field:** `status = SUSPECT` (already in `FieldStatus`, unused so far), with the rule and the reason.
- **Check:** a check whose finding uses a SUSPECT input gets status **REVIEW_REQUIRED**, reason `suspect_reading`
  (category *reading*), not FAIL. A check with no finding and a SUSPECT input gets **NOT_RUN** `suspect_reading`:
  it cannot PASS on a value that may be misread.
- **Finding:** kept, with the same text and values, plus a marker "LDV may have read this wrongly: check the
  document" and the reason (e.g. "15 goods lines on this page were not read"). **Severity stays as it is** in the stored
  result. The verdict and the colours use the check status. Nothing is removed.
- **Independent errors stay visible:** a finding is affected only if one of *its own* inputs is SUSPECT. Other
  findings on the same document stay FAIL / RED (on the FOC-parts replay, the Form D date stays RED).
- **Verdict:** REVIEW_REQUIRED on a core check → **AMBER** ("not verified: LDV may have misread …"), never RED and never GREEN.
  An open ERROR from a check *without* SUSPECT inputs still makes the package RED.
- **Reviewer:** can mark such a finding "not an error" (misread) or "fixed" as today; the stored automated result is unchanged.

## 5. Risks

| Risk | Mitigation |
|---|---|
| A real document error hidden as "may be misread" | only S1–S3, each tied to a reading defect that a document cannot cause; the finding stays visible; the package goes AMBER, not GREEN |
| S2 too broad (one unread decorative row makes all sums suspect) | the "unread goods rows" detector already exists and is 0 on all 21 sets; every new layout that triggers it is a reading gap to fix anyway |
| Readers improve and S1–S3 never fire | expected: they are a net. The 2.2.3 replay test keeps proving that they work |

## 6. Decisions for the owner

1. Approve S1, S2 and S3 as the only suspicion rules for now?
2. Approve the effect: REVIEW_REQUIRED (AMBER) with the finding kept and marked "LDV may have read this wrongly"?
3. Should a SUSPECT finding also show as WARNING in the findings list, or keep its ERROR severity with the marker?
   (Recommended: keep ERROR + marker. The colour of the verdict and the check already say "review", and the stored
   result stays comparable with earlier revisions.)
