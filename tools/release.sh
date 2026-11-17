#!/usr/bin/env bash
# Publish a new LDV release that office PCs pick up through updater.py.
# Usage: tools/release.sh 1.2.0 path/to/notes.md
#   1. set VERSION to the new number, commit everything, run tests/run_baseline.py (ALL PASS)
#   2. run this script
set -euo pipefail
V=${1:?version, e.g. 1.2.0}; NOTES=${2:?release notes file}
cd "$(dirname "$0")/.."
[ -z "$(git status --porcelain)" ] || { echo "Uncommitted changes - commit first."; exit 1; }
[ "$(tr -d '[:space:]' < VERSION)" = "$V" ] || { echo "VERSION file is not $V."; exit 1; }
git tag -a "v$V" -m "LDV v$V"
git push origin main "v$V"
OUT="$(mktemp -d)/LDV-v$V.zip"
git archive --format=zip --prefix=logistics-document-validator/ -o "$OUT" "v$V"
gh release create "v$V" "$OUT" --verify-tag --title "LDV v$V" --notes-file "$NOTES"
