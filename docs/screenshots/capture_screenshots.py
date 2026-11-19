"""Capture a screenshot of every dashboard page for the backup slides.

Run from the project root:  python docs/screenshots/capture_screenshots.py

Starts the app on the committed sample (EQR_DATA_SOURCE=sample), opens
each page in headless Chrome, waits until the page has finished loading,
and saves full-page PNGs next to this script. Re-run it after any visual
change so the backup slides match the live demo.

Needs Google Chrome (or set CHROME_PATH). It drives Chrome through its
DevTools protocol with the "websockets" package, which Streamlit already
installs, so no extra download is required. Only localhost is contacted.
"""

import asyncio
import base64
import itertools
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(__file__).resolve().parent
APP_PORT = 8599
DEBUG_PORT = 9333
APP_URL = f"http://localhost:{APP_PORT}"
DEFAULT_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_PATH = os.environ.get("CHROME_PATH", DEFAULT_CHROME)

# Slide-friendly width; height grows to fit each page.
VIEW_WIDTH = 1440
VIEW_HEIGHT = 1000
PAGE_TIMEOUT_SECONDS = 60
# Charts finish drawing a moment after their data arrives.
SETTLE_SECONDS = 2

# (file name, path, text that proves the page loaded, button or tab to
# click first or None, text to wait for after clicking, full page?).
# Under Armour FY2015 is the case-study year its M-Score warned.
SHOTS = [
    ("01_screener.png", "/", "match your filters", None, None, True),
    (
        "02_company_verdict.png",
        "/company?cik=1336917&year=2015",
        "checks raised concerns",
        None,
        None,
        True,
    ),
    (
        "03_trace_popup.png",
        "/company?cik=1336917&year=2015",
        "checks raised concerns",
        "Trace to the 10-K",
        "Inputs, as first reported",
        False,
    ),
    (
        "04_trace_tab.png",
        "/company?cik=1336917&year=2015",
        "checks raised concerns",
        "Trace to SEC filing",
        "Inputs, as first reported",
        True,
    ),
    (
        "05_case_hit.png",
        "/case-studies?case=1",
        "earnings manipulation check",
        None,
        None,
        True,
    ),
    (
        "06_case_miss.png",
        "/case-studies?case=2",
        "earnings manipulation check",
        None,
        None,
        True,
    ),
    (
        "07_case_unscored.png",
        "/case-studies?case=3",
        "earnings manipulation check",
        None,
        None,
        True,
    ),
    ("08_about.png", "/about", "Keeping the data current", None, None, True),
]

# True once Streamlit has no spinner or skeleton on screen.
JS_IDLE = """
!document.querySelector('[data-testid="stSpinner"]') &&
!document.querySelector('[data-testid="stSkeleton"]') &&
document.querySelector('[data-testid="stApp"]') !== null
"""
# Height of the scrolling main area (Streamlit scrolls inside it).
JS_HEIGHT = """
Math.max(
  ...[...document.querySelectorAll(
      '[data-testid="stMain"], [data-testid="stAppViewContainer"]')]
     .map(el => el.scrollHeight),
  document.body.scrollHeight)
"""


def wait_for_url(url, timeout):
    """Poll url until it answers, or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.read()
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"{url} did not respond within {timeout}s")


class DevTools:
    """Minimal Chrome DevTools Protocol client over one WebSocket."""

    def __init__(self, socket):
        """Wrap an open WebSocket to a Chrome page target."""
        self.socket = socket
        self.ids = itertools.count(1)

    async def send(self, method, params=None):
        """Send one command and return its result, skipping events."""
        message_id = next(self.ids)
        await self.socket.send(
            json.dumps(
                {"id": message_id, "method": method, "params": params or {}}
            )
        )
        while True:
            reply = json.loads(await self.socket.recv())
            if reply.get("id") == message_id:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})

    async def evaluate(self, expression):
        """Run JavaScript in the page and return its value."""
        result = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        )
        return result.get("result", {}).get("value")

    async def wait_until(self, expression, description):
        """Poll a JavaScript condition until true, or raise TimeoutError."""
        deadline = time.monotonic() + PAGE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if await self.evaluate(expression):
                return
            await asyncio.sleep(0.5)
        # Report what the page did show, so a timeout is easy to diagnose.
        snapshot = await self.evaluate(
            "JSON.stringify({text: document.body.innerText.slice(0, 300),"
            " spinner: !!document.querySelector("
            "'[data-testid=\"stSpinner\"]'), skeleton: !!document."
            "querySelector('[data-testid=\"stSkeleton\"]')})"
        )
        raise TimeoutError(
            f"Timed out waiting for {description}; page state: {snapshot}"
        )

    async def wait_for_text(self, text):
        """Wait until text is on the page and nothing is still loading."""
        has_text = f"document.body.innerText.includes({json.dumps(text)})"
        await self.wait_until(f"({has_text}) && ({JS_IDLE})", repr(text))
        await asyncio.sleep(SETTLE_SECONDS)

    async def click(self, label):
        """Click the first button or tab whose text contains label."""
        clicked = await self.evaluate(
            "(() => { const el = [...document.querySelectorAll("
            "'button, [role=\"tab\"]')].find(e => e.innerText.includes("
            f"{json.dumps(label)})); if (el) {{ el.click(); return true; }}"
            " return false; })()"
        )
        if not clicked:
            raise RuntimeError(f"No button or tab labeled {label!r}")

    async def set_height(self, height):
        """Resize the viewport to VIEW_WIDTH x height."""
        await self.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": VIEW_WIDTH,
                "height": int(height),
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )

    async def screenshot(self, path, full_page):
        """Save a PNG; full_page grows the viewport to the page height."""
        if full_page:
            await self.set_height(await self.evaluate(JS_HEIGHT))
            await asyncio.sleep(SETTLE_SECONDS)
        image = await self.send("Page.captureScreenshot", {"format": "png"})
        path.write_bytes(base64.b64decode(image["data"]))
        await self.set_height(VIEW_HEIGHT)


async def capture_all(page_socket_url):
    """Visit each page in SHOTS and save its screenshot."""
    async with websockets.connect(page_socket_url, max_size=None) as socket:
        tools = DevTools(socket)
        await tools.send("Page.enable")
        await tools.set_height(VIEW_HEIGHT)
        for name, path, ready, action, after, full_page in SHOTS:
            await tools.send("Page.navigate", {"url": APP_URL + path})
            await tools.wait_for_text(ready)
            if action:
                await tools.click(action)
                await tools.wait_for_text(after)
            await tools.screenshot(OUTPUT_DIR / name, full_page)
            print(f"Saved {name}")


def main():
    """Start the app and Chrome, capture every page, then shut down."""
    if not Path(CHROME_PATH).exists():
        sys.exit(f"Chrome not found at {CHROME_PATH}; set CHROME_PATH.")
    app_env = dict(os.environ, EQR_DATA_SOURCE="sample")
    app = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app/app.py",
            "--server.headless",
            "true",
            "--server.port",
            str(APP_PORT),
        ],
        cwd=PROJECT_ROOT,
        env=app_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with tempfile.TemporaryDirectory() as profile_dir:
        chrome = subprocess.Popen(
            [
                CHROME_PATH,
                "--headless=new",
                f"--remote-debugging-port={DEBUG_PORT}",
                f"--user-data-dir={profile_dir}",
                f"--window-size={VIEW_WIDTH},{VIEW_HEIGHT}",
                "--hide-scrollbars",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_url(f"{APP_URL}/_stcore/health", PAGE_TIMEOUT_SECONDS)
            targets = json.loads(
                wait_for_url(
                    f"http://localhost:{DEBUG_PORT}/json/list",
                    PAGE_TIMEOUT_SECONDS,
                )
            )
            page = next(t for t in targets if t["type"] == "page")
            asyncio.run(capture_all(page["webSocketDebuggerUrl"]))
        finally:
            chrome.terminate()
            app.terminate()
            chrome.wait(timeout=10)
            app.wait(timeout=10)


if __name__ == "__main__":
    main()
