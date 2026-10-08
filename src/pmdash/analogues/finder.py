"""Analogue finder: "when did it last look like this?" (section 9.16).

Distance: d^2 = (N / W) * sum_g w_g * mean_{m in g} dz_m^2 + penalty^2 * (categorical mismatches),
with N the number of numeric measures used and W the sum of group weights. With a single
group this is plain Euclidean distance over standardised measures (the section 8.4 seed),
and with several groups each group carries its weight regardless of how many measures it has.

Standardisation uses the candidate pool only (months that are eligible matches), so it is
point-in-time whenever the pool ends before the target month.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .state import CATEGORICAL, LABELS


@dataclass
class Match:
    month: pd.Period
    distance: float
    group_distance: dict
    differences: list[str]
    outcomes: dict
    key_moment: str | None = None
    dropped: list[str] = field(default_factory=list)


@dataclass
class FinderResult:
    target: pd.Period
    matches: list[Match]
    used_measures: list[str]
    dropped_measures: list[str]
    spread: dict
    baseline: dict
    disagreement: bool
    key_moments: list[dict]

    def summary(self) -> str:
        s = self.spread
        txt = (f"{s['n']} matches; next-12-month USD outcomes from {s['min']:+.0%} to {s['max']:+.0%}, "
               f"median {s['median']:+.0%}. Unconditional median since 1971: {self.baseline['median']:+.0%} "
               f"(n={self.baseline['n']}).")
        if self.disagreement:
            txt += " The closest matches point in opposite directions; the measures used do not separate them."
        if self.dropped_measures:
            txt += f" Dropped (no data): {', '.join(self.dropped_measures)}."
        return txt


def forward_outcomes(p: pd.Series, horizons=(3, 6, 12, 24)) -> pd.DataFrame:
    out = {f"fwd_{h}m": p.shift(-h) / p - 1 for h in horizons}
    vals = p.to_numpy()
    n = len(vals)
    dd, ru = np.full(n, np.nan), np.full(n, np.nan)
    for i in range(n - 12):
        path = vals[i + 1:i + 13] / vals[i] - 1
        dd[i], ru[i] = min(path.min(), 0.0), max(path.max(), 0.0)
    out["max_dd_12m"] = pd.Series(dd, index=p.index)
    out["max_rise_12m"] = pd.Series(ru, index=p.index)
    return pd.DataFrame(out)


def _describe_diff(measure: str, then, now) -> str:
    name = LABELS.get(measure, measure)
    if measure in CATEGORICAL:
        return f"{name}: {then} then, {now} now"
    if measure == "efficiency_ratio":
        return f"{name}: {then:.2f} then vs {now:.2f} now"
    return f"{name}: {then:+.0%} then vs {now:+.0%} now"


def find(state: pd.DataFrame, target: str | pd.Period, groups: dict[str, list[str]],
         weights: dict[str, float] | None = None, prices: dict[str, pd.Series] | None = None,
         regime: pd.Series | None = None, candidate_start: str = "1975-01",
         exclude_recent: int = 24, collapse: int = 18, top_n: int = 6,
         categorical_penalty: float = 1.0, standardise: str = "zscore",
         key_moments: pd.DataFrame | None = None, baseline_start: str = "1971-08",
         horizons=(3, 6, 12, 24), key_moment_max_gap: int = 6) -> FinderResult:
    target = pd.Period(target, "M")
    weights = weights or {}
    cutoff = target - exclude_recent
    pool = state.loc[pd.Period(candidate_start, "M"):cutoff]
    now = state.loc[target]

    used, dropped, sel = [], [], {}
    for g, ms in groups.items():
        keep = [m for m in ms if m in state.columns and not pd.isna(now.get(m))]
        dropped += [m for m in ms if m not in keep]
        if keep:
            sel[g] = keep
            used += keep
    numeric = [m for m in used if m not in CATEGORICAL]
    cats = [m for m in used if m in CATEGORICAL]

    x = pool[numeric].astype(float)
    t = now[numeric].astype(float)
    if standardise == "rank":
        allv = pd.concat([x, t.to_frame().T])
        r = allv.rank(pct=True)
        z, zt = r.iloc[:-1], r.iloc[-1]
    else:
        mu, sd = x.mean(), x.std(ddof=0)
        z, zt = (x - mu) / sd, (t - mu) / sd
    dz2 = (z - zt) ** 2

    n_num = len(numeric)
    group_d2 = {}
    total = pd.Series(0.0, index=pool.index)
    wsum = pd.Series(0.0, index=pool.index)
    for g, ms in sel.items():
        nm = [m for m in ms if m in numeric]
        if not nm:
            continue
        gd2 = dz2[nm].mean(axis=1, skipna=True)        # missing candidate values: mean of the rest
        group_d2[g] = gd2 * len(nm)
        w = weights.get(g, 1.0)
        ok = gd2.notna()
        total[ok] += w * gd2[ok]
        wsum[ok] += w
    d2 = (n_num / wsum.replace(0, np.nan)) * total
    for c in cats:
        d2 += categorical_penalty ** 2 * (pool[c] != now[c]).astype(float)
    dist = np.sqrt(d2).dropna().sort_values()

    picked: list[tuple[pd.Period, float]] = []
    for m, v in dist.items():
        if all(abs((m - q).n) >= collapse for q, _ in picked):
            picked.append((m, float(v)))
        if len(picked) == top_n:
            break

    prices = prices or {}
    fwd = {cur: forward_outcomes(p, horizons) for cur, p in prices.items()}
    km = key_moments.copy() if key_moments is not None else None
    if km is not None:
        km["month"] = pd.PeriodIndex(pd.to_datetime(km["date"]), freq="M")

    matches = []
    for m, v in picked:
        diffs = sorted(numeric, key=lambda c: -abs((z.loc[m, c] - zt[c])) if not pd.isna(z.loc[m, c]) else 0)
        words = [_describe_diff(c, state.loc[m, c], now[c]) for c in diffs[:2]]
        words += [_describe_diff(c, state.loc[m, c], now[c]) for c in cats if state.loc[m, c] != now[c]]
        outcomes = {}
        for cur, f in fwd.items():
            if m in f.index:
                for col in f.columns:
                    outcomes[f"{col}_{cur.lower()}"] = float(f.loc[m, col])
        if regime is not None and m + 12 in regime.index:
            outcomes["regime_after_12m"] = regime.loc[m + 12]
        label = None
        if km is not None and len(km):
            gap = (km["month"] - m).apply(lambda o: abs(o.n))
            j = gap.idxmin()
            if gap[j] <= key_moment_max_gap:
                label = km.loc[j, "label"] if gap[j] == 0 else f"{km.loc[j, 'label']} ({gap[j]} months away)"
        matches.append(Match(m, v, {g: float(np.sqrt(d.loc[m])) for g, d in group_d2.items()},
                             words, outcomes, label,
                             [c for c in numeric if pd.isna(state.loc[m, c])]))

    key = "fwd_12m_usd"
    vals = [mm.outcomes.get(key) for mm in matches if mm.outcomes.get(key) is not None]
    spread = {"n": len(vals), "min": min(vals, default=np.nan), "median": float(np.median(vals)) if vals else np.nan,
              "max": max(vals, default=np.nan)}
    base = {"n": 0, "median": np.nan, "share_positive": np.nan}
    if "USD" in fwd:
        b = fwd["USD"]["fwd_12m"].loc[pd.Period(baseline_start, "M"):cutoff].dropna()
        base = {"n": int(len(b)), "median": float(b.median()), "share_positive": float((b > 0).mean())}
    disagreement = bool(vals) and min(vals) < 0 < max(vals)

    km_rows = []
    if km is not None:
        for _, r in km.iterrows():
            if r["month"] in d2.index and not pd.isna(d2[r["month"]]):
                km_rows.append({"moment": r["label"], "month": str(r["month"]),
                                "distance": float(np.sqrt(d2[r["month"]]))})
        km_rows.sort(key=lambda r: r["distance"])

    return FinderResult(target, matches, used, dropped, spread, base, disagreement, km_rows)


def out_of_sample(state: pd.DataFrame, gold_usd: pd.Series, groups, start: str = "2000-01",
                  **kw) -> pd.DataFrame:
    """For each month since ``start`` with a known 12-month outcome, run the finder on earlier
    history only and record whether the matched range contained the actual outcome and whether
    the matched median was closer to it than the unconditional median."""
    fwd = forward_outcomes(gold_usd)["fwd_12m"]
    rows = []
    last = gold_usd.index[-1] - 12
    for t in pd.period_range(start, last, freq="M"):
        if t not in state.index:
            continue
        res = find(state, t, groups, prices={"USD": gold_usd}, **kw)
        actual = fwd.get(t)
        if pd.isna(actual) or res.spread["n"] == 0:
            continue
        rows.append({
            "month": str(t), "actual_12m": actual,
            "match_min": res.spread["min"], "match_median": res.spread["median"], "match_max": res.spread["max"],
            "baseline_median": res.baseline["median"],
            "in_range": res.spread["min"] <= actual <= res.spread["max"],
            "median_beats_baseline": abs(res.spread["median"] - actual) < abs(res.baseline["median"] - actual),
            "direction_right": np.sign(res.spread["median"]) == np.sign(actual),
            "baseline_direction_right": np.sign(res.baseline["median"]) == np.sign(actual),
        })
    return pd.DataFrame(rows)


def oos_summary(df: pd.DataFrame) -> dict:
    """Hit rates of the out-of-sample test and the resulting label.

    "useful" requires the matched median to be closer to the actual outcome than the
    unconditional median in most months AND to get the direction right more often.
    """
    out = {
        "months": int(len(df)),
        "in_range": float(df["in_range"].mean()),
        "median_beats_baseline": float(df["median_beats_baseline"].mean()),
        "direction_right": float(df["direction_right"].mean()),
        "baseline_direction_right": float(df["baseline_direction_right"].mean()),
    }
    useful = out["median_beats_baseline"] > 0.5 and out["direction_right"] > out["baseline_direction_right"]
    out["label"] = "useful" if useful else "context only"
    return out
