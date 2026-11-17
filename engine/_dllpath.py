"""Windows only: let pymupdf find the Microsoft C++ runtime (MSVCP140.dll etc.) without admin rights.

Python ships VCRUNTIME140.dll but not MSVCP140.dll, which pymupdf needs. Office PCs without the
"Visual C++ Redistributable" then fail with "DLL load failed while importing _extra".
Setup.bat installs the runtime DLLs into the local .venv (pip package `msvc-runtime`), or they can be
copied by hand into the app's `dll` folder. This module adds those folders to the DLL search path.
Must be imported before pymupdf.
"""
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    _app = Path(__file__).resolve().parents[1]
    _seen = set()
    for _d in (_app / "dll", Path(sys.prefix), Path(sys.prefix) / "Scripts", Path(sys.base_prefix)):
        if _d in _seen:
            continue
        _seen.add(_d)
        if (_d / "msvcp140.dll").exists():
            os.add_dll_directory(str(_d))
            # Some loaders still go through PATH; keep it consistent.
            os.environ["PATH"] = str(_d) + os.pathsep + os.environ.get("PATH", "")
