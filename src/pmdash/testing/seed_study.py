"""Initial regime study (section 8): reproduce, then write outputs to data/research/."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..indicators.trend import ma_signal, momentum_signal
from ..regime.labeller import episodes, label_from_config
from . import backtest as bt


def monthly_cash(rate_pct: pd.Series | None) -> pd.Series | float:
    """Monthly cash return from an annual % rate series (monthly Period index); 0 where missing."""
    if rate_pct is None or len(rate_pct) == 0:
        return 0.0
    return (rate_pct.astype(float) / 100 / 12)


def month_end_closes(daily_close: pd.Series, last_month: pd.Period | None = None) -> pd.Series:
    """Last daily close of each month (a real, tradeable price, unlike the month's average)."""
    c = daily_close.dropna()
    m = c.groupby(c.index.to_period("M")).last()
    return m.loc[:last_month] if last_month is not None else m


def realistic(gold_avg_usd: pd.Series, close_usd: pd.Series, close_chf: pd.Series, cfg: dict,
              cash: dict | None = None) -> dict:
    """The rules as the dashboard runs them: decided on dollar monthly averages, traded at real
    month-end closes, cash earning 3-month rates, for each way of holding gold (cost per switch)."""
    b = cfg["backtest"]
    start = b.get("realistic_start", "2001-01")
    costs = b.get("costs", {"fund": b["cost_per_switch"]})
    cash = cash or {}
    mom, ma = momentum_signal(gold_avg_usd), ma_signal(gold_avg_usd, 10)
    rules = {"buy_and_hold": pd.Series(1.0, index=gold_avg_usd.index), "momentum_12_1": mom, "ma_10m": ma,
             "both_rules": (mom * ma).where(mom.notna() & ma.notna())}
    end = str(min(close_usd.index[-1], close_chf.index[-1], gold_avg_usd.index[-1]))
    rows = []
    for holding, cost in costs.items():
        for name, sig in rules.items():
            row = {"rule": name, "holding": holding, "cost": cost}
            for cur, px in (("usd", close_usd), ("chf", close_chf)):
                c = monthly_cash(cash.get(cur.upper()))
                res = bt.run(px, sig.reindex(px.index), start, end, cost=cost,
                             cash_ret=c.reindex(px.index).ffill(limit=3).fillna(0.0) if isinstance(c, pd.Series) else c)
                row[f"{cur}_cagr"], row[f"{cur}_max_dd"] = res.cagr(), res.max_drawdown()
                row["switches"], row["months"] = res.n_switches(), len(res.returns)
                row["in_market"] = float(res.position.mean())
            rows.append(row)
    has = {k: v is not None and len(v) > 0 for k, v in cash.items()}
    return {"rows": rows, "window": [start, end], "costs": costs, "holding": b.get("holding", "fund"),
            "cash": {"USD": has.get("USD", False), "CHF": has.get("CHF", False)}}


def run_study(gold_usd: pd.Series, usdchf: pd.Series, cfg: dict, cash: dict | None = None) -> dict:
    """``gold_usd`` and ``usdchf`` are monthly Period-indexed series. ``cash`` (optional) maps
    USD / CHF to annual % cash rates; without it cash earns 0 (the section 8 reproduction)."""
    b = cfg["backtest"]
    start, cost = b["start"], b["cost_per_switch"]
    labels = label_from_config(gold_usd, cfg)
    regime = labels["regime"]

    gold_chf = (gold_usd * usdchf).dropna()
    mom = momentum_signal(gold_usd)
    ma = ma_signal(gold_usd, 10)
    ones = pd.Series(1.0, index=gold_usd.index)
    chop = bt.chop_filtered_signal(mom, regime, start, b.get("chop_filter_label_lag_months", 1))

    rules = {"buy_and_hold": ones, "momentum_12_1": mom, "ma_10m": ma, "momentum_chop_filter": chop}
    rows = []
    results = {}
    cash = cash or {}
    c_usd, c_chf = monthly_cash(cash.get("USD")), monthly_cash(cash.get("CHF"))
    for name, sig in rules.items():
        usd = bt.run(gold_usd, sig, start, cost=cost, cash_ret=c_usd)
        chf = bt.run(gold_chf, sig, start, cost=cost, cash_ret=c_chf)
        results[name] = (usd, chf)
        rows.append({
            "rule": name,
            "usd_cagr": usd.cagr(), "usd_max_dd": usd.max_drawdown(),
            "chf_cagr": chf.cagr(), "chf_max_dd": chf.max_drawdown(),
            "switches": usd.n_switches(), "months": len(usd.returns),
        })
    summary = pd.DataFrame(rows).set_index("rule")

    per_reg = bt.per_regime(results["momentum_12_1"][0], results["buy_and_hold"][0], regime)

    float_start = cfg.get("float_start", "1971-08")
    shares = regime[float_start:].value_counts(normalize=True)
    r = cfg["regime"]
    eps = episodes(regime[float_start:], min_months=r["sideways_episode_min_months"],
                   gap_merge=r["sideways_gap_merge_months"])
    ep_df = pd.DataFrame([{"start": str(e.start), "end": str(e.end), "months": e.months,
                           "sideways_months": e.regime_months} for e in eps])
    return {"labels": labels, "summary": summary, "per_regime": per_reg,
            "regime_shares_since_float": shares, "sideways_episodes": ep_df,
            "window": (start, str(gold_usd.index[-1]))}


def write_outputs(study: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for key in ("summary", "per_regime", "sideways_episodes"):
        p = out_dir / f"regime_study_{key}.csv"
        study[key].to_csv(p, float_format="%.4f")
        paths.append(p)
    lab = study["labels"].copy()
    lab.index = lab.index.astype(str)
    p = out_dir / "regime_labels_monthly.csv"
    lab.to_csv(p, float_format="%.4f", index_label="month")
    paths.append(p)
    return paths
