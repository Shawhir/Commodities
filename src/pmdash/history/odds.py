"""Weighed-up odds: rising, sideways or falling over the next 12 months.

The owner asked (8 October 2026) for one measured probability that weighs the statistics, the news
and the technicals together. This module does that as honestly as the data allows:

1. One model (multinomial logistic regression with strong L2 shrinkage) weighs every measure we
   hold at a month's end: trend, stretch, rates, the Fed, the dollar, inflation, oil, geopolitical
   risk (the only news-like input so far), equity fear, speculative positioning, the franc and
   short-term price momentum. Outcome classes follow the regime thresholds: rising if the next 12
   months return at least +10%, falling if -10% or worse, otherwise sideways.
2. It is tested walk-forward: for every month since 2000 it is refitted only on months whose
   12-month outcome was already known, standardised on that training window alone.
3. "Measured": the shown odds blend the model with gold's normal odds (class frequencies so far).
   The blend weight is the one that would have scored best on the walk-forward test up to now,
   so a model that has not beaten the normal odds is pulled back to them.
4. It reports which measures push towards rising and which towards falling.

It is a probability estimate from history, not knowledge of the future.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CLASSES = ("rising", "sideways", "falling")

FEATURES = {
    # key in the analogue state table: (plain name, technical name)
    "dist_10m_avg": ("gold vs its 10-month average", "P/SMA10 - 1"),
    "dist_10y_avg": ("gold vs its 10-year average", "P/SMA120 - 1"),
    "return_3y": ("change over 3 years", "3-year return"),
    "fall_from_24m_high": ("distance below its 2-year high", "P/max24 - 1"),
    "efficiency_ratio": ("how steady the move has been", "efficiency ratio"),
    "mom_12_1": ("gold vs a year ago (rule 1)", "12-1 momentum"),
    "ret_3m": ("change over the last 3 months", "3-month return"),
    "real_yield_proxy": ("interest rates after inflation", "GS10 - CPI y/y"),
    "real_yield_proxy_chg_6m": ("change in interest rates after inflation", "6m change in real-yield proxy"),
    "fed_dir": ("US interest rates rising or falling", "Fed direction (+1 hiking, -1 cutting)"),
    "dollar_chg_6m": ("the dollar's move", "DTWEXBGS 6m change"),
    "cpi_yoy": ("US inflation", "CPI y/y"),
    "oil_chg_12m": ("the oil price's move", "Brent 12m change"),
    "gpr_pct": ("war and political risk", "GPR 120m percentile"),
    "vix_pct": ("stock market fear", "VIX 120m percentile"),
    "cftc_mm_pct": ("speculators' bets", "CFTC managed-money 36m percentile"),
    "usdchf_chg_12m": ("the franc's move against the dollar", "USD/CHF 12m change"),
}


def classes_from_returns(r: pd.Series, up: float = 0.10, down: float = -0.10) -> pd.Series:
    out = pd.Series(np.nan, index=r.index)
    out[r >= up] = 0
    out[r <= down] = 2
    out[(r > down) & (r < up)] = 1
    return out


def feature_table(state: pd.DataFrame, gold: pd.Series) -> pd.DataFrame:
    X = pd.DataFrame(index=state.index)
    for k in FEATURES:
        if k in state.columns:
            X[k] = state[k].astype(float)
    X["mom_12_1"] = (gold.shift(1) / gold.shift(12) - 1).reindex(state.index)
    X["ret_3m"] = (gold / gold.shift(3) - 1).reindex(state.index)
    if "fed_direction" in state.columns:
        X["fed_dir"] = state["fed_direction"].map({"hiking": 1.0, "cutting": -1.0, "on hold": 0.0})
    return X[[k for k in FEATURES if k in X.columns]]


def _softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


L2 = 300.0   # strong shrinkage; chosen from 8 / 60 / 300 / 1500 on the walk-forward test (disclosed on the page)


def fit(X: np.ndarray, y: np.ndarray, l2: float = L2, iters: int = 600, lr: float = 0.5) -> np.ndarray:
    """Multinomial logistic regression, L2 on the weights (not the intercepts), plain gradient descent.
    The step shrinks with the penalty so heavy shrinkage stays numerically stable."""
    n, d = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    W = np.zeros((d + 1, 3))
    Y = np.eye(3)[y.astype(int)]
    prior = np.clip(Y.mean(axis=0), 1e-3, 1)
    W[0] = np.log(prior)
    reg = np.full((d + 1, 1), l2 / n)
    reg[0] = 0
    lr = lr / (1 + l2 / n)
    for _ in range(iters):
        P = _softmax(Xb @ W)
        G = Xb.T @ (P - Y) / n + reg * W
        W -= lr * G
    return W


def predict(W: np.ndarray, X: np.ndarray) -> np.ndarray:
    return _softmax(np.hstack([np.ones((len(X), 1)), X]) @ W)


def _standardise(train: pd.DataFrame, rows: pd.DataFrame):
    mu, sd = train.mean(), train.std(ddof=0).replace(0, np.nan)
    f = lambda d: ((d - mu) / sd).fillna(0.0).clip(-4, 4).to_numpy()   # missing = no information
    return f(train), f(rows), mu, sd


def brier(P: np.ndarray, y: np.ndarray) -> float:
    return float(((P - np.eye(3)[y.astype(int)]) ** 2).sum(axis=1).mean())


def walk_forward(X: pd.DataFrame, y: pd.Series, start: str, h: int = 12, refit_every: int = 6,
                 min_train: int = 120) -> pd.DataFrame:
    """Out-of-sample odds for every month from ``start``: model and normal (base) odds."""
    rows = []
    idx = list(X.index)
    pos = {d: i for i, d in enumerate(idx)}
    W = mu = sd = None
    last_fit = None
    for t in X.index[X.index >= pd.Period(start, "M")]:
        k = pos[t] - h
        if k < 0:
            continue
        train_idx = [d for d in idx[: k + 1] if not pd.isna(y.get(d))]
        if len(train_idx) < min_train:
            continue
        if last_fit is None or pos[t] - last_fit >= refit_every:
            Xt, _, mu, sd = _standardise(X.loc[train_idx], X.loc[[t]])
            W = fit(Xt, y.loc[train_idx].to_numpy())
            base = np.bincount(y.loc[train_idx].astype(int), minlength=3) / len(train_idx)
            last_fit = pos[t]
        xt = ((X.loc[[t]] - mu) / sd).fillna(0.0).clip(-4, 4).to_numpy()
        p = predict(W, xt)[0]
        rows.append({"month": t, "p_model": p, "p_base": base, "y": y.get(t)})
    return pd.DataFrame(rows)


def best_blend(wf: pd.DataFrame) -> tuple[float, dict]:
    """Blend weight on the model (0..1) that scored best on months with a known outcome."""
    done = wf.dropna(subset=["y"])
    if done.empty:
        return 0.0, {"n": 0}
    Pm, Pb, y = np.vstack(done.p_model), np.vstack(done.p_base), done.y.to_numpy()
    scores = {w: brier(w * Pm + (1 - w) * Pb, y) for w in np.linspace(0, 1, 11)}
    w = min(scores, key=scores.get)
    hit_m = float((Pm.argmax(1) == y).mean())
    hit_b = float((Pb.argmax(1) == y).mean())
    return float(w), {"n": int(len(done)), "brier_model": brier(Pm, y), "brier_base": brier(Pb, y),
                      "brier_blend": scores[w], "hit_model": hit_m, "hit_base": hit_b,
                      "skill": 1 - brier(Pm, y) / brier(Pb, y)}


def contributions(W: np.ndarray, x: np.ndarray, names: list[str]) -> list[dict]:
    """Push of each measure towards rising vs falling: x_i * (w_rising_i - w_falling_i)."""
    push = x * (W[1:, 0] - W[1:, 2])
    out = [{"key": n, "plain": FEATURES[n][0], "tech": FEATURES[n][1], "z": float(xi), "push": float(p)}
           for n, xi, p in zip(names, x, push)]
    return sorted(out, key=lambda d: -abs(d["push"]))


def build(state: pd.DataFrame, gold_usd: pd.Series, gold_chf: pd.Series, start: str = "2000-01",
          train_from: str = "1975-01", h: int = 12) -> dict:
    out = {"horizon_months": h, "currencies": {}}
    for cur, p in (("USD", gold_usd), ("CHF", gold_chf)):
        X = feature_table(state, gold_usd).loc[train_from:]
        fwd = (p.shift(-h) / p - 1).reindex(X.index)
        y = classes_from_returns(fwd)
        wf = walk_forward(X, y, start, h)
        w, track = best_blend(wf)
        # today's odds: fit on everything with a known outcome
        known = y.dropna().index
        Xt, xnow, mu, sd = _standardise(X.loc[known], X.iloc[[-1]])
        W = fit(Xt, y.loc[known].to_numpy())
        pm = predict(W, xnow)[0]
        pb = np.bincount(y.loc[known].astype(int), minlength=3) / len(known)
        pf = w * pm + (1 - w) * pb
        # calibration: in months where the blended odds favoured a class, how often it happened
        done = wf.dropna(subset=["y"])
        Pbl = w * np.vstack(done.p_model) + (1 - w) * np.vstack(done.p_base) if len(done) else np.zeros((0, 3))
        cal = []
        for lo, hi in ((0, 0.3), (0.3, 0.45), (0.45, 1.01)):
            sel = (Pbl[:, 0] >= lo) & (Pbl[:, 0] < hi) if len(done) else np.array([], bool)
            if sel.sum():
                cal.append({"range": f"{int(lo * 100)}-{min(int(hi * 100), 100)}%", "n": int(sel.sum()),
                            "said": float(Pbl[sel, 0].mean()), "happened": float((done.y.to_numpy()[sel] == 0).mean())})
        out["currencies"][cur] = {
            "as_of": str(X.index[-1]), "odds": dict(zip(CLASSES, map(float, pf))),
            "model_odds": dict(zip(CLASSES, map(float, pm))), "normal_odds": dict(zip(CLASSES, map(float, pb))),
            "blend_weight": w, "track": track, "calibration_rising": cal,
            "drivers": contributions(W, xnow[0], list(X.columns)),
            "n_train": int(len(known)), "features": list(X.columns),
        }
    return out
