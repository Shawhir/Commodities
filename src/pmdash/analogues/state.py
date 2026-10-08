"""Point-in-time state vectors for the analogue finder (section 9.16).

Each measure is computed from trailing data only. Measures whose inputs are
not ingested yet are simply absent; the finder reports them as dropped and
never fills them with invented values.
"""
from __future__ import annotations

import pandas as pd

from ..indicators.stretch import measures as price_measures
from ..regime.labeller import label

LABELS = {
    "fall_from_24m_high": "fall from 24-month high",
    "dist_10y_avg": "distance from 10-year average",
    "return_3y": "3-year return",
    "dist_10m_avg": "distance from 10-month average",
    "dist_3y_avg": "distance from 3-year average",
    "efficiency_ratio": "efficiency ratio",
    "regime": "regime label",
    "chf_dist_10y_avg": "gold in CHF vs its 10-year average",
    "usdchf_chg_12m": "USD/CHF 12-month change",
}
CATEGORICAL = {"regime", "fed_direction"}


def build(gold_usd: pd.Series, usdchf: pd.Series | None = None) -> pd.DataFrame:
    """Monthly state table indexed by Period. Uses the full price history for windows."""
    m = price_measures(gold_usd)
    lab = label(gold_usd)
    df = pd.DataFrame({
        "fall_from_24m_high": m["fall_from_24m_high"],
        "dist_10y_avg": m["dist_10y_avg"],
        "return_3y": m["return_3y"],
        "dist_10m_avg": m["dist_10m_avg"],
        "dist_3y_avg": m["dist_3y_avg"],
        "efficiency_ratio": lab["er"],
        "regime": lab["regime"],
    })
    if usdchf is not None:
        chf = (gold_usd * usdchf).dropna()
        df["chf_dist_10y_avg"] = (chf / chf.rolling(120).mean() - 1).reindex(df.index)
        df["usdchf_chg_12m"] = (usdchf / usdchf.shift(12) - 1).reindex(df.index)
    return df
