"""Run all configured fetchers; each fails in isolation."""
from __future__ import annotations

from .. import config
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


def fetch_all(con, schedules: set[str] | None = None, ids: set[str] | None = None) -> dict[str, str]:
    results = {}
    for f in build_fetchers(schedules, ids):
        try:
            results[f.source_id] = f"ok, {f.run(con)} rows added"
        except Exception as exc:  # noqa: BLE001 - isolation: keep going
            results[f.source_id] = f"FAILED: {exc}"
    return results
