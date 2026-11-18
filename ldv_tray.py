"""Run LDV in the background: no console window, just an icon in the notification area (next to the clock).

Tray menu: Open LDV (also double-click) · Open reports folder · Check for updates · Quit.
"Check for updates" installs a newer version without asking and restarts LDV.
Started by the "LDV" desktop shortcut, Start.bat / start.sh, or the right-click menu (ldv_open.py passes "nobrowser").
Run it with pythonw.exe so no window appears. Before starting, it checks for updates (Y/N message box).
Streamlit's output goes to %TEMP%\\ldv.log.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

APP = Path(__file__).resolve().parent
PORT = 8501
URL = f"http://localhost:{PORT}"
LOG = Path(tempfile.gettempdir()) / "ldv.log"
WIN = sys.platform == "win32"
TITLE = "LDV - Logistics Document Validator"


def running() -> bool:
    try:
        with socket.create_connection(("localhost", PORT), timeout=1):
            return True
    except OSError:
        return False


def msgbox(text: str, yesno: bool = False) -> bool:
    """Windows message box on top of other windows. Returns True for Yes."""
    if not WIN:
        print(text)
        return False
    import ctypes
    style = (0x04 | 0x20) if yesno else 0x40              # Yes/No + question icon, or info icon
    return ctypes.windll.user32.MessageBoxW(None, text, TITLE, style | 0x40000 | 0x10000) == 6  # topmost, foreground


def icon_image(size: int = 256):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 6, fill=(31, 111, 235))
    font = ImageFont.load_default(size=size * 0.38)
    d.text((size / 2, size / 2), "LDV", font=font, fill="white", anchor="mm")
    return img


def ensure_ico() -> Path:
    ico = APP / "ldv.ico"
    if not ico.exists():
        icon_image().save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
    return ico


def ensure_png() -> Path:
    png = APP / "ldv.png"                                 # Linux app-menu icon
    if not png.exists():
        icon_image(256).save(png)
    return png


def report_dir() -> Path:
    cfg = json.loads((APP / "config.json").read_text(encoding="utf-8"))
    return Path(os.environ.get("LDV_REPORT_DIR") or os.path.expanduser(cfg["report_dir"]))


def open_folder(p: Path):
    p.mkdir(parents=True, exist_ok=True)
    if WIN:
        os.startfile(p)                                   # noqa: S606 - local folder
    else:
        subprocess.Popen(["xdg-open", str(p)])


def restart(args: list[str]):
    """After an update: refresh libraries, then start the new launcher (the caller exits)."""
    if WIN:                                               # visible window: pip may take a minute
        subprocess.run(["cmd", "/c", str(APP / "Setup.bat"), "auto"], cwd=APP,
                       creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        with open(LOG, "a", encoding="utf-8") as log:
            subprocess.run(["bash", str(APP / "setup.sh"), "auto"], cwd=APP, stdout=log, stderr=subprocess.STDOUT)
    args = [a for a in args if a != "updated"] + ["updated"]
    subprocess.Popen([sys.executable, str(APP / "ldv_tray.py"), *args], cwd=APP, start_new_session=not WIN)


def update_first():
    """Ask about a newer version. After an update: refresh libraries, restart the new launcher."""
    import updater
    with open(LOG, "w", encoding="utf-8") as log:
        code = updater.check_and_update(lambda text: msgbox(text, yesno=True), lambda m: print(m, file=log))
    if code == updater.UPDATED:
        restart(sys.argv[1:])
        sys.exit(0)


def update_message(code: int, version: str) -> str:
    import updater
    return {
        updater.UP_TO_DATE: f"LDV {version} is the latest version.\nLDV {version} la phien ban moi nhat.",
        updater.OFFLINE: "Could not check for updates (no internet connection?).\n"
                         "Khong kiem tra duoc cap nhat (khong co mang?).",
        updater.DEV: "This copy is a developer checkout: update it with git pull.\n"
                     "Ban nay la ban phat trien: cap nhat bang git pull.",
    }.get(code, f"Update failed, LDV {version} is kept. Details: {LOG}\n"
                f"Cap nhat that bai, giu ban LDV {version}. Chi tiet: {LOG}")


def main() -> int:
    show = "nobrowser" not in sys.argv
    if running():                                         # already running: just open it
        if show:
            webbrowser.open(URL)
        return 0
    update_first()

    py = Path(sys.executable)
    if WIN and py.name.lower() == "pythonw.exe" and py.with_name("python.exe").exists():
        py = py.with_name("python.exe")
    log = open(LOG, "a", encoding="utf-8")
    proc = subprocess.Popen([str(py), "-m", "streamlit", "run", str(APP / "app.py"), "--server.headless", "true"],
                            cwd=APP, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW if WIN else 0)
    for _ in range(180):
        if running():
            break
        if proc.poll() is not None:
            if running():                                 # another copy won the race: use that one
                if show:
                    webbrowser.open(URL)
                return 0
            msgbox(f"LDV could not start. Details: {LOG}\nLDV khong khoi dong duoc. Chi tiet: {LOG}")
            return 1
        time.sleep(1)
    if show:
        webbrowser.open(URL)
    if "updated" in sys.argv:                             # restarted after an update
        import updater
        v = updater.current_version()
        threading.Thread(target=msgbox, args=(f"LDV was updated to {v}.\nLDV da duoc cap nhat len {v}.",),
                         daemon=True).start()

    try:
        import pystray
    except ImportError:
        msgbox("LDV is running, but the tray icon needs Setup.bat to be run again.\n"
               "LDV dang chay, nhung can chay lai Setup.bat de co bieu tuong.\n\n" + URL)
        proc.wait()
        return 0

    quitting = threading.Event()

    def quit_app(icon, _item=None):
        quitting.set()
        proc.terminate()
        icon.stop()

    def watch(icon):                                      # app stopped by itself: remove the icon
        icon.visible = True
        proc.wait()
        if not quitting.is_set():
            icon.stop()
            msgbox(f"LDV stopped unexpectedly. Details: {LOG}\nLDV da dung bat thuong. Chi tiet: {LOG}")

    checking = threading.Lock()

    def check_update(icon, _item=None):                   # menu: check now, update without asking, restart
        if checking.acquire(blocking=False):
            threading.Thread(target=do_update, args=(icon,), daemon=True).start()

    def do_update(icon):
        import updater
        try:
            with open(LOG, "a", encoding="utf-8") as log:
                code = updater.check_and_update(lambda _text: True, lambda m: print(m, file=log, flush=True))
            if code != updater.UPDATED:
                msgbox(update_message(code, updater.current_version()))
                return
            try:
                icon.notify(f"Restarting LDV {updater.current_version()}... / Dang khoi dong lai LDV...", TITLE)
            except Exception:                             # notifications not supported here
                pass
            quitting.set()
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            restart(["nobrowser"])                        # the open browser tab reconnects by itself
            icon.stop()
        finally:
            checking.release()

    icon = pystray.Icon("LDV", icon_image(64), f"{TITLE} - {URL}", pystray.Menu(
        pystray.MenuItem("Open LDV / Mở LDV", lambda: webbrowser.open(URL), default=True),
        pystray.MenuItem("Open reports folder / Mở thư mục báo cáo", lambda: open_folder(report_dir())),
        pystray.MenuItem("Check for updates / Kiểm tra cập nhật", check_update),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit LDV / Thoát LDV", quit_app)))
    icon.run(setup=watch)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                     # pythonw has no console: show errors in a box
        import traceback
        LOG.write_text(traceback.format_exc(), encoding="utf-8")
        msgbox(f"LDV error. Details: {LOG}\nLDV bi loi. Chi tiet: {LOG}")
        sys.exit(1)
