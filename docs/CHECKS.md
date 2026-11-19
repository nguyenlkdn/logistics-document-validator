# Checks: what LDV verified, and what it could not

Since LDV 2.3 every verification a rule makes is a **check** with its own execution record. A check that cannot run
says why, and it never disappears or passes without its inputs. Code: `engine/checks.py`; tests: `tests/run_checks.py`.
All examples here are invented.

## 1. Check status (one record per check and group)

| Status | Meaning |
|---|---|
| `PASS` | the inputs were read and compared; nothing wrong (MINOR / INFO findings may be attached) |
| `FAIL` | an ERROR finding |
| `REVIEW_REQUIRED` | a WARNING finding, no ERROR |
| `NOT_RUN` | the check could not be made; `reason` says why (table §3) |
| `NOT_APPLICABLE` | **positive evidence** that the check does not apply (the document prints no such section, the contract lists its documents and no Form D, one invoice only …). A field that was not read is never evidence. |

Rules for PASS: every needed input has field status `READ` and at least one comparison was made. An empty list
(no lines read, no P/O numbers) never passes. When a check found an error but some inputs were missing, it is `FAIL`
and the record notes `incomplete`.

**Groups.** One invoice: group `inv1` plus `shipment`. Several invoices under one B/L: `inv1`, `inv2` … (in the
order of the files; two invoices with the same number keep separate groups) and `shipment` for the B/L totals,
the B/L invoice list and the pairing of contracts / Form D to invoices. A document-scope check (e.g. the page
headers of one invoice file) has one record per document.

## 2. Field status (separate from check status)

| Field status | From the reader |
|---|---|
| `READ` | a value was read |
| `UNREADABLE` | printed at its label but not understood (e.g. a date `21-NOV-2O26`) |
| `ABSENT` | not printed on this layout at all (the reader's `absent` list) |
| `NOT_FOUND` | expected, not found |
| `SUSPECT` | reserved for P5 (plausibility gate); never set in 2.3 |

`field_state(doc, name)` returns the Field or a `Missing(name, status)` that has no value, so a missing field can
never become zero. In 2.3 the status is derived from the readers' existing conventions; no reader was changed.

## 3. NOT_RUN reasons

| Code | Category | Meaning |
|---|---|---|
| `document_missing` | package | the document this check needs is not in the package (it is required: B/L, invoice; a Form D when the contract asks for one or a Form D names the invoice) |
| `requirement_unknown` | package | no document says whether a contract / Form D is required for this invoice (FOC exempts nothing in 2.3) |
| `field_not_found` / `field_unreadable` / `field_absent_required` | reading | an input was not found / not understood / not printed |
| `items_not_read` / `items_not_comparable` | reading | goods lines not read / lines cannot be paired one to one |
| `too_few_values` | reading | fewer than two documents gave a value although another prints it |
| `master_data_missing` | master data | the HS master list (or the city list) has no entry; fix the data, not the document |
| `blocked_by` | dependency | another check already reports this difference (e.g. Form D item models when the item counts differ) |
| `scope_unsupported` | system | LDV does not make this check for this kind of package (container count with several invoices) |
| `internal_error` | system | the rule failed (exception isolated, traceback in `diagnostics.log` of the report folder) |
| `not_reported` | system | safety net: the check left no record (an LDV fault; the tests fail on it) |

EN / VI texts: `config.json "check_reasons"`; check names: `config.json "checks"`.

## 4. Verdict

| Verdict | When |
|---|---|
| **RED: DOCUMENT ERROR** | an open ERROR finding (core check or not) |
| **AMBER: INCOMPLETE / REVIEW** | no open error, but a **core** check is `NOT_RUN` or `REVIEW_REQUIRED` |
| **GREEN: VERIFIED** | every applicable core check `PASS` (`NOT_APPLICABLE` does not block) |

The core list is `config.json "core_checks"` (52 checks): CI/PL quantity, weight and CBM, B/L totals, B/L invoice
references and cargo quantity, contract terms, Form D against the shipment, HS classification, shipper / consignee.
Non-core NOT_RUN checks do not change the verdict, but they are shown (Dashboard tile, Checks page, Excel sheet).

**Reviewer decisions** stay in `history.db` (marks + `mark_log`: who, when, from → to, note). The check records
in `review.json` are never changed. The *effective* verdict on screen is computed from both: a check whose findings
the reviewer closed no longer counts as FAIL; a check `blocked_by` a closed one follows it; a closed FAIL whose
inputs were incomplete becomes NOT_RUN again. **Sign-off:** plain approval only on GREEN; otherwise an exception
with a reason (who / when / reason stored in `signoff`).

## 5. Adding or changing a rule

1. In the rule function, one check context per check:
   ```python
   ck = begin("MY_CHECK", out)            # document-scope: begin("MY_CHECK", out, doc)
   a = ck.need(ci, "field")               # records READ / NOT_FOUND / UNREADABLE / ABSENT
   if a:
       ck.compared()
       if a.value != expected:
           ck.add(Finding(...))           # instead of out.append(...)
   ck.end()
   ```
   `need(..., absent_ok=True)` / `need(..., trace=regex)` make the check NOT_APPLICABLE when the document shows no
   trace of the field; use them only with independent evidence. `ck.na(...)`, `ck.not_run(reason, ...)`,
   `ck.blocked(other_id)` record the other outcomes.
2. Add a `CheckDef` row in `engine/checks.py` (scope, documents, `needs`, finding keys) and a name in
   `config.json "checks"`; add the id to `core_checks` if it belongs in the verdict.
3. Call the rule through `_call()` (exception isolation).
4. `tests/run_checks.py` (and `--local`): closure, declared inputs, blank-out sweep must stay ALL PASS.

## 6. Known limits (2.3)

- Applicability of a contract / Form D comes only from the documents in the package; there is no rule yet for
  invoices that never need them (e.g. FOC parts): they show `requirement_unknown` (AMBER) until P4.
- `CONTAINERS` (B/L container count vs invoice) is not made for packages with several invoices: `scope_unsupported`.
- Field status is derived; readers set it directly from P2 on. `SUSPECT` arrives with P5 after its own design review.
