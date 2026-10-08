"""Build line series from levels.yaml and run the engine on monthly closes.

Only monthly research data exists so far, so every close is a monthly (and
therefore weekly) close: a break beyond the buffer is confirmed on the same
close. Daily closes arrive with the daily price source (phase 2), and the
same engine then separates broken from confirmed.
"""
from __future__ import annotations

import pandas as pd

from ..indicators.stretch import measures
from ..indicators.trend import momentum_12_1, moving_average
from ..regime.labeller import label_from_config
from .engine import LineSpec, Transition, run_line


def _spec(item: dict, defaults: dict, **overrides) -> LineSpec:
    kw = dict(
        id=item["id"],
        direction=item.get("direction", "both"),
        buffer_pct=item.get("buffer_pct", defaults.get("buffer_pct", 1.0)),
        buffer_abs=item.get("buffer_abs"),
        approach_multiple=item.get("approach_multiple", defaults.get("approach_multiple", 2.0)),
        fail_window=item.get("fail_window_closes", defaults.get("fail_window_closes", 10)),
        severity=item.get("severity", "info"),
        active_from=str(item["active_from"]) if item.get("active_from") else None,
    )
    kw.update(overrides)
    return LineSpec(**kw)


def expanding_percentile(s: pd.Series, since: str) -> pd.Series:
    """Point-in-time percentile of each value among all earlier values since ``since``."""
    s = s[since:].dropna()
    vals = s.to_numpy()
    out = [float((vals[:i] < vals[i]).mean() * 100) if i else float("nan") for i in range(len(vals))]
    return pd.Series(out, index=s.index)


def regime_changes(regime: pd.Series, line_id: str, severity: str, market: str) -> list[Transition]:
    out = []
    prev = None
    for t, r in regime.dropna().items():
        if prev is not None and r != prev:
            out.append(Transition(line_id, t.to_timestamp(how="end").normalize(), prev, r, float("nan"),
                                  float("nan"), severity, severity in ("watch", "important"),
                                  True, True, market, None))
        prev = r
    return out


def evaluate_market(market: str, prices: dict[str, pd.Series], levels_cfg: dict,
                    thresholds: dict, usdchf: pd.Series | None = None,
                    since: str = "1971-08") -> tuple[list[Transition], list[str]]:
    """Run every configured line for ``market`` on monthly closes in each currency.

    ``prices`` maps currency -> monthly Period-indexed close series.
    Returns (transitions, notes about lines that could not be evaluated).
    """
    defaults = levels_cfg.get("defaults", {})
    transitions: list[Transition] = []
    notes: list[str] = []
    for item in levels_cfg.get(market, []):
        kind = item["type"]
        for cur, p in prices.items():
            p = p[since:].dropna()
            idx = p.index.to_timestamp(how="end").normalize()
            closes = pd.Series(p.to_numpy(), index=idx)
            monthly = pd.Series(True, index=idx)
            fw = item.get("fail_window_monthly_closes", defaults.get("fail_window_monthly_closes", 2))
            spec = _spec(item, defaults, market=market, currency=cur, fail_window=fw)
            if kind == "manual_price":
                if cur == "USD":
                    line = float(item["value_usd"])
                elif usdchf is not None:
                    line = (float(item["value_usd"]) * usdchf).reindex(p.index)
                    line.index = idx
                else:
                    continue
            elif kind == "derived_ma":
                ma = moving_average(prices[cur].dropna(), item["window_months"])[since:]
                line = pd.Series(ma.reindex(p.index).to_numpy(), index=idx)
            elif kind == "signal_zero_cross":
                if item.get("signal") != "momentum_12_1":
                    notes.append(f"{item['id']}: signal {item.get('signal')} not implemented")
                    break
                sig = momentum_12_1(prices[cur].dropna()).reindex(p.index)
                closes = pd.Series(sig.to_numpy(), index=idx)
                line = 0.0
                spec.buffer_abs = item.get("buffer_abs", 0.0)
            elif kind == "stretch_percentile":
                m = measures(prices[cur].dropna()[since:])[item["measure"]]
                pct = expanding_percentile(m, since).reindex(p.index)
                closes = pd.Series(pct.to_numpy(), index=idx)
                for thr in item["thresholds"]:
                    s2 = _spec(item, defaults, id=f"{item['id']}_p{thr}", market=market, currency=cur,
                               buffer_abs=item.get("buffer_abs", 0.0), fail_window=fw)
                    transitions += run_line(s2, closes, float(thr), monthly=monthly)
                continue
            elif kind == "regime_change":
                if cur == "USD":   # the regime label is defined on the USD price (section 8)
                    reg = label_from_config(prices[cur].dropna(), thresholds)["regime"][since:]
                    transitions += regime_changes(reg, item["id"], spec.severity, market)
                continue
            else:
                notes.append(f"{item['id']}: type {kind} not implemented yet")
                break
            transitions += run_line(spec, closes, line, monthly=monthly)
    for group, items in levels_cfg.items():
        if group in ("defaults", market) or not isinstance(items, list):
            continue
        if group == "macro":
            for item in items:
                notes.append(f"{item['id']}: needs series {item.get('series')} (not ingested yet)")
    return transitions, notes


def latest_states(transitions: list[Transition]) -> pd.DataFrame:
    if not transitions:
        return pd.DataFrame()
    df = pd.DataFrame([t.to_dict() for t in transitions])
    df = df.sort_values("date")
    return df.groupby(["line_id", "currency"], dropna=False).tail(1).set_index(["line_id", "currency"])
