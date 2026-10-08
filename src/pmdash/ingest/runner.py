"""Run all configured fetchers; each fails in isolation."""
from __future__ import annotations

from .. import config
from .github_datasets import FETCHERS


def build_fetchers() -> list:
    cfg = config.load("sources")
    out = []
    for source_id, spec in cfg["sources"].items():
        cls = FETCHERS.get(spec["fetcher"])
        if cls is None:
            continue
        out.append(cls(source_id=source_id, spec=spec, retry=cfg.get("retry", {})))
    return out


def fetch_all(con) -> dict[str, str]:
    results = {}
    for f in build_fetchers():
        try:
            results[f.source_id] = f"ok, {f.run(con)} rows added"
        except Exception as exc:  # noqa: BLE001 - isolation: keep going
            results[f.source_id] = f"FAILED: {exc}"
    return results
