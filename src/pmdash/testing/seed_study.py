"""Initial regime study (section 8): reproduce, then write outputs to data/research/."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..indicators.trend import ma_signal, momentum_signal
from ..regime.labeller import episodes, label_from_config
from . import backtest as bt


def run_study(gold_usd: pd.Series, usdchf: pd.Series, cfg: dict) -> dict:
    """``gold_usd`` and ``usdchf`` are monthly Period-indexed series."""
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
    for name, sig in rules.items():
        usd = bt.run(gold_usd, sig, start, cost=cost)
        chf = bt.run(gold_chf, sig, start, cost=cost)
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
