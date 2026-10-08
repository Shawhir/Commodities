import numpy as np
import pandas as pd

from pmdash.analogues import state
from pmdash.history import odds


def test_classes_from_returns():
    r = pd.Series([0.15, 0.0, -0.2, np.nan])
    assert list(odds.classes_from_returns(r).fillna(-1)) == [0, 1, 2, -1]


def test_fit_learns_a_clear_signal_and_probabilities_sum_to_one():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(600, 2))
    y = np.where(X[:, 0] > 0.5, 0, np.where(X[:, 0] < -0.5, 2, 1))
    W = odds.fit(X, y, l2=1.0)
    P = odds.predict(W, np.array([[2.0, 0.0], [-2.0, 0.0]]))
    assert np.allclose(P.sum(axis=1), 1)
    assert P[0].argmax() == 0 and P[1].argmax() == 2


def test_heavy_penalty_stays_stable():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(300, 5))
    y = rng.integers(0, 3, 300)
    W = odds.fit(X, y, l2=5000.0)
    assert np.isfinite(W).all()
    P = odds.predict(W, X[:5])
    assert np.allclose(P, P[0], atol=0.05)                     # shrunk to the base rates


def test_walk_forward_never_trains_on_unknown_outcomes(monkeypatch, gold, fx):
    st = state.build(gold, fx)
    X = odds.feature_table(st, gold).loc["1975-01":]
    y = odds.classes_from_returns((gold.shift(-12) / gold - 1).reindex(X.index))
    seen = []
    real = odds._standardise

    def spy(train, rows):
        seen.append((train.index.max(), rows.index[0]))
        return real(train, rows)

    monkeypatch.setattr(odds, "_standardise", spy)
    wf = odds.walk_forward(X, y, "2010-01")
    assert len(wf) > 100
    for last_train, t in seen:
        assert (t - last_train).n >= 12


def test_build_outputs(gold, fx):
    st = state.build(gold, fx)
    o = odds.build(st, gold, (gold * fx).dropna())
    for cur in ("USD", "CHF"):
        c = o["currencies"][cur]
        assert abs(sum(c["odds"].values()) - 1) < 1e-9
        assert 0 <= c["blend_weight"] <= 1
        assert c["track"]["n"] > 200
