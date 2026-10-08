"""Phase 0: re-verify the section 7 snapshot against stored data.

Each brief figure is compared with the value computed from stored monthly data.
Intraday figures (peak, low, drawdown) cannot be checked from monthly averages
and are reported as such, never silently accepted.
"""
from __future__ import annotations

import pandas as pd

from ..indicators.stretch import measures
from ..indicators.trend import ma_signal, momentum_12_1
from ..regime.labeller import label

# (item, brief value, tolerance, kind)
BRIEF = {
    "sep26_avg_usd": 4300, "sep26_avg_chf": 3540, "feb26_avg_usd": 5020,
    "dist_10m_avg": -0.05, "dist_3y_avg": 0.33, "dist_3y_avg_pct": 85,
    "dist_10y_avg": 1.08, "dist_10y_avg_pct": 91, "return_3y": 1.25, "return_3y_pct": 92,
    "return_12m": 0.18, "er": 0.24, "regime": "Sideways", "rule_10m": "Out", "rule_mom": "In",
}


def _pct(s: pd.Series) -> float:
    s = s.dropna()
    return float((s < s.iloc[-1]).mean() * 100)


def check(gold_usd: pd.Series, usdchf: pd.Series, month: str = "2026-09",
          float_start: str = "1971-08") -> pd.DataFrame:
    p = gold_usd.loc[:month]
    fp = p.loc[float_start:]
    m_float = measures(fp)            # windows from floating-era prices only
    m_all = measures(p)
    lab = label(p).iloc[-1]
    peak_month = p.loc["2026-01":month].idxmax()
    computed = {
        "sep26_avg_usd": float(p.iloc[-1]),
        "sep26_avg_chf": float(p.iloc[-1] * usdchf.loc[month]),
        "feb26_avg_usd": float(p.loc[peak_month]),
        "dist_10m_avg": float(m_all["dist_10m_avg"].iloc[-1]),
        "dist_3y_avg": float(m_all["dist_3y_avg"].iloc[-1]),
        "dist_3y_avg_pct": _pct(m_float["dist_3y_avg"]),
        "dist_10y_avg": float(m_all["dist_10y_avg"].iloc[-1]),
        "dist_10y_avg_pct": _pct(m_float["dist_10y_avg"]),
        "return_3y": float(m_all["return_3y"].iloc[-1]),
        "return_3y_pct": _pct(m_float["return_3y"]),
        "return_12m": float(lab["ret"]),
        "er": float(lab["er"]),
        "regime": lab["regime"],
        "rule_10m": "In" if ma_signal(p).iloc[-1] == 1 else "Out",
        "rule_mom": "In" if momentum_12_1(p).iloc[-1] > 0 else "Out",
    }
    tol = {"sep26_avg_usd": 50, "sep26_avg_chf": 50, "feb26_avg_usd": 50,
           "dist_3y_avg_pct": 2, "dist_10y_avg_pct": 2, "return_3y_pct": 2}
    rows = []
    for k, brief in BRIEF.items():
        c = computed[k]
        if isinstance(brief, str):
            ok = c == brief
        else:
            ok = abs(c - brief) <= tol.get(k, 0.01 if abs(brief) < 0.5 else 0.02)
        rows.append({"item": k, "brief": brief, "computed": c, "status": "confirmed" if ok else "differs"})
    rows.append({"item": "feb26_peak_month", "brief": "2026-02", "computed": str(peak_month),
                 "status": "confirmed" if str(peak_month) == "2026-02" else "differs"})
    turn = momentum_turn_estimate(p, 4300)
    acts = str(pd.Period(turn, "M") + 1) if turn else None
    rows.append({"item": "momentum_turns_negative_if_4300_holds", "brief": "Jan to Feb 2027",
                 "computed": f"signal on {turn} close, position changes {acts}" if turn else "not within 12 months",
                 "status": "confirmed" if acts in ("2027-01", "2027-02") else "differs"})
    for k, v in {"peak_intraday_usd": ">5500 (late Jan 2026)", "low_intraday_usd": "3955 (30 Jun 2026)",
                 "drawdown_peak_to_low": "~28%"}.items():
        rows.append({"item": k, "brief": v, "computed": None,
                     "status": "not checkable from monthly averages (needs daily data)"})
    return pd.DataFrame(rows).set_index("item")


def momentum_turn_estimate(gold_usd: pd.Series, hold_price: float, months_ahead: int = 12) -> str | None:
    """First future month in which 12-1 momentum turns negative if price stays at ``hold_price``."""
    p = gold_usd.copy()
    last = p.index[-1]
    for i in range(1, months_ahead + 1):
        p.loc[last + i] = hold_price
        if momentum_12_1(p).iloc[-1] <= 0:
            return str(last + i)
    return None
