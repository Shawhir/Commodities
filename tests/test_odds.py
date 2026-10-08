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


def test_walk_forward_never_trains_on_unknown_outcomes(gold, fx):
    st = state.build(gold, fx)
    X = odds.feature_table(st, gold).loc["1975-01":]
    y = odds.classes_from_returns(odds.forward_return(gold, 12).reindex(X.index))
    wf = odds.walk_forward(X, y, "2010-01")
    assert len(wf) > 100
    # each prediction uses a model trained only on months at least 12 months earlier
    assert all((m - t).n >= 12 for m, t in zip(wf.month, wf.trained_to))


def test_walk_forward_with_too_little_history_does_not_crash(gold, fx):
    st = state.build(gold, fx)
    X = odds.feature_table(st, gold).loc["2020-01":]
    y = odds.classes_from_returns(odds.forward_return(gold, 12).reindex(X.index))
    wf = odds.walk_forward(X, y, "2021-01")
    assert wf.empty and list(wf.columns) == odds.WF_COLUMNS
    assert odds.best_blend(wf) == (0.0, {"n": 0})


def test_forward_return_counts_calendar_months_across_gaps():
    idx = pd.PeriodIndex(["2000-01", "2000-02", "2000-04"], freq="M")      # March missing
    p = pd.Series([100.0, 110.0, 130.0], index=idx)
    fr = odds.forward_return(p, 2)
    assert np.isnan(fr["2000-01"])            # 2000-03 is missing: no fake 3-month return
    assert abs(fr["2000-02"] - (130 / 110 - 1)) < 1e-12


def test_chf_features_use_franc_prices(gold, fx):
    st = state.build(gold, fx)
    chf = (gold * fx).dropna()
    Xu, Xc = odds.feature_table(st, gold), odds.feature_table(st, chf)
    t = Xu.index[-1]
    assert abs(Xc.loc[t, "mom_12_1"] - (chf.shift(1) / chf.shift(12) - 1)[t]) < 1e-12
    assert Xc.loc[t, "mom_12_1"] != Xu.loc[t, "mom_12_1"]


def test_thresholds_follow_config_and_drivers_carry_raw_fed(gold, fx):
    st = state.build(gold, fx)
    st["fed_direction"] = "on hold"
    o = odds.build(st, gold, (gold * fx).dropna(), up=0.12, down=-0.12)
    assert o["up"] == 0.12
    fed = [d for d in o["currencies"]["USD"]["drivers"] if d["key"] == "fed_dir"][0]
    assert fed["raw"] == 0.0


def test_build_outputs(gold, fx):
    st = state.build(gold, fx)
    o = odds.build(st, gold, (gold * fx).dropna())
    assert "calibration_rising" not in o["currencies"]["USD"]
    for cur in ("USD", "CHF"):
        c = o["currencies"][cur]
        assert abs(sum(c["odds"].values()) - 1) < 1e-9
        assert 0 <= c["blend_weight"] <= 1
        assert c["track"]["n"] > 200
