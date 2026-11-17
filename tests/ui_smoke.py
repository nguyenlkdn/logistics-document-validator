"""Browser smoke test of the whole review workflow (developer tool, not needed on the office PC).

  pip install playwright            # once, in any Python; uses the installed Google Chrome (or: playwright install chromium)
  python tests/ui_smoke.py [--shots DIR] [--headed]

Starts its own LDV on a free port with temporary report and data folders (the PC's history is not touched),
uploads the first test set from tests/baseline, then walks the workflow: upload inventory -> analysis -> dashboard
-> workspace (finding selection, keyboard, search in document) -> cross-check -> findings bulk status -> report
sign-off rules and PDF -> Ctrl+K search -> every page in EN / VI / both -> a 1366x768 window.
Exit code 1 if a step fails or any page shows an exception.
"""
import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "tests" / "baseline"
FAILS = []


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_set(tmp: Path) -> Path | None:
    zips = sorted(BASE.glob("*.zip"))
    if zips:
        return zips[0]
    dirs = sorted(d for d in BASE.iterdir() if d.is_dir()) if BASE.exists() else []
    return Path(shutil.make_archive(str(tmp / dirs[0].name), "zip", dirs[0].parent, dirs[0].name)) if dirs else None


SHOTS = None


def step(name, fn, page):
    try:
        fn()
        n = page.locator("[data-testid=stException]").count()
        assert n == 0, f"{n} exception(s) on the page: " + page.locator("[data-testid=stException]").first.inner_text()[:300].replace("\n", " | ")
        print(f"PASS  {name}")
    except Exception as e:                                  # noqa: BLE001 — report and continue
        FAILS.append(name)
        lines = str(e).splitlines()
        why = [ln.strip() for ln in lines[1:] if any(k in ln for k in ("intercepts", "inert", "not visible", "not stable",
                                                                       "outside", "detached"))][:2]
        print(f"FAIL  {name}: {lines[0][:200]}" + (f" ({'; '.join(why)})" if why else ""))
        if SHOTS:
            page.screenshot(path=str(SHOTS / f"FAIL_{len(FAILS)}.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", help="folder for screenshots")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed: pip install playwright")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="ldv_ui_"))
    zip_path = test_set(tmp)
    if not zip_path:
        print("No test sets in tests/baseline/ (confidential, kept outside git).")
        return 0
    port = free_port()
    env = dict(os.environ, LDV_REPORT_DIR=str(tmp / "reports"), LDV_DATA_DIR=str(tmp / "data"))
    srv = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"), "--server.port", str(port),
                            "--server.headless", "true"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.STDOUT)
    url = f"http://localhost:{port}"
    global SHOTS
    shots = SHOTS = Path(a.shots) if a.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(channel="chrome", headless=not a.headed)
            except Exception:                                # no Chrome: Playwright's own Chromium
                browser = pw.chromium.launch(headless=not a.headed)
            p = browser.new_page(viewport={"width": 1600, "height": 1000})
            run(p, url, zip_path, shots)
            browser.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    print("RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    return 1 if FAILS else 0


def run(p, url, zip_path, shots):
    def wait(t=1.2):
        time.sleep(0.4)
        p.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=180000)
        time.sleep(t)

    def shot(name):
        if shots:
            p.screenshot(path=str(shots / f"{name}.png"))

    def nav(name):
        p.locator("[data-testid=stSidebarNavLink]", has_text=name).first.click()
        wait()

    def lang(code):
        p.locator("section[data-testid=stSidebar] button").filter(has_text=re.compile(f"^{re.escape(code)}$")).click()
        wait()

    p.goto(url)
    wait(3)

    def upload():
        nav("New review")
        p.locator("input[type=file]").set_input_files(str(zip_path))
        wait(3)
        assert p.get_by_text("Ready").count() >= 3, "fewer than 3 documents recognised in the upload inventory"
        shot("01_upload")
        p.get_by_role("button", name="Start analysis").click()
        wait(4)
        assert p.locator(".ldv-verdict").count() >= 1, "no verdict on the dashboard"
        shot("02_dashboard")
    step("upload, inventory, analysis, dashboard verdict", upload, p)

    def workspace():
        nav("Review workspace")
        p.locator("div[class*=st-key-fbtn_] button").first.click()
        wait(2)
        assert p.locator(".ldv-viewer img").count() == 1, "no page image"
        first = p.locator("div[class*=st-key-fbtn_] button[kind=primary]").first.inner_text()
        p.evaluate("document.activeElement && document.activeElement.blur()")
        p.keyboard.press("ArrowDown")
        wait(2)
        second = p.locator("div[class*=st-key-fbtn_] button[kind=primary]").first.inner_text()
        assert first != second, "ArrowDown did not move to the next finding"
        shot("03_workspace")
        p.keyboard.press("Escape")
        wait(1.5)
        assert p.locator("div[class*=st-key-fbtn_] button[kind=primary]").count() == 0, "Esc did not close the panel"
        assert p.locator(".ldv-text span").count() > 10, "no selectable text layer"
    step("workspace: select finding, page shown, ↓ next, Esc closes, text layer", workspace, p)

    def find_in_doc():
        p.locator("input[aria-label='Find in this document']").fill("INVOICE")
        p.keyboard.press("Enter")
        wait(2)
        assert p.get_by_text(re.compile(r"match\(es\) on page|No match in this document")).count() == 1
    step("workspace: find in document", find_in_doc, p)

    def crosscheck():
        nav("Cross-check")
        assert p.locator("table.ldv-xc tbody tr").count() >= 5, "no comparison table"
        p.locator("[data-testid=stExpander] summary", has_text="Where does a value come from?").click()
        wait(1.5)
        assert p.get_by_role("button", name="Open this page").count() >= 1, "no source of the selected value"
        shot("04_crosscheck")
    step("cross-check table", crosscheck, p)

    def todo():
        m = re.search(r"(\d+) still to handle", p.get_by_text(re.compile(r"still to handle")).first.inner_text())
        return int(m.group(1))

    def bulk():
        nav("Findings")
        before = todo()
        box = p.locator("[data-testid=stDataFrame]").first.bounding_box()
        for i in (0, 1):
            p.mouse.click(box["x"] + 16, box["y"] + 36 + 35 * i + 17)
            wait(1)
        assert p.get_by_text(re.compile(r"^2 selected$")).count() == 1, "row selection"
        p.locator("[data-testid=stSelectbox]").last.click()
        p.get_by_role("option", name="Fixed").click()
        wait(1)
        p.get_by_role("button", name="Apply").click()
        wait(1.5)
        assert todo() == before - 2, f"still to handle: {before} -> {todo()}, expected {before - 2}"
        shot("05_findings")
    step("findings: select two, set Fixed", bulk, p)

    def report():
        nav("Report")
        p.get_by_text("Approved with exception", exact=True).click()
        wait(1)
        sign = p.get_by_role("button", name="Sign off")
        assert sign.is_disabled(), "exception accepted without a reason"
        p.locator("textarea").first.fill("UI test exception")
        p.keyboard.press("Tab")
        wait(1)
        assert sign.is_disabled(), "signed without a reviewer name"
        p.locator("input[aria-label='Your name']").fill("UI Tester")
        p.keyboard.press("Tab")
        wait(1)
        sign.click()
        wait(2)
        assert p.get_by_text(re.compile(r"^Approved with exception — ")).count() == 1, "sign-off not shown"
        p.get_by_role("button", name="Create PDF").click()
        wait(4)
        assert p.get_by_text(re.compile(r"^Report created")).count() == 1, "PDF not created"
        shot("06_report")
    step("report: sign-off needs a reason, PDF created", report, p)

    def ctrl_k():
        p.evaluate("document.activeElement && document.activeElement.blur()")
        focus = p.evaluate("document.activeElement.tagName")
        p.keyboard.press("Control+k")
        wait(1.5)
        try:
            try:
                p.wait_for_selector("[role=dialog] input", timeout=15000)
            except Exception:
                dlg = p.locator("[role=dialog]")
                if SHOTS:
                    p.screenshot(path=str(SHOTS / "ctrlk_dialog.png"))
                raise AssertionError(f"no search box after Ctrl+K (focus was on {focus}); dialogs: {dlg.count()}, "
                                     f"text: {dlg.first.inner_text()[:200]!r}" if dlg.count() else "no dialog")
            ship = p.locator(".ldv-ws b").first.inner_text()
            p.locator("[role=dialog] input").first.fill(ship[:8])
            p.keyboard.press("Enter")
            wait(2)
            assert p.locator("[role=dialog] button", has_text=ship).count() >= 1, "shipment not found"
            shot("07_search")
        finally:                                     # never leave the dialog open for the next steps
            p.keyboard.press("Escape")
            wait(1)
    step("Ctrl+K global search finds the shipment", ctrl_k, p)

    def sweep():
        bad = []
        for code in ("VI", "EN + VI", "EN"):
            lang(code)
            links = p.locator("[data-testid=stSidebarNavLink]")
            for i in range(links.count()):
                links.nth(i).click()
                wait(1)
                if p.locator("[data-testid=stException]").count():
                    bad.append(f"{code} page {i + 1}")
        assert not bad, ", ".join(bad)
    step("every page in EN / VI / both without errors", sweep, p)

    def small():
        p.set_viewport_size({"width": 1366, "height": 768})
        nav("Review workspace")
        assert p.locator(".ldv-viewer").count() == 1
        shot("08_workspace_1366")
        for i, name in enumerate(("Dashboard", "Cross-check", "Findings", "Report")):
            nav(name)
            assert p.locator("[data-testid=stException]").count() == 0, name
            shot(f"{9 + i:02d}_{name.lower().replace('-', '')}_1366")
    step("1366x768 window", small, p)


if __name__ == "__main__":
    sys.exit(main())
