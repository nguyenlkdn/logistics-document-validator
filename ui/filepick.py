"""Native "open file" dialog for the local app (LDV runs on the user's own PC, so the dialog opens on their desktop).

Windows: the standard dialog through PowerShell (always installed, no admin, no extra library).
Elsewhere: tkinter. Each runs in its own process, so the web server is never blocked by a GUI loop.
Returns the chosen path, "" when the user cancels, or None when no dialog is available (the page then offers an upload).
"""
import os
import subprocess
import sys
from pathlib import Path

_PS = r"""
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false}
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Filter = 'Excel (*.xlsx;*.xlsm)|*.xlsx;*.xlsm|All files (*.*)|*.*'
$d.InitialDirectory = $env:LDV_PICK_DIR
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($d.FileName) }
"""

_TK = r"""
import os, sys, tkinter as tk
from tkinter import filedialog
r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)
p = filedialog.askopenfilename(parent=r, initialdir=os.environ.get('LDV_PICK_DIR') or None,
                               filetypes=[('Excel', '*.xlsx *.xlsm'), ('All files', '*.*')])
sys.stdout.write(p or '')
"""


def pick_excel(start: str = "") -> str | None:
    folder = str(Path(start).parent) if start and Path(start).parent.exists() else str(Path.home() / "Documents")
    env = dict(os.environ, LDV_PICK_DIR=folder)
    try:
        if os.name == "nt":
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", _PS],
                               capture_output=True, text=True, env=env, timeout=600,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            r = subprocess.run([sys.executable, "-c", _TK], capture_output=True, text=True, env=env, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()
