# LDV UI modernisation — assessment and plan

Goal: **Upload → Analyze → Review findings → Inspect evidence → Resolve → Report**, with the package status clear
within seconds and any discrepancy reachable in a few clicks. The engine (`engine/`) and its rules are unchanged.

## 1. Current architecture (v1.3.0)

| Layer | What it is |
|---|---|
| Runtime | Streamlit 1.67, local only (`localhost:8501`), started by `ldv_tray.py` / `Start.bat`; one office Windows PC, no admin, Python 3.12–3.15 |
| Engine | `check(paths) → Result`: classify CI/SC/BL/CO → extract fields with page/position → ~25 rule groups → `Finding(key, severity, docs, current, suggested, locs)` |
| Evidence | `evidence.py`: cropped PNG per finding (red = value to check, green = reference) + full-page boxes for the preview |
| Output | report folder per check: `report.xlsx`, `report.md`, `evidence/`, `documents/` (copies of the PDFs) |
| History | `history.db` (SQLite): checks, revisions per invoice no., findings, reviewer marks (open / fixed / not_error / waiting + note) keyed by a stable finding signature |
| Reference data | HS master Excel → `master_hs.json` (+ import log), re-imported automatically when the Excel changes |
| UI (before Phase 1) | one 400-line `app.py`: sidebar holds language, page switch, severity filter, report path, HS import; main page holds upload, results, preview, findings |

**Choice: stay on Streamlit and restructure it.** A React/Node frontend would need a build toolchain and a second
server on a PC without admin rights, and would duplicate the Python engine's data model. Streamlit 1.67 provides
multipage navigation, pills, segmented controls and selectable tables, which covers Phases 1–4. Revisit only if the
PDF viewer in Phase 2 hits a hard limit (see 6).

## 2. UX problems found

1. All controls (language, page, severity filter, HS import, report folder) were crowded into the sidebar.
2. No overview: four big severity numbers, no notion of "open / resolved", no verdict.
3. A past review could not be **opened** again: History showed only a status table, so the findings, preview and
   evidence of an old check were gone unless you checked the files again.
4. No pre-flight view of the upload: you couldn't see what LDV recognised in each file until after the analysis.
5. Findings filters lived in the sidebar, far from the list they filter; you couldn't filter by status or search.
6. The red primary colour (Streamlit default) clashed with "red = error".
7. Severity/status/kind labels were spread between `app.py` and `config.json`, with some UI strings hard-coded.

## 3. Page structure

| Section | Page | Purpose |
|---|---|---|
| Review | **Dashboard** | verdict, package / findings / progress numbers (each clickable), severity distribution, documents table |
| | **New review** | drag-and-drop, file inventory (detected type, pages, size, duplicates, validation) → Start analysis |
| | **Review workspace** | documents · page viewer · finding panel (Phase 2) |
| | **Findings** | all findings in one table, filters, bulk status / comment, Excel (Phase 3) |
| Records | **Review history** | search, open/clear filter, date range; open review, Excel report, folder, quick status edit, feedback Excel |
| Data & settings | **Reference data** | HS master: status, preview + diff + confirm before import, browse/search the list, ignored rows |
| | **Settings** | language, folders, where rules are configured, version |

Sidebar: navigation, the open review (shipment, revision, counts), recent reviews, language (EN / VI / EN + VI),
version. Pages planned for later phases (cross-document comparison, report center) are added when they work. No
placeholder pages.

## 4. Component architecture

```
app.py                  page config, CSS, right-click job intake, st.navigation, sidebar
ui/i18n.py              T{key: (en, vi)}, t() / t1(), severity / kind / message helpers  ← all UI text
ui/state.py             open review (session dict), reviewer marks, counts, per-document rows,
                        filters kept outside widget keys (so the dashboard can set them), go(page)
ui/components.py        CSS, chips, stepper, verdict, tiles (clickable numbers), bars, stats
ui/viewer.py            page viewer: cached page images, overlay boxes, search, text layer, focus scroll, keys
ui/views/*.py           one render() per page; they read state and engine results
engine/session.py       review.json writer/loader (+ fallback for checks saved by ≤ 1.3 from history.db)
```

Data flow: `check()` → report folder + **`review.json`** → `History.record()` → `state.open_check(id)` loads the
session from `review.json` → every page renders from that dict. A fresh check and a reopened check take the same
path. Reviewer decisions stay in `history.db`, separate from the automated findings, which are never overwritten.

`review.json` holds: documents (kind, pages, DRAFT flag, copy path, **extracted fields with page**, line items),
findings (stable sig, severity, message EN/VI, note, current/suggested, page, related documents, evidence crops),
unrecognised items, highlight boxes per document. The extracted fields are already in place for Phase 4.

## 5. Phased plan

| Phase | Scope | Status |
|---|---|---|
| 1 UI foundation | layout + navigation, new review with inventory, dashboard, findings page with filters, history search + reopen, reference data with import preview, centralised strings, blue theme | **done** |
| 2 Review workspace | three panes: document list · page viewer (page nav, fit width / fit page / 100–200 %, find in document, selectable text, original PDF download) · finding panel (found / expected, document, compared with, evidence links to the value and the reference value, what to check, status + note, snapshots). Clicking a finding opens its page and centres its box; ↑/↓ (or k/j) move between findings, Esc closes the panel. Document type can be corrected before analysis | **done** |
| 3 Findings management | Findings page: every finding of the open review, of all shipments (latest revision) or of all revisions; filters for severity, status, document type, rule, date, keyword; multi-select → set status and/or comment in one go, open one in the workspace; Excel export of the filtered list. New statuses *In review* and *Accepted – no action*; reviewer name (Settings, no login) and a per-finding activity trail (`mark_log`) | **done** |
| 4 Cross-document comparison | field × document grid (invoice no., consignee, qty, G.W., N.W., CBM, cartons, vessel, POL/POD, dates, HS) from `review.json` fields; match / mismatch / missing / not applicable; click a cell → page | |
| 5 Report center | preview, PDF + Excel + HTML export, EN / VI / both, include/exclude Info or resolved, automated vs reviewer sections, sign-off with explicit exception note for open errors | |
| 6 Polish & QA | Ctrl+K search, keyboard navigation, accessibility, large packages, UI regression (Playwright) next to the baseline test | |

## 6. Backend gaps (to build before the matching UI)

| Needed for | Missing | Plan |
|---|---|---|
| Correcting a document's type (Phase 2) | — | **done**: `load(path, kind)`, `check(..., kinds=)`; the choice is part of the fingerprint (new revision) and shown as ✎ |
| Highlights for both sides of a finding (Phase 2) | — | **done**: every location (role, page, bbox) stored in `review.json` (`evidence.locations`). Many rules record only the value to check, so the reference box exists only where a rule locates it (4 of 20 boxes in a typical set); adding reference locations to more rules is engine work |
| Fast page viewer (Phase 2) | — | **done**: one page rendered on demand, cached per (file, page, resolution); boxes, search hits and the text layer are HTML overlays |
| Correcting a type after analysis | unrecognised PDFs are not copied into the report folder | copy every input file to `documents/`, then allow "change type and check again" from the workspace |
| Statuses *In review* / *Accepted* (Phase 3) | — | **done**: open, in_review, waiting (to do) · fixed, accepted, not_error (done); old marks keep their meaning |
| Reviewer identity, comment history (Phase 3) | — | **done**: `mark_log` (who, when, from → to, note); the name is set in Settings and saved in the data folder |
| Comparison grid (Phase 4) | fields are not mapped to one vocabulary across CI/SC/BL/CO | field map in `config.json` (field → key per document kind, unit) |
| Report sign-off (Phase 5) | no record of a reviewer conclusion | `signoff` table (check id, result, exception note, who, when) |
| Archive review (history) | — | `archived` flag on `checks`; hidden by default |

## 7. Not changed

- Engine rules, extraction, `report.xlsx` / `report.md`, evidence crops: identical output (baseline: 7 sets ALL PASS).
- `history.db` schema: unchanged; checks from v1.3 reopen through the fallback (no on-page boxes for those).
- Right-click *Send to*, tray launcher, updater, `?job=` hand-off: unchanged behaviour.
- Original PDFs and the HS Excel are only read.
