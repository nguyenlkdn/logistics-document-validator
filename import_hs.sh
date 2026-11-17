#!/usr/bin/env bash
# Import the HS master Excel:  ./import_hs.sh "path/to/MA HS.xlsx"   (no argument: show status / re-import if changed)
cd "$(dirname "$(readlink -f "$0")")"
exec .venv/bin/python -m engine.master "$@"
