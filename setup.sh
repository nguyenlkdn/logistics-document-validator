#!/usr/bin/env bash
# LDV - Logistics Document Validator - Linux setup (no root needed).
# Creates .venv, installs the libraries, adds an "LDV" app-menu entry and a right-click entry
# in the Files app (Nautilus: right-click > Scripts > LDV Checker).
# Usage: ./setup.sh          (run once; safe to run again)
#        ./setup.sh auto     (no questions; used by start.sh and after updates)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
APP="$PWD"
echo "============================================================"
echo " LDV - Logistics Document Validator - Setup"
echo "============================================================"

PY=""
for c in python3.15 python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "[ERROR] Python 3.11 or newer is required (3.15 recommended). Install it with your package manager."
  echo "[LOI] Can Python 3.11 tro len (nen dung 3.15)."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating local environment ($("$PY" --version)) / Dang tao moi truong..."
  if ! "$PY" -m venv .venv; then
    echo "[ERROR] Could not create the environment. On Debian/Ubuntu: sudo apt install python3-venv"
    exit 1
  fi
fi

echo "Installing libraries / Dang cai thu vien (first time takes a few minutes)..."
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt \
  || { [ -d wheels ] && .venv/bin/python -m pip install --disable-pip-version-check -q --no-index --find-links wheels -r requirements.txt; } \
  || { echo "[ERROR] Library install failed. Check internet/proxy."; exit 1; }

echo "Checking the PDF library / Dang kiem tra thu vien PDF..."
.venv/bin/python -c "import engine" || { echo "[ERROR] PDF library cannot start."; exit 1; }

# Streamlit: skip the first-run email question
mkdir -p "$HOME/.streamlit"
[ -f "$HOME/.streamlit/credentials.toml" ] || printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"

# Icon, app-menu entry, Files right-click entry
.venv/bin/python -c "import ldv_tray; ldv_tray.ensure_png()" >/dev/null 2>&1 || true
chmod +x start.sh setup.sh 2>/dev/null || true
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
cat > "$APPS/ldv.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=LDV - Logistics Document Validator
Comment=Check shipment documents (Invoice/PL, Sales Contract, B/L, Form D)
Exec="$APP/.venv/bin/python" "$APP/ldv_tray.py"
Icon=$APP/ldv.png
Terminal=false
Categories=Office;
DESK
NAUT="${XDG_DATA_HOME:-$HOME/.local/share}/nautilus/scripts"
if command -v nautilus >/dev/null 2>&1 || [ -d "$NAUT" ]; then
  mkdir -p "$NAUT"
  cat > "$NAUT/LDV Checker" <<SCRIPT
#!/usr/bin/env bash
# Right-click > Scripts > LDV Checker: check the selected files / folder / zip with LDV
exec "$APP/.venv/bin/python" "$APP/ldv_open.py" "\$@"
SCRIPT
  chmod +x "$NAUT/LDV Checker"
  echo "Right-click menu added: Files app > right-click > Scripts > LDV Checker"
fi
echo "App menu entry added: LDV - Logistics Document Validator"
echo
echo "Setup complete / Cai dat xong. Run ./start.sh or open LDV from the app menu."
