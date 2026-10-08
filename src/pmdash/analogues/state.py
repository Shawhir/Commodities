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
    "fall_from_24m_high": "distance below its 2-year high",
    "dist_10y_avg": "gold vs its 10-year average",
    "return_3y": "change over 3 years",
    "dist_10m_avg": "gold vs its 10-month average",
    "dist_3y_avg": "gold vs its 3-year average",
    "efficiency_ratio": "how steady the move was",
    "regime": "market mood",
    "chf_dist_10y_avg": "gold in francs vs its 10-year average",
    "usdchf_chg_12m": "francs per dollar, change over 12 months",
    "cpi_yoy": "US inflation",
    "real_yield_proxy": "interest rates after inflation",
    "real_yield_proxy_chg_6m": "change in interest rates after inflation over 6 months",
    "yield_10y_chg_6m": "change in the US 10-year interest rate over 6 months",
    "real_yield_10y": "interest rates after inflation (official)",
    "oil_chg_12m": "oil price change over 12 months",
    "vix_pct": "stock market fear (0 to 100 scale)",
    "gpr_pct": "war and political risk (0 to 100 scale)",
    "dollar_chg_6m": "dollar change over 6 months",
    "fed_direction": "US interest rates",
    "breakeven_10y": "expected inflation over 10 years",
    "cftc_mm_pct": "speculators' bets on gold (0 to 100 scale)",
}
TECH_LABELS = {
    "fall_from_24m_high": "P / max(P, 24m) - 1", "dist_10y_avg": "P / SMA120 - 1", "return_3y": "P / P(t-36) - 1",
    "dist_10m_avg": "P / SMA10 - 1", "dist_3y_avg": "P / SMA36 - 1", "efficiency_ratio": "efficiency ratio (12m)",
    "regime": "regime label", "chf_dist_10y_avg": "P_CHF / SMA120_CHF - 1", "usdchf_chg_12m": "USD/CHF 12m change",
    "cpi_yoy": "CPI-U y/y (lag 1m)", "real_yield_proxy": "GS10 - CPI y/y (pp)", "real_yield_proxy_chg_6m": "6m change in real-yield proxy (pp)",
    "yield_10y_chg_6m": "6m change in GS10 (pp)", "real_yield_10y": "DFII10", "oil_chg_12m": "Brent 12m change",
    "vix_pct": "VIX 120m percentile", "gpr_pct": "GPR 120m percentile", "dollar_chg_6m": "DTWEXBGS 6m change",
    "fed_direction": "Fed direction (6m policy-rate change)", "breakeven_10y": "T10YIE", "cftc_mm_pct": "CFTC MM net 36m percentile",
}
FED_PLAIN = {"hiking": "rising", "cutting": "falling", "on hold": "steady"}
MOOD_PLAIN = {"Up": "rising steadily", "Sideways": "going sideways", "Down": "falling steadily"}
CATEGORICAL = {"regime", "fed_direction"}
POINTS = {"real_yield_proxy", "real_yield_proxy_chg_6m", "yield_10y_chg_6m", "real_yield_10y", "breakeven_10y"}  # shown in pp


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
    if "fed_rate" in macro:
        # Effective fed funds rate at month end (from 1954): a 6-month move of 25 bp or more counts
        # as a direction. Month-end, not the monthly average, so a late-month hike is not diluted.
        chg = macro["fed_rate"] - macro["fed_rate"].shift(6)
        df["fed_direction"] = chg.map(lambda c: None if pd.isna(c) else "hiking" if c >= 0.25
                                      else "cutting" if c <= -0.25 else "on hold").reindex(idx)
    if "breakeven" in macro:
        df["breakeven_10y"] = macro["breakeven"].reindex(idx)
    if "cftc_gold_mm" in macro:
        # percentile within the trailing 3 years of monthly means
        df["cftc_mm_pct"] = trailing_pct(macro["cftc_gold_mm"], window=36, min_periods=24).reindex(idx)
    return df
