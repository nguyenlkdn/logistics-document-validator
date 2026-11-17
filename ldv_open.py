"""Right-click "Send to > LDV Checker": check the selected files/folder/zip in the LDV web app.

Starts LDV (Start.bat, in its own window) if it is not running yet, waits until it answers,
then opens the browser at http://localhost:8501/?job=<id>. The app reads the job (the list of
selected paths) and checks them straight away. Standard library only.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import webbrowser
from pathlib import Path

APP = Path(__file__).resolve().parent
PORT = 8501
JOBS = Path(tempfile.gettempdir()) / "ldv_jobs"


def running() -> bool:
    try:
        with socket.create_connection(("localhost", PORT), timeout=1):
            return True
    except OSError:
        return False


def start_app():
    if sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", str(APP / "Start.bat"), "nobrowser"], cwd=APP,
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:                                                 # developer machine
        subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true"], cwd=APP,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def main(args: list[str]) -> int:
    paths = [str(Path(a).resolve()) for a in args if Path(a).exists()]
    if not paths:
        return 1
    JOBS.mkdir(exist_ok=True)
    job = uuid.uuid4().hex
    (JOBS / f"{job}.json").write_text(json.dumps({"paths": paths}), encoding="utf-8")

    if not running():
        start_app()
        # first start may run the update question / library install: wait up to 10 minutes
        deadline = time.time() + 600
        while not running():
            if time.time() > deadline:
                return 1
            time.sleep(1)
        time.sleep(2)                                     # let Streamlit finish starting
    webbrowser.open(f"http://localhost:{PORT}/?job={job}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
