"""YAML config loading. Config lives in <repo>/config and is versioned in git."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("PMDASH_CONFIG_DIR", REPO_ROOT / "config"))
DATA_DIR = Path(os.environ.get("PMDASH_DATA_DIR", REPO_ROOT / "data"))


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    """Load config/<name>.yaml."""
    with open(CONFIG_DIR / f"{name}.yaml") as fh:
        return yaml.safe_load(fh) or {}


def db_path() -> Path:
    return Path(os.environ.get("PMDASH_DB", DATA_DIR / "pmdash.duckdb"))
