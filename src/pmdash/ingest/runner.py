"""Run all configured fetchers; each fails in isolation."""
from __future__ import annotations

import time
from urllib.parse import urlparse

from .. import config
from ..storage import db
from .base import DownloadError
from .github_datasets import FETCHERS


def build_fetchers(schedules: set[str] | None = None, ids: set[str] | None = None) -> list:
    """Fetchers for the given schedules (daily, weekly, on_release) and/or source ids."""
    cfg = config.load("sources")
    out = []
    for source_id, spec in cfg["sources"].items():
        cls = FETCHERS.get(spec["fetcher"])
        if cls is None:
            continue
        if ids is not None and source_id not in ids:
            continue
        if ids is None and schedules is not None and spec.get("schedule", "daily") not in schedules:
            continue
        spec = dict(spec)
        if spec["fetcher"] == "manual":
            spec["path"] = str(config.REPO_ROOT / spec["path"])
        out.append(cls(source_id=source_id, spec=spec, retry=cfg.get("retry", {})))
    return out


def _host(f) -> str:
    url = f.spec.get("url") or getattr(f, "URL", "")
    return urlparse(url).netloc


def fetch_all(con, schedules: set[str] | None = None, ids: set[str] | None = None,
              progress: bool = False) -> dict[str, str]:
    """Run fetchers in isolation. Once a host times out or refuses connections, the remaining
    sources on that host are skipped for this run instead of each waiting through retries."""
    results = {}
    down: dict[str, str] = {}
    for f in build_fetchers(schedules, ids):
        host = _host(f)
        t0 = time.monotonic()
        if host and host in down:
            results[f.source_id] = f"FAILED: skipped, {host} unreachable this run ({down[host]})"
            db.record_health(con, f.source_id, ok=False, error=results[f.source_id][8:])
        else:
            try:
                results[f.source_id] = f"ok, {f.run(con)} rows added"
                if getattr(f, "missing", None):
                    results[f.source_id] += f" (not found: {', '.join(f.missing)})"
            except Exception as exc:  # noqa: BLE001 - isolation: keep going
                results[f.source_id] = f"FAILED: {exc}"
                if isinstance(exc, DownloadError) and exc.host_down and host:
                    down[host] = type(exc.cause).__name__ if exc.cause else "error"
        if progress:
            print(f"{f.source_id}: {results[f.source_id]} [{time.monotonic() - t0:.0f}s]", flush=True)
    return results
