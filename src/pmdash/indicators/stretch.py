"""Stretch: distance from long averages and 3-year return, as percentiles.

Percentiles "since 1971" are computed on windows built from floating-era
prices only, so a 10-year average is first available in August 1981. This is
the convention that reproduces the section 7 snapshot percentiles.
"""
from __future__ import annotations

import pandas as pd


def measures(p: pd.Series) -> pd.DataFrame:
    """Price-shape measures for each month (trailing windows)."""
    return pd.DataFrame({
        "fall_from_24m_high": p / p.rolling(24).max() - 1,
        "dist_10m_avg": p / p.rolling(10).mean() - 1,
        "dist_3y_avg": p / p.rolling(36).mean() - 1,
        "dist_10y_avg": p / p.rolling(120).mean() - 1,
        "return_3y": p / p.shift(36) - 1,
        "return_12m": p / p.shift(12) - 1,
    })


def percentile_of_last(s: pd.Series) -> float:
    """Share of observations strictly below the last value, in percent."""
    s = s.dropna()
    if s.empty:
        return float("nan")
    return float((s < s.iloc[-1]).mean() * 100)


def stretch_table(p: pd.Series, since: str = "1971-08", rolling_years=(5, 10)) -> pd.DataFrame:
    """Current value, full-history percentile (float era) and rolling-window percentiles."""
    float_p = p[since:]
    m = measures(float_p)
    rows = []
    for col in ["dist_10m_avg", "dist_3y_avg", "dist_10y_avg", "return_3y", "fall_from_24m_high"]:
        s = m[col].dropna()
        row = {"measure": col, "value": s.iloc[-1] if len(s) else float("nan"),
               "pct_since_float": percentile_of_last(s), "n_since_float": len(s)}
        for y in rolling_years:
            w = s.iloc[-12 * y:]
            row[f"pct_{y}y"] = percentile_of_last(w)
            row[f"n_{y}y"] = len(w)
        rows.append(row)
    return pd.DataFrame(rows).set_index("measure")


def rolling_percentile(s: pd.Series, window: int) -> pd.Series:
    """Percentile of each value within its trailing window (point-in-time)."""
    return s.rolling(window, min_periods=window).apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)
