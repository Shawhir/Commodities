"""Open the published dashboard in a real browser, let TradingView's widget load, save screenshots.

Used by the workflow job 'screenshot' to confirm that third-party widgets render on the live page.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://shawhir.github.io/Commodities/"
out = Path(sys.argv[1] if len(sys.argv) > 1 else "data/research/screenshots")
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for w, h, name in ((1280, 900, "live_page"), (390, 844, "live_page_phone")):
        p = b.new_page(viewport={"width": w, "height": h})
        p.goto(URL, wait_until="load", timeout=60000)   # streams never go idle
        p.wait_for_timeout(8000)                       # TradingView widget and live quotes
        p.screenshot(path=str(out / f"{name}.png"))
        frames = [f.url for f in p.frames if "tradingview" in f.url]
        print(name, "tradingview frames:", len(frames))
        (out / f"{name}.txt").write_text("\n".join(frames) + "\n")
    b.close()
