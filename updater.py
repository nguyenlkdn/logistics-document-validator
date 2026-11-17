"""Check GitHub Releases for a newer LDV version and install it (asks first). Standard library only.

Called by Start.bat before the app starts:
  python updater.py            # check, ask Y/N, update
  python updater.py --yes      # update without asking
Exit codes: 0 = nothing changed (up to date, declined, offline, error), 10 = updated.

Only files shipped in the release zip are replaced. .venv, wheels, DLLs and reports are never touched.
Replaced files are first copied to _backup/<old version>/ so an update can be undone by hand.
"""
import hashlib
import io
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "nguyenlkdn/logistics-document-validator"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
APP = Path(__file__).resolve().parent
KEEP = {".venv", "wheels", "_backup", ".git"}   # folders never overwritten (nor any *.dll)


def current_version() -> str:
    f = APP / "VERSION"
    return f.read_text(encoding="utf-8").strip() if f.exists() else "0"


def parse(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in v.lstrip("vV").split("."))


def _get(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": "LDV-updater", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest() -> dict | None:
    """Latest release as {version, url, sha256, notes}, or None if there is no usable release."""
    rel = json.loads(_get(API, timeout=8))
    asset = next((a for a in rel.get("assets", []) if a["name"].lower().endswith(".zip")), None)
    if not asset:
        return None
    digest = asset.get("digest") or ""
    return dict(version=rel["tag_name"].lstrip("vV"), url=asset["browser_download_url"],
                sha256=digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
                notes=(rel.get("body") or "").strip())


def install(data: bytes, old: str) -> int:
    """Extract the release zip over the app folder. Returns the number of files written."""
    backup = APP / "_backup" / old
    n = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for m in z.infolist():
            parts = Path(m.filename).parts[1:]           # drop the top folder "logistics-document-validator/"
            if not parts or m.is_dir() or parts[0] in KEEP or ".." in parts \
                    or m.filename.lower().endswith(".dll"):
                continue
            target = APP.joinpath(*parts)
            if not target.resolve().is_relative_to(APP):
                continue
            new = z.read(m)
            if target.exists():
                if target.read_bytes() == new:
                    continue
                (backup / Path(*parts)).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup / Path(*parts))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(new)
            n += 1
    return n


def main() -> int:
    if (APP / ".git").exists():
        return 0                                          # developer checkout: update with git instead
    cur = current_version()
    print(f"LDV version {cur} - checking for updates / Dang kiem tra cap nhat...")
    try:
        rel = latest()
    except Exception as e:                                # offline, proxy, GitHub down: just start the app
        print(f"  Update check skipped / Bo qua kiem tra cap nhat ({type(e).__name__})")
        return 0
    if not rel or parse(rel["version"]) <= parse(cur):
        print("  Up to date / Da la ban moi nhat")
        return 0

    print(f"\n  New version {rel['version']} is available / Co phien ban moi {rel['version']}")
    if rel["notes"]:
        print("  " + "\n  ".join(rel["notes"].splitlines()[:15]))
    if "--yes" not in sys.argv:
        try:
            ans = input("\n  Update now? / Cap nhat ngay? [Y/N]: ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes", "c", "co"):
            print("  Skipped / Da bo qua")
            return 0

    try:
        print("  Downloading / Dang tai...")
        data = _get(rel["url"], timeout=120)
        if rel["sha256"] and hashlib.sha256(data).hexdigest() != rel["sha256"]:
            print("  [ERROR] Download is corrupted, not installed / File tai ve bi loi, khong cai dat")
            return 0
        n = install(data, cur)
    except Exception as e:
        print(f"  [ERROR] Update failed, keeping version {cur} / Cap nhat that bai, giu ban {cur}: {e}")
        return 0
    print(f"  Updated to {rel['version']} ({n} files) / Da cap nhat len {rel['version']}")
    return 10


if __name__ == "__main__":
    sys.exit(main())
