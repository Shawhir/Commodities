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
    """0 rising (>= up), 1 sideways, 2 falling (<= down). Thresholds come from the regime config."""
    out = pd.Series(np.nan, index=r.index)
    out[r >= up] = 0
    out[r <= down] = 2
    out[(r > down) & (r < up)] = 1
    return out


def forward_return(p: pd.Series, h: int) -> pd.Series:
    """Return over the next ``h`` calendar months. Gaps are kept as gaps, so a missing month never
    turns a 12-month return into a 13-month one."""
    if isinstance(p.index, pd.PeriodIndex):
        full = p.reindex(pd.period_range(p.index[0], p.index[-1], freq=p.index.freq))
        return (full.shift(-h) / full - 1).reindex(p.index)
    return p.shift(-h) / p - 1


PRICE_SHAPE = ("dist_10m_avg", "dist_10y_avg", "return_3y", "fall_from_24m_high", "efficiency_ratio")


def feature_table(state: pd.DataFrame, price: pd.Series) -> pd.DataFrame:
    """Month-end measures. Price-shape and momentum measures come from ``price`` (the currency
    being predicted), so the franc odds are driven by gold in francs; the rest come from ``state``."""
    from ..indicators.stretch import measures
    from ..indicators.trend import momentum_12_1
    from ..regime.labeller import efficiency_ratio
    X = pd.DataFrame(index=state.index)
    full = price.reindex(pd.period_range(price.index[0], price.index[-1], freq="M")) \
        if isinstance(price.index, pd.PeriodIndex) else price
    shape = measures(full)
    shape["efficiency_ratio"] = efficiency_ratio(full)
    for k in FEATURES:
        if k in PRICE_SHAPE:
            X[k] = shape[k].reindex(state.index)
        elif k in state.columns:
            X[k] = state[k].astype(float)
    X["mom_12_1"] = momentum_12_1(full).reindex(state.index)
    X["ret_3m"] = (full / full.shift(3) - 1).reindex(state.index)
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


def _scaler(train: pd.DataFrame):
    return train.mean(), train.std(ddof=0).replace(0, np.nan)


def _apply(rows: pd.DataFrame, mu: pd.Series, sd: pd.Series) -> np.ndarray:
    """Standardise with training statistics; a missing value (or zero spread) carries no information (0)."""
    return _apply_arr(rows.to_numpy(dtype=float), mu.to_numpy(dtype=float), sd.to_numpy(dtype=float))


def _apply_arr(rows: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    z = (rows - mu) / sd
    return np.clip(np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0), -4, 4)


def _standardise(train: pd.DataFrame, rows: pd.DataFrame):
    mu, sd = _scaler(train)
    return _apply(train, mu, sd), _apply(rows, mu, sd), mu, sd


def brier(P: np.ndarray, y: np.ndarray) -> float:
    return float(((P - np.eye(3)[y.astype(int)]) ** 2).sum(axis=1).mean())


WF_COLUMNS = ["month", "p_model", "p_base", "y", "trained_to"]


def walk_forward(X: pd.DataFrame, y: pd.Series, start: str, h: int = 12, refit_every: int = 6,
                 min_train: int = 120) -> pd.DataFrame:
    """Out-of-sample odds for every month from ``start``: model and normal (base) odds.
    At month t the model only sees months up to t - h, whose outcome was already known."""
    y = y.reindex(X.index)
    Xv = X.to_numpy(dtype=float)
    known = y.notna().to_numpy()
    yv = y.to_numpy()
    n_known = np.cumsum(known)
    rows = []
    W = mu = sd = base = trained_to = None
    last_fit = None
    start_p = pd.Period(start, "M")
    for i, t in enumerate(X.index):
        if t < start_p:
            continue
        k = i - h
        if k < 0 or n_known[k] < min_train:
            continue
        if last_fit is None or i - last_fit >= refit_every:
            mask = known[: k + 1]
            train = X.iloc[: k + 1][mask]
            ytr = yv[: k + 1][mask].astype(int)
            mu, sd = _scaler(train)
            W = fit(_apply(train, mu, sd), ytr)
            base = np.bincount(ytr, minlength=3) / len(ytr)
            trained_to = train.index.max()
            mu_v, sd_v = mu.to_numpy(dtype=float), sd.to_numpy(dtype=float)
            last_fit = i
        p = predict(W, _apply_arr(Xv[i:i + 1], mu_v, sd_v))[0]
        rows.append({"month": t, "p_model": p, "p_base": base, "y": yv[i], "trained_to": trained_to})
    return pd.DataFrame(rows, columns=WF_COLUMNS)


def best_blend(wf: pd.DataFrame) -> tuple[float, dict]:
    """Blend weight on the model (0..1) that scored best on months with a known outcome."""
    done = wf.dropna(subset=["y"]) if "y" in wf.columns else wf
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


def contributions(W: np.ndarray, x: np.ndarray, names: list[str], raw: pd.Series | None = None) -> list[dict]:
    """Push of each measure towards rising vs falling: x_i * (w_rising_i - w_falling_i).
    ``raw`` is today's unstandardised value (for wording such as the Fed's actual stance)."""
    push = x * (W[1:, 0] - W[1:, 2])
    out = [{"key": n, "plain": FEATURES[n][0], "tech": FEATURES[n][1], "z": float(xi), "push": float(p),
            "raw": None if raw is None or pd.isna(raw.get(n)) else float(raw[n])}
           for n, xi, p in zip(names, x, push)]
    return sorted(out, key=lambda d: -abs(d["push"]))


def build(state: pd.DataFrame, gold_usd: pd.Series, gold_chf: pd.Series, start: str = "2000-01",
          train_from: str = "1975-01", h: int = 12, up: float = 0.10, down: float = -0.10) -> dict:
    """``up``/``down`` come from the regime thresholds (config/thresholds.yaml)."""
    out = {"horizon_months": h, "up": up, "down": down, "currencies": {}}
    for cur, p in (("USD", gold_usd), ("CHF", gold_chf)):
        X = feature_table(state, p).loc[train_from:]
        y = classes_from_returns(forward_return(p, h).reindex(X.index), up, down)
        wf = walk_forward(X, y, start, h)
        w, track = best_blend(wf)
        known = y.dropna().index
        if len(known) < 60:
            out["currencies"][cur] = None
            continue
        Xt, xnow, mu, sd = _standardise(X.loc[known], X.iloc[[-1]])
        W = fit(Xt, y.loc[known].astype(int).to_numpy())
        pm = predict(W, xnow)[0]
        pb = np.bincount(y.loc[known].astype(int), minlength=3) / len(known)
        pf = w * pm + (1 - w) * pb
        out["currencies"][cur] = {
            "as_of": str(X.index[-1]), "odds": dict(zip(CLASSES, map(float, pf))),
            "model_odds": dict(zip(CLASSES, map(float, pm))), "normal_odds": dict(zip(CLASSES, map(float, pb))),
            "blend_weight": w, "track": track,
            "drivers": contributions(W, xnow[0], list(X.columns), X.iloc[-1]),
            "n_train": int(len(known)), "features": list(X.columns),
        }
    return out
