"""Capture a screenshot of every dashboard page for the backup slides.

Run from the project root:
    python docs/screenshots/capture_screenshots.py                # sample
    python docs/screenshots/capture_screenshots.py --source full  # full

Starts the app on the chosen data (default: the committed sample, so
anyone can reproduce the shots from a fresh clone; "full" needs
data/processed/ and saves to docs/screenshots/full/), opens
each page in headless Chrome, waits until the page has finished loading,
and saves full-page PNGs next to this script. Re-run it after any visual
change so the backup slides match the live demo.

Needs Google Chrome (or set CHROME_PATH). It drives Chrome through its
DevTools protocol with the "websockets" package, which Streamlit already
installs, so no extra download is required. Only localhost is contacted:
Chrome is started with every other address blocked (see OFFLINE_FLAGS),
so the shots also prove the pages load without an internet connection.
"""

import argparse
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

# Close-ups of the price chart for the backup slides: (file name, path,
# text that proves the page loaded, heading to scroll to the top). The
# viewport is captured, not the full page, so the chart fills the shot.
CHART_HEADING = "Stock price and 10-K warnings"
CHART_SHOTS = [
    (
        "09_price_chart_company.png",
        "/company?cik=1336917&year=2015",
        "checks raised concerns",
        CHART_HEADING,
    ),
    (
        "10_price_chart_case.png",
        "/case-studies?case=1",
        "earnings manipulation check",
        CHART_HEADING,
    ),
]

# Send every non-localhost request to a closed local port, so a page that
# needed the internet would fail here just as it would on the demo laptop
# with Wi-Fi off. Chrome never sends localhost through a proxy.
OFFLINE_FLAGS = ["--proxy-server=127.0.0.1:9"]

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

    async def scroll_to(self, text):
        """Scroll the first element whose own text is text to the top."""
        found = await self.evaluate(
            "(() => { const el = [...document.querySelectorAll('p, strong,"
            " h1, h2, h3')].find(e => e.innerText.trim() === "
            f"{json.dumps(text)}); if (el) {{ el.scrollIntoView("
            "{block: 'start'}); return true; } return false; })()"
        )
        if not found:
            raise RuntimeError(f"No heading {text!r} to scroll to")
        await asyncio.sleep(SETTLE_SECONDS)

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


async def capture_all(page_socket_url, output_dir):
    """Visit each page in SHOTS and save its screenshot in output_dir."""
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
            await tools.screenshot(output_dir / name, full_page)
            print(f"Saved {name}")
        for name, path, ready, heading in CHART_SHOTS:
            await tools.send("Page.navigate", {"url": APP_URL + path})
            await tools.wait_for_text(ready)
            await tools.scroll_to(heading)
            await tools.screenshot(output_dir / name, full_page=False)
            print(f"Saved {name}")


def main(argv=None):
    """Start the app and Chrome, capture every page, then shut down."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        choices=["sample", "full"],
        default="sample",
        help="data to show (full needs data/processed/)",
    )
    args = parser.parse_args(argv)
    # Full-data shots go in their own folder so the committed sample
    # shots stay reproducible from a fresh clone.
    output_dir = OUTPUT_DIR if args.source == "sample" else OUTPUT_DIR / "full"
    output_dir.mkdir(exist_ok=True)
    if not Path(CHROME_PATH).exists():
        sys.exit(f"Chrome not found at {CHROME_PATH}; set CHROME_PATH.")
    app_env = dict(os.environ, EQR_DATA_SOURCE=args.source)
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
                *OFFLINE_FLAGS,
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
            asyncio.run(capture_all(page["webSocketDebuggerUrl"], output_dir))
        finally:
            chrome.terminate()
            app.terminate()
            chrome.wait(timeout=10)
            app.wait(timeout=10)


if __name__ == "__main__":
    main()
