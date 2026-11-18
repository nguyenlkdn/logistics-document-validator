# LDV — Logistics Document Validator (Phase 1, report only)

Local web app for one user on one Windows PC (no admin). Reads a shipment's PDFs (Invoice/PL, Sales Contract,
B/L, Form D), cross-checks them and writes a bilingual (EN/VI) report with page screenshots.
**Documents are never modified. Nothing leaves the PC.** User guide: `GUIDE.html`.

## Layout
```
app.py                 Streamlit UI (localhost:8501)
Setup.bat / Start.bat  Windows: install libraries + shortcuts (no admin) / run the app
ldv_tray.py            background launcher: no console, tray icon (Open / Reports / Quit), update prompt
ldv_open.py            right-click Send to > LDV Checker
updater.py             GitHub Releases updater
.streamlit/config.toml localhost-only, no telemetry
config.json            ports, typo rules, slack days, required fields, EN/VI messages & labels
engine/
  pdftext.py           rebuild text lines with geometry (ignores rotated watermarks)
  extract.py           classify CI/SC/BL/CO + extract fields (each remembers page/position)
  extract_net.py       extra fields for the cross-document / self-check rules (parties, origin, TTL lines, …)
  rules.py             validation rules → Finding (message key, current, suggested, locations)
  rules_net.py         cross-document and self-consistency rules (2.1); full list: docs/RULES.md
  evidence.py          page screenshots: red = wrong value, green = reference
  report.py            report.xlsx (Findings · Extracted data · Not recognised) + report.md
  review_report.py     review report (PDF / Excel / HTML) with reviewer sign-off; saved in <report folder>/reports/
  search.py            global search (Ctrl+K) over the history
  compare.py           cross-check of the same fields across documents (map: config.json "compare")
  session.py           review.json in each report folder: reopen a review without checking again
  history.py           history.db: checks, revisions, reviewer status/notes (kept apart from findings)
  __init__.py          check(inputs) → Result
app.py                 web app entry: sidebar, navigation, right-click jobs
ui/
  i18n.py              every UI string (EN / VI / both)
  state.py             open review, reviewer marks, filters, page switching
  components.py        styling, severity chips, workflow stepper, number tiles, bars
  viewer.py            page viewer: page image + HTML boxes, search, selectable text (PDF is only read)
  views/               dashboard · new_review · review (workspace) · compare · findings · report · history ·
                       reference · settings
docs/REDESIGN.md       UI modernisation: assessment and phased plan
tests/baseline/        test sets + expected.json (confidential, local only, not in git)
tests/run_baseline.py  regression test
```

## Develop / test
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tests/run_baseline.py            # must print ALL PASS
.venv/bin/python tests/run_unit.py                # review features (cross-check, sign-off, reports, search)
.venv/bin/python tests/ui_smoke.py                # optional, browser walk-through (pip install playwright)
.venv/bin/python tools/rules_doc.py               # regenerate docs/RULES.md after adding or changing a rule
.venv/bin/python -m streamlit run app.py
```
After an intended change in results: review the new output manually, then `tests/run_baseline.py --update`.

Reports go to `~/Documents/LDV_reports` (override with env `LDV_REPORT_DIR` or `report_dir` in config.json).

## Linux
`./setup.sh` (once; no root): creates `.venv`, installs the libraries, adds an app-menu entry "LDV" and, for the
GNOME Files app, a right-click entry *Scripts > LDV Checker*. `./start.sh` starts LDV in the background with a tray
icon and opens the browser. Needs Python 3.11+ with venv (`sudo apt install python3-venv` on Debian/Ubuntu).
The tray icon needs an X11 session or a desktop with AppIndicator support. Without one, LDV still runs: open
http://localhost:8501 in the browser.

## HS master list
The company's HS Excel (model → HS code, header row e.g. `Mã NPL/SP` | `Mã HS`) is the reference for HS codes. It is
**not** stored in the repository: `engine/master.py` converts it into `master_hs.json` in the data folder
(`~/Documents/LDV_data`, config `data_dir`, env `LDV_DATA_DIR`) and logs each import in `master_hs_log.jsonl`
(models added / removed / changed). LDV remembers the Excel's path and re-imports it automatically before each check
when the file has changed. Import: page *Reference data* (preview + confirm before replacing), drag the Excel onto `Import-HS.bat`, `./import_hs.sh <file>`,
or `python -m engine.master <file>`.
Rules: `CO_HS_MASTER` (Form D item HS ≠ master), `BL_HS_MASTER` (B/L heading matches no invoice model's master HS),
`HS_MASTER_MISSING` (invoice model not in the list). Models not in the list fall back to Form D vs B/L (`HS_CODE`).
Tests use their own copy `tests/baseline/master_hs.xlsx` (ignored by git), never the PC's real list.

## History
Every check is saved in `history.db` (SQLite) in the report folder. A shipment = its invoice no.; a new check of the
same invoice with changed files = next revision, compared with the previous one (fixed / still there / new).
Each finding can be marked Open, In review, Waiting for supplier, Fixed, Accepted (no action) or Not an error, with a
note; every change is logged in `mark_log` with the reviewer's name (Settings) and time. Marks carry over to later
revisions. The *Review history* page lists, searches and filters all checks, reopens one (from its `review.json`,
no re-analysis) and exports a feedback Excel.

## Right-click menu
`Setup.bat` puts a shortcut "LDV Checker" in the user's SendTo folder and "LDV" on the Desktop (no admin). It runs `ldv_open.py` with the selected paths:
the paths go to a job file in `%TEMP%\ldv_jobs`, LDV is started (`ldv_tray.py nobrowser`) if port 8501 is not answering,
then the browser opens `http://localhost:8501/?job=<id>` and `app.py` checks those files at once.

## Updates and releases
`ldv_tray.py` (started by the Desktop shortcut or `Start.bat`) runs `updater.py` first, asking in a message box: it reads the latest GitHub release of `nguyenlkdn/logistics-document-validator`, compares it with `VERSION`,
asks Y/N, checks the zip's SHA-256 against the digest GitHub reports, replaces only changed files (old copies → `_backup/<version>/`; `.venv`, `wheels`, `*.dll` untouched),
then re-runs `Setup.bat auto` for new libraries. If it is offline or anything fails, the app just starts. It is skipped in a git checkout.
While LDV runs, right-click the tray icon > **Check for updates**: a newer version is installed without asking and LDV restarts
(an open browser tab reconnects); otherwise a message says it is up to date, offline or that the update failed.

Release: bump `VERSION`, commit, run the baseline (ALL PASS), then `tools/release.sh <version> <notes.md>`.
That tags, pushes, builds the zip with `git archive` (tracked files only, so confidential test data can't leak) and publishes it with `gh`.

## Extending
- New typo / port alias / message wording → `config.json` only.
- New rule → function `r_xxx()` in `engine/rules.py`, call it in `validate()`, add message to `config.json`.
- New supplier layout → adjust regexes in `engine/extract.py`, add its zip to `tests/baseline/`, update baseline.

## Offline install (if the office proxy blocks pip)
On a machine with internet:
`pip download -r requirements.txt msvc-runtime -d wheels --platform win_amd64 --python-version 3.15 --only-binary=:all:`
then copy the `wheels` folder into this folder; `Setup.bat` uses it automatically when online install fails.

## Microsoft C++ runtime ("DLL load failed while importing _extra")
pymupdf needs MSVCP140.dll, which Python does not ship. `Setup.bat` installs the pip package `msvc-runtime` into `.venv` (no admin); `engine/_dllpath.py` adds `.venv`, `.venv\Scripts` and `dll\` to the DLL search path before pymupdf loads. Manual fallback: copy MSVCP140.dll, MSVCP140_1.dll, VCRUNTIME140.dll, VCRUNTIME140_1.dll into `dll\`.

## Test sets
Real shipment documents are confidential and are **not** in this (public) repository. Keep them in `tests/baseline/` on your own machine only; see `tests/baseline/README.md`.

## Synthetic test sets
`tools/mutate_pdf.py SPEC.json` copies a test set and changes text in its PDFs (the original text is blanked out
and the new text written in its place), so a rule can be tested on an error the real documents do not contain.
Specs live in `tests/baseline/specs/` (ignored by git, like the documents they are made from). The sets
`Synthetic_net_A/B/C` cover the 2.1 rules; after changing a spec, rebuild the set, review its findings and
approve with `tests/run_baseline.py --update`.
