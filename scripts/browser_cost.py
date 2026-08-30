"""Stretch: what does a browser actually cost?

Fetches one page of https://quotes.toscrape.com/js/ twice -- once with a plain
HTTP request, once with a real browser -- and reports the time and peak memory
of each, plus how many quotes each approach could actually see.

    python scripts/browser_cost.py

The point: on that page the quotes are rendered by JavaScript, so a plain
request sees zero of them and a browser is the only option. On
books.toscrape.com the data is already in the HTML the server sends, so a
browser would only add cost.
"""

from __future__ import annotations

import json
import resource
import sys
import time
from pathlib import Path

import requests

URL = "https://quotes.toscrape.com/js/"
USER_AGENT = "FlyRankInternshipA9/1.0 (+https://github.com/Gamey001/flyrank-polit-scraper)"
OUTPUT = Path("docs/browser-cost.json")


def _peak_mb() -> float:
    """Peak RSS of this process and its children, in MiB (macOS reports bytes)."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round((usage + children) / divisor, 1)


def with_plain_http() -> dict[str, object]:
    from bs4 import BeautifulSoup

    started = time.perf_counter()
    response = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=10)
    response.raise_for_status()
    quotes = BeautifulSoup(response.content, "lxml").select("div.quote span.text")
    return {
        "approach": "plain HTTP (requests + BeautifulSoup)",
        "seconds": round(time.perf_counter() - started, 3),
        "peak_memory_mb": _peak_mb(),
        "bytes_downloaded": len(response.content),
        "quotes_found": len(quotes),
    }


def with_browser() -> dict[str, object]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"approach": "playwright chromium", "skipped": "playwright is not installed"}

    started = time.perf_counter()
    with sync_playwright() as playwright:
        # Playwright ships no Chromium build for macOS 12; fall back to installed Chrome
        try:
            browser = playwright.chromium.launch()
            engine = "playwright chromium"
        except Exception:
            browser = playwright.chromium.launch(channel="chrome")
            engine = "installed google chrome"
        page = browser.new_page(user_agent=USER_AGENT)
        page.goto(URL, wait_until="networkidle", timeout=30_000)
        quotes = page.query_selector_all("div.quote span.text")
        html = page.content()
        result = {
            "approach": f"playwright ({engine})",
            "seconds": round(time.perf_counter() - started, 3),
            "peak_memory_mb": _peak_mb(),
            "bytes_downloaded": len(html.encode()),
            "quotes_found": len(quotes),
        }
        browser.close()
    return result


def main() -> int:
    measurements = [with_plain_http(), with_browser()]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"url": URL, "measurements": measurements}, indent=2) + "\n")
    for measurement in measurements:
        print(json.dumps(measurement))
    print(f"written -> {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
