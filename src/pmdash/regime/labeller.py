"""Regime labeller (section 8.1), trailing data only.

Efficiency ratio = |12-month net change| / sum of |monthly changes|.
Up if ER >= 0.30 and 12-month return >= +10%; Down if ER >= 0.30 and return <= -10%;
otherwise Sideways.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

UP, SIDEWAYS, DOWN = "Up", "Sideways", "Down"


def efficiency_ratio(p: pd.Series, lookback: int = 12) -> pd.Series:
    net = (p - p.shift(lookback)).abs()
    path = p.diff().abs().rolling(lookback).sum()
    return net / path


def label(p: pd.Series, lookback: int = 12, er_min: float = 0.30,
          up_return_min: float = 0.10, down_return_max: float = -0.10) -> pd.DataFrame:
    """Return DataFrame with columns ret, er, regime (None before enough history)."""
    ret = p / p.shift(lookback) - 1
    er = efficiency_ratio(p, lookback)
    reg = pd.Series(SIDEWAYS, index=p.index, dtype=object)
    reg[(er >= er_min) & (ret >= up_return_min)] = UP
    reg[(er >= er_min) & (ret <= down_return_max)] = DOWN
    reg[ret.isna() | er.isna()] = None
    return pd.DataFrame({"ret": ret, "er": er, "regime": reg})


def label_from_config(p: pd.Series, cfg: dict) -> pd.DataFrame:
    r = cfg["regime"]
    return label(p, r["lookback_months"], r["er_min"], r["up_return_min"], r["down_return_max"])


@dataclass(frozen=True)
class Episode:
    start: pd.Period
    end: pd.Period
    months: int
    regime_months: int


def episodes(regime: pd.Series, which: str = SIDEWAYS, min_months: int = 12,
             gap_merge: int = 2) -> list[Episode]:
    """Runs of ``which``, merging gaps of up to ``gap_merge`` months, keeping runs >= ``min_months``."""
    flags = (regime == which).to_numpy()
    idx = regime.index
    runs: list[list[int]] = []
    start = None
    for k, v in enumerate(flags):
        if v and start is None:
            start = k
        elif not v and start is not None:
            runs.append([start, k - 1])
            start = None
    if start is not None:
        runs.append([start, len(flags) - 1])
    merged: list[list[int]] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] - 1 <= gap_merge:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    out = []
    for a, b in merged:
        n = b - a + 1
        if n >= min_months:
            out.append(Episode(idx[a], idx[b], n, int(flags[a:b + 1].sum())))
    return out
