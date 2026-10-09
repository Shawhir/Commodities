"""Try candidate source URLs and save what comes back (status, size, first bytes).

Used from GitHub Actions, which can reach hosts the development sandbox cannot.
"""
from __future__ import annotations

import csv
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

HEADERS = {"User-Agent": "Mozilla/5.0 (pmdash data probe)", "Accept": "*/*"}


def run(urls: dict[str, str], out_dir: Path, timeout: int = 25, keep: int = 6000) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("FRED_API_KEY", "")
    rows = []
    for name, url in urls.items():
        real = url.replace("{FRED_API_KEY}", key)
        t0 = time.time()
        status, body, err = None, b"", ""
        try:
            with urllib.request.urlopen(urllib.request.Request(real, headers=HEADERS), timeout=timeout) as r:
                status, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, err = e.code, str(e)
            try:
                body = e.read()
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        text = body[:keep].decode("utf-8", "replace")
        if key:
            text, err = text.replace(key, "***"), err.replace(key, "***")
        (out_dir / f"{name}.txt").write_text(f"URL: {url}\nSTATUS: {status}\nBYTES: {len(body)}\nERROR: {err}\n\n{text}")
        rows.append({"name": name, "status": status, "bytes": len(body), "seconds": round(time.time() - t0, 1),
                     "error": err[:200]})
        print(f"{name}: {status} {len(body)} bytes {err[:120]}", flush=True)
    with open(out_dir / "_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows
