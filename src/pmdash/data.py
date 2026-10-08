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


# Monthly macro inputs for the analogue state. First source with data wins.
MACRO = {
    "cpi": ["us_cpi_fred", "us_cpi_mirror"],
    "yield_10y": ["us_10y_yield_monthly"],
    "real_yield_tips": ["real_yield_10y"],
    "vix": ["vix_fred", "vix_daily_mirror"],
    "brent": ["brent_monthly"],
    "gpr": ["gpr_monthly"],
    "dollar": ["dollar_broad"],
    "fed_rate": ["fed_funds_eff"],          # spliced with the target upper bound below
    "breakeven": ["breakeven_10y"],
    "cftc_gold_mm": ["cftc_gold_mm_net"],
}


def load_macro(con, as_of=None) -> dict[str, pd.Series]:
    """Monthly macro series (Period-indexed). Daily series become monthly averages."""
    out = {}
    for name, ids in MACRO.items():
        for sid in ids:
            s = db.get_series(con, sid, as_of=as_of)
            if s.empty:
                continue
            g = s.groupby(s.index.to_period("M"))
            m = g.last() if name == "fed_rate" else g.mean()
            out[name] = m
            break
    # Fed policy rate: the target upper bound (exact 25 bp steps, from Dec 2008) where it exists,
    # the effective rate (floats inside the range, from 1954) before that. Month-end values.
    tgt = db.get_series(con, "fed_target_upper", as_of=as_of)
    if not tgt.empty:
        t = tgt.groupby(tgt.index.to_period("M")).last()
        out["fed_rate"] = t.combine_first(out["fed_rate"]) if "fed_rate" in out else t
    return out
