"""Load the stored series the modules work on (point-in-time via ``as_of``)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config
from .ingest.github_datasets import FxMonthly, GoldMonthly
from .storage import db


def load_monthly(con, as_of=None) -> tuple[pd.Series, pd.Series]:
    """Return (gold_usd, usdchf) as monthly Period-indexed series."""
    mk = config.load("markets")
    gold = db.get_monthly(con, mk["markets"]["gold"]["price_series"], as_of=as_of)
    fx = db.get_monthly(con, mk["fx"]["usdchf"], as_of=as_of)
    if gold.empty:
        raise RuntimeError("No gold history stored. Run `pmdash fetch` (or `pmdash import-files`).")
    return gold, fx


def import_files(con, gold_csv: Path, fx_csv: Path) -> dict[str, int]:
    """Load the two monthly datasets from local files (offline / test use)."""
    src = config.load("sources")["sources"]
    out = {}
    for sid, cls, path in (("gold_usd_monthly", GoldMonthly, gold_csv), ("usdchf_monthly", FxMonthly, fx_csv)):
        spec = dict(src[sid], url=f"file:{path}")
        out[sid] = cls(source_id=sid, spec=spec).run(con, raw=Path(path).read_bytes())
    return out
