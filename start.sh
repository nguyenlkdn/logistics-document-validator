#!/usr/bin/env bash
# Start LDV in the background (tray icon: Open / Reports folder / Quit) and open the browser.
# The terminal can be closed afterwards. Log: ${TMPDIR:-/tmp}/ldv.log
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import streamlit, pystray" >/dev/null 2>&1; then
  ./setup.sh auto
fi
setsid -f .venv/bin/python ldv_tray.py "$@" >/dev/null 2>&1 < /dev/null
echo "LDV is starting at http://localhost:8501 (tray icon next to the clock; right-click it to Quit)."
