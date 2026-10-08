"""Point-in-time state vectors for the analogue finder (section 9.16).

Each measure is computed from trailing data only, and lagged to when it was published:
US CPI for a month is known in the middle of the next month, so the state for month t uses
CPI up to t-1. Measures whose inputs are not ingested are absent; the finder lists them as
dropped and never fills them in.

Proxies (config: thresholds.analogues.proxies):
- real_yield_proxy = 10-year Treasury yield - trailing CPI inflation. TIPS only start in 1997
  (FRED DFII10 from 2003), so this proxy keeps one definition across the whole history.
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
    "cpi_yoy": "US inflation (CPI, y/y)",
    "real_yield_proxy": "real yield (10y minus inflation)",
    "real_yield_proxy_chg_6m": "6-month change in real yield",
    "yield_10y_chg_6m": "6-month change in 10y yield",
    "real_yield_10y": "10-year TIPS real yield",
    "oil_chg_12m": "oil (Brent) 12-month change",
    "vix_pct": "VIX percentile (10y)",
    "gpr_pct": "geopolitical risk percentile (10y)",
    "dollar_chg_6m": "dollar 6-month change",
    "fed_direction": "Fed direction",
}
CATEGORICAL = {"regime", "fed_direction"}
POINTS = {"real_yield_proxy", "real_yield_proxy_chg_6m", "yield_10y_chg_6m", "real_yield_10y"}  # shown in pp


def trailing_pct(s: pd.Series, window: int = 120, min_periods: int = 36) -> pd.Series:
    """Percentile of each value within its own trailing window (point-in-time)."""
    return s.rolling(window, min_periods=min_periods).apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)


def build(gold_usd: pd.Series, usdchf: pd.Series | None = None, macro: dict | None = None) -> pd.DataFrame:
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
    idx = df.index
    # Align each macro series to the monthly index and carry the latest published value forward
    # for up to 2 months (sources publish with a lag; nothing older is carried).
    macro = {k: v.reindex(v.index.union(idx)).ffill(limit=2) for k, v in (macro or {}).items()}
    if "cpi" in macro:
        cpi = macro["cpi"]
        cpi_yoy = (cpi / cpi.shift(12) - 1).shift(1)      # published mid next month
        df["cpi_yoy"] = cpi_yoy.reindex(idx)
        if "yield_10y" in macro:
            ry = macro["yield_10y"] - cpi_yoy * 100
            df["real_yield_proxy"] = ry.reindex(idx)
            df["real_yield_proxy_chg_6m"] = (ry - ry.shift(6)).reindex(idx)
    if "yield_10y" in macro:
        y = macro["yield_10y"]
        df["yield_10y_chg_6m"] = (y - y.shift(6)).reindex(idx)
    if "real_yield_tips" in macro:
        df["real_yield_10y"] = macro["real_yield_tips"].reindex(idx)
    if "brent" in macro:
        b = macro["brent"]
        df["oil_chg_12m"] = (b / b.shift(12) - 1).reindex(idx)
    if "vix" in macro:
        df["vix_pct"] = trailing_pct(macro["vix"]).reindex(idx)
    if "gpr" in macro:
        df["gpr_pct"] = trailing_pct(macro["gpr"]).reindex(idx)
    if "dollar" in macro:
        d = macro["dollar"]
        df["dollar_chg_6m"] = (d / d.shift(6) - 1).reindex(idx)
    if "fed_target" in macro:
        f = macro["fed_target"]
        chg = f - f.shift(6)
        df["fed_direction"] = chg.map(lambda c: None if pd.isna(c) else "hiking" if c > 0 else "cutting" if c < 0 else "on hold").reindex(idx)
    return df
