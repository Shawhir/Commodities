"""What happened after setups like this: counts from history, never a forecast.

For a "setup" (a yes/no condition known at each date, e.g. "rule 1 ON and rule 2 OFF"), this
counts what gold did over the next h periods every time the setup held before, and compares it
with all periods (the baseline). It also runs an honesty test: walking forward through history,
would the setup's past share of rises have described the next outcome better than the plain
baseline share did (Brier score), using only information available at the time?

Overlap: consecutive periods inside one spell share most of their future, so counts are given
both per period and per spell (separate episodes at least h periods apart).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Rate:
    name: str
    horizon: int
    unit: str                  # "months" or "trading days"
    n_periods: int
    n_spells: int
    share_up: float
    median: float
    p25: float
    p75: float
    base_share_up: float
    base_median: float
    base_n: int
    continuation: float | None = None      # share where the move kept the direction of the trend
    extra: dict | None = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def forward_return(p: pd.Series, h: int) -> pd.Series:
    return p.shift(-h) / p - 1


def spells(cond: pd.Series, gap: int) -> int:
    """Number of separate spells: True runs whose starts are at least ``gap`` periods apart."""
    idx = np.flatnonzero(cond.fillna(False).to_numpy())
    if not len(idx):
        return 0
    n, last = 1, idx[0]
    for i in idx[1:]:
        if i - last >= gap:
            n += 1
            last = i
    return n


def rate(p: pd.Series, cond: pd.Series, h: int, name: str, unit: str = "months",
         trend: pd.Series | None = None, start=None) -> Rate:
    """Counts for ``cond`` over horizon ``h``. Only periods with a known outcome are used."""
    fwd = forward_return(p, h)
    if start is not None:
        fwd = fwd[fwd.index >= start]
    cond = cond.reindex(fwd.index).fillna(False).astype(bool)
    known = fwd.notna()
    f = fwd[cond & known]
    base = fwd[known]
    cont = None
    if trend is not None and len(f):
        t = trend.reindex(f.index)
        ok = t.notna() & (t != 0)
        cont = float((np.sign(f[ok]) == np.sign(t[ok])).mean()) if ok.any() else None
    q = f.quantile([0.25, 0.5, 0.75]) if len(f) else pd.Series([np.nan] * 3, index=[0.25, 0.5, 0.75])
    return Rate(name, h, unit, int(len(f)), spells(cond & known, h), float((f > 0).mean()) if len(f) else float("nan"),
                float(q[0.5]), float(q[0.25]), float(q[0.75]), float((base > 0).mean()), float(base.median()),
                int(len(base)), cont)


def honesty_test(p: pd.Series, cond: pd.Series, h: int, start, min_cases: int = 20, min_spells: int = 15,
                 min_brier_gain: float = 0.05, min_hit_gain: float = 0.05) -> dict:
    """Walk forward from ``start``. At each date t where the setup held, the setup's share of
    rises is computed from outcomes already known at t (dates <= t - h), and so is the baseline
    share. Score both against what happened next (Brier score: lower is better)."""
    fwd = forward_return(p, h)
    cond = cond.reindex(p.index).fillna(False).astype(bool)
    up = (fwd > 0).astype(float).where(fwd.notna())
    pos = {d: i for i, d in enumerate(p.index)}
    rows = []
    cum_c = np.cumsum(np.where(cond.to_numpy() & up.notna().to_numpy(), up.fillna(0).to_numpy(), 0))
    cnt_c = np.cumsum((cond & up.notna()).to_numpy().astype(int))
    cum_b = np.cumsum(up.fillna(0).to_numpy())
    cnt_b = np.cumsum(up.notna().to_numpy().astype(int))
    for t in p.index[p.index >= start]:
        if not cond[t] or pd.isna(up[t]):
            continue
        k = pos[t] - h                      # last date whose outcome is known at t
        if k < 0 or cnt_c[k] < min_cases:
            continue
        pc, pb = cum_c[k] / cnt_c[k], cum_b[k] / cnt_b[k]
        y = up[t]
        rows.append({"date": t, "p_setup": pc, "p_base": pb, "up": y})
    if not rows:
        return {"n": 0, "label": "not enough history"}
    df = pd.DataFrame(rows)
    bs_c = float(((df.p_setup - df.up) ** 2).mean())
    bs_b = float(((df.p_base - df.up) ** 2).mean())
    hit_c = float(((df.p_setup > 0.5) == (df.up == 1)).mean())
    hit_b = float(((df.p_base > 0.5) == (df.up == 1)).mean())
    # independent spells among the tested dates: positions at least h periods apart
    tpos = sorted(pos[d] for d in df.date)
    n_sp, last = 0, None
    for i in tpos:
        if last is None or i - last >= h:
            n_sp += 1
            last = i
    # Pass only with a clear margin on both scores and enough independent spells; small edges
    # appear by luck (pure random walks pass the bare "lower and higher" rule surprisingly often).
    useful = n_sp >= min_spells and bs_c <= bs_b * (1 - min_brier_gain) and hit_c >= hit_b + min_hit_gain
    return {"n": int(len(df)), "spells": n_sp,
            "brier_setup": bs_c, "brier_base": bs_b, "hit_setup": hit_c, "hit_base": hit_b,
            "label": "useful" if useful else "context only"}


# --- monthly setups for gold ---------------------------------------------------------------------

def monthly_setups(gold: pd.Series, regime: pd.Series, mom: pd.Series, ma: pd.Series,
                   stretch_pct: pd.Series) -> dict[str, dict]:
    """Today's setup in several ways, each as {plain, tech, cond}. All conditions are known at
    the month's end (point-in-time)."""
    t = gold.index[-1]
    out = {}
    ms, as_ = mom.get(t), ma.get(t)
    onoff = {1.0: "ON", 0.0: "OFF"}
    if not pd.isna(ms) and not pd.isna(as_):
        out["rules"] = {"plain": f"Rule 1 {onoff[ms]} and rule 2 {onoff[as_]}",
                        "tech": f"12-1 momentum signal {int(ms)}, SMA10 signal {int(as_)}",
                        "cond": (mom == ms) & (ma == as_)}
    r = regime.get(t)
    if isinstance(r, str):
        mood = {"Up": "rising steadily", "Sideways": "going sideways", "Down": "falling steadily"}[r]
        out["mood"] = {"plain": f"Market mood {mood}", "tech": f"Regime label {r}", "cond": regime == r}
    s = stretch_pct.get(t)
    if s is not None and not pd.isna(s):
        lo, hi, txt = (90, 101, "in the top 10% of history") if s >= 90 else (50, 90, "above the middle of history") if s >= 50 \
            else (10, 50, "below the middle of history") if s >= 10 else (-1, 10, "in the bottom 10% of history")
        out["stretch"] = {"plain": f"Gold vs its 10-year average {txt}",
                          "tech": f"Distance from SMA120 at the {s:.0f}th expanding percentile (bucket {max(lo, 0)}-{min(hi, 100)})",
                          "cond": (stretch_pct >= lo) & (stretch_pct < hi)}
    if "rules" in out and "mood" in out:
        out["combined"] = {"plain": out["rules"]["plain"] + ", " + out["mood"]["plain"].replace("Market mood ", "mood "),
                           "tech": out["rules"]["tech"] + " AND " + out["mood"]["tech"],
                           "cond": out["rules"]["cond"] & out["mood"]["cond"]}
    return out


def expanding_pct(s: pd.Series) -> pd.Series:
    """Point-in-time percentile of each value among all earlier values."""
    vals = s.to_numpy()
    out = np.full(len(vals), np.nan)
    seen = []
    import bisect
    for i, v in enumerate(vals):
        if np.isnan(v):
            continue
        if seen:
            out[i] = bisect.bisect_left(seen, v) / len(seen) * 100
        bisect.insort(seen, v)
    return pd.Series(out, index=s.index)


def build_monthly(gold: pd.Series, regime: pd.Series, mom: pd.Series, ma: pd.Series, dist_10y: pd.Series,
                  since: str = "1972-08", horizons=(3, 6, 12), test_start: str = "2000-01") -> dict:
    """Counts for today's setups at each horizon, with the honesty test at 12 months."""
    p = gold[since:]
    stretch_pct = expanding_pct(dist_10y[since:])
    trend = (gold.shift(1) / gold.shift(12) - 1)[since:]
    setups = monthly_setups(p, regime[since:], mom[since:], ma[since:], stretch_pct)
    out = []
    for key, s in setups.items():
        rates = [rate(p, s["cond"], h, key, "months", trend=trend).as_dict() for h in horizons]
        test = honesty_test(p, s["cond"], 12, pd.Period(test_start, "M"))
        out.append({"key": key, "plain": s["plain"], "tech": s["tech"], "rates": rates, "test": test})
    return {"as_of": str(gold.index[-1]), "setups": out}


# --- daily technical signals -----------------------------------------------------------------------

def build_technical(df: pd.DataFrame, source: str, horizons=(21, 63), test_start: str = "2010-01-01") -> dict:
    """Today's indicator readings, and for each signal that holds today, what followed it before."""
    from ..indicators import technical as ta
    ind = ta.compute(df)
    p = df["close"]
    trend = p / p.shift(252) - 1
    sig = ta.signals(ind)
    today = ind.index[-1]
    active = []
    for key, s in sig.items():
        c = s["cond"].fillna(False)
        if not bool(c.iloc[-1]):
            continue
        rates = [rate(p, c, h, key, "trading days", trend=trend).as_dict() for h in horizons]
        test = honesty_test(p, c, horizons[-1], pd.Timestamp(test_start), min_cases=60)
        active.append({"key": key, "plain": s["plain"], "tech": s["tech"], "rates": rates, "test": test})
    tail = ind.iloc[-260:]
    return {
        "as_of": str(pd.Timestamp(today).date()), "source": source, "first": str(pd.Timestamp(ind.index[0]).date()),
        "n_days": int(len(ind)), "readings": ta.readings(ind),
        "active": active,
        "chart": {"dates": [str(pd.Timestamp(d).date()) for d in tail.index],
                  "close": [None if pd.isna(v) else round(float(v), 2) for v in tail["close"]],
                  "sma50": [None if pd.isna(v) else round(float(v), 2) for v in tail["sma50"]],
                  "sma200": [None if pd.isna(v) else round(float(v), 2) for v in tail["sma200"]],
                  "upper": [None if pd.isna(v) else round(float(v), 2) for v in tail["bb_upper"]],
                  "lower": [None if pd.isna(v) else round(float(v), 2) for v in tail["bb_lower"]],
                  "rsi": [None if pd.isna(v) else round(float(v), 1) for v in tail["rsi14"]]},
    }


def to_markdown(history: dict | None, technical: dict | None) -> str:
    out = ["## What happened after setups like this", "",
           "Counts from history, not a forecast. Each line: how often gold was higher a year later, against all months.", ""]
    for s in (history or {}).get("setups", []):
        y = s["rates"][-1]
        lab = "passed the honesty test" if s["test"].get("label") == "useful" else "for context only"
        out.append(f"- **{s['plain']}**: higher a year later in {y['share_up']:.0%} of {y['n_periods']} months "
                   f"({y['n_spells']} separate spells), against {y['base_share_up']:.0%} for all months. {lab.capitalize()}.")
    out += ["", "## Technical picture (daily prices)", ""]
    if not technical:
        out.append("- Daily prices not loaded yet.")
    for metal, t in (technical or {}).items():
        out.append(f"**{metal.capitalize()}** (to {t['as_of']}, {t['source']}):")
        out += [f"- {r['name']}: {r['value']}. {r['plain']}" for r in t["readings"]]
        for a in t["active"]:
            r = a["rates"][-1]
            out.append(f"- After \"{a['plain']}\": higher 3 months later in {r['share_up']:.0%} of {r['n_periods']} days "
                       f"({r['n_spells']} spells), against {r['base_share_up']:.0%} for all days. "
                       f"{'Passed the honesty test' if a['test'].get('label') == 'useful' else 'For context only'}.")
        out.append("")
    return "\n".join(out) + "\n"
