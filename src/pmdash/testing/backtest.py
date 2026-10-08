"""Monthly switching backtest (gold or cash) with per-regime reporting.

Conventions (these reproduce the section 8.3 seed results):
- A signal computed on the close of month t sets the position held during month t+1.
- The window starts in cash; the first entry counts as a switch.
- Each switch costs ``cost`` (0.2%) of equity.
- Cash earns ``cash_ret`` (0 in the seed study; replace with T-bill / SARON).
- CHF results apply the USD signal to CHF-priced returns.
- Per-regime results classify month t+1's return by the regime label at t,
  annualised geometrically.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..regime.labeller import DOWN, SIDEWAYS, UP


@dataclass
class Result:
    returns: pd.Series      # strategy monthly returns in the window
    position: pd.Series     # position held during each month
    switches: pd.Series     # 1 where the position changed entering the month

    @property
    def equity(self) -> pd.Series:
        return (1 + self.returns).cumprod()

    def cagr(self) -> float:
        n_years = len(self.returns) / 12
        return float(self.equity.iloc[-1] ** (1 / n_years) - 1)

    def max_drawdown(self) -> float:
        eq = self.equity
        return float((eq / eq.cummax() - 1).min())

    def n_switches(self) -> int:
        return int(self.switches.sum())


def run(price: pd.Series, signal: pd.Series, start: str, end: str | None = None,
        cost: float = 0.002, cash_ret: pd.Series | float = 0.0) -> Result:
    """``signal`` in [0, 1] at each month close; NaN treated as cash."""
    signal = signal.reindex(price.index)
    ret = price.pct_change()
    pos = signal.shift(1).fillna(0.0)
    window = pos.loc[start:end].index
    prev = pos.shift(1).fillna(0.0)
    prev.loc[window[0]] = 0.0                       # start the window in cash
    sw = (pos - prev).abs()
    cash = cash_ret if isinstance(cash_ret, pd.Series) else pd.Series(cash_ret, index=price.index)
    cash = cash.reindex(price.index).fillna(0.0)
    strat = pos * ret + (1 - pos) * cash - sw * cost
    return Result(strat.loc[window], pos.loc[window], sw.loc[window])


def chop_filtered_signal(base_signal: pd.Series, regime: pd.Series, start: str,
                         label_lag: int = 1) -> pd.Series:
    """Rejected variant: freeze the position while the (lagged) regime is Sideways.

    Kept only as a tested, rejected variant (section 8.3, finding 3).
    """
    lagged = regime.shift(label_lag)
    cur = 0.0
    out = []
    for t in base_signal.index:
        if t < pd.Period(start, "M"):
            out.append(0.0)
            continue
        if lagged.get(t) != SIDEWAYS and not pd.isna(base_signal.get(t)):
            cur = float(base_signal[t])
        out.append(cur)
    return pd.Series(out, index=base_signal.index)


def annualised(r: pd.Series) -> float:
    if len(r) == 0:
        return float("nan")
    return float((1 + r).prod() ** (12 / len(r)) - 1)


def per_regime(result: Result, buy_hold: Result, regime: pd.Series) -> pd.DataFrame:
    lab = regime.shift(1).reindex(result.returns.index)
    rows = []
    for reg in (UP, SIDEWAYS, DOWN):
        m = lab == reg
        rows.append({
            "regime": reg,
            "share_of_months": float(m.mean()),
            "months": int(m.sum()),
            "buy_hold_ann": annualised(buy_hold.returns[m]),
            "strategy_ann": annualised(result.returns[m]),
            "strategy_switches": int(result.switches[m].sum()),
        })
    return pd.DataFrame(rows).set_index("regime")


def summary_row(name: str, res: Result) -> dict:
    return {"rule": name, "cagr": res.cagr(), "max_drawdown": res.max_drawdown(),
            "switches": res.n_switches(), "months": len(res.returns)}

