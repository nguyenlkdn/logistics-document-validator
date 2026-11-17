# LDV — Logistics Document Validator (Phase 1, report only)

Local web app for one user on one Windows PC (no admin). Reads a shipment's PDFs (Invoice/PL, Sales Contract,
B/L, Form D), cross-checks them and writes a bilingual (EN/VI) report with page screenshots.
**Documents are never modified. Nothing leaves the PC.** User guide: `GUIDE.html`.

## Layout
```
app.py                 Streamlit UI (localhost:8501)
Setup.bat / Start.bat  Windows: install libraries into .venv (no admin) / run the app
.streamlit/config.toml localhost-only, no telemetry
config.json            ports, typo rules, slack days, required fields, EN/VI messages & labels
engine/
  pdftext.py           rebuild text lines with geometry (ignores rotated watermarks)
  extract.py           classify CI/SC/BL/CO + extract fields (each remembers page/position)
  rules.py             validation rules → Finding (message key, current, suggested, locations)
  evidence.py          page screenshots: red = wrong value, green = reference
  report.py            report.xlsx (Findings · Extracted data · Not recognised) + report.md
  __init__.py          check(inputs) → Result
tests/baseline/        test sets + expected.json (confidential, local only, not in git)
tests/run_baseline.py  regression test
```

## Develop / test
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tests/run_baseline.py            # must print ALL PASS
.venv/bin/python -m streamlit run app.py
```
After an intended change in results: review the new output manually, then `tests/run_baseline.py --update`.

Reports go to `~/Documents/LDV_reports` (override with env `LDV_REPORT_DIR` or `report_dir` in config.json).

## Right-click menu
`Setup.bat` puts a shortcut "LDV Checker" in the user's SendTo folder (no admin). It runs `ldv_open.py` with the selected paths:
the paths go to a job file in `%TEMP%\ldv_jobs`, LDV is started (`Start.bat nobrowser`) if port 8501 is not answering,
then the browser opens `http://localhost:8501/?job=<id>` and `app.py` checks those files at once.

## Updates and releases
`Start.bat` runs `updater.py` first: it reads the latest GitHub release of `nguyenlkdn/logistics-document-validator`, compares it with `VERSION`,
asks Y/N, checks the zip's SHA-256 against the digest GitHub reports, replaces only changed files (old copies → `_backup/<version>/`; `.venv`, `wheels`, `*.dll` untouched),
then re-runs `Setup.bat auto` for new libraries. If it is offline or anything fails, the app just starts. It is skipped in a git checkout.

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
