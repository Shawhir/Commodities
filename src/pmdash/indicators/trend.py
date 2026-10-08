"""Trend indicators on monthly closes. All use trailing data only."""
from __future__ import annotations

import pandas as pd


def momentum_12_1(p: pd.Series) -> pd.Series:
    """Return from t-12 to t-1 (skips the latest month)."""
    return p.shift(1) / p.shift(12) - 1


def moving_average(p: pd.Series, window: int = 10) -> pd.Series:
    return p.rolling(window).mean()


def momentum_signal(p: pd.Series) -> pd.Series:
    """1 when 12-1 momentum is positive, else 0 (NaN before enough history)."""
    m = momentum_12_1(p)
    return (m > 0).astype(float).where(m.notna())


def ma_signal(p: pd.Series, window: int = 10) -> pd.Series:
    ma = moving_average(p, window)
    return (p > ma).astype(float).where(ma.notna())


def trend_reading(p: pd.Series, flat_band: float = 0.0) -> str:
    """Up / Flat / Down from the two trend rules at the last close.

    Up when both rules are in, Down when both are out, otherwise Flat.
    """
    mom = momentum_12_1(p).iloc[-1]
    ma = moving_average(p, 10).iloc[-1]
    votes = int(mom > flat_band) + int(p.iloc[-1] > ma)
    return {2: "Up", 1: "Flat", 0: "Down"}[votes]
