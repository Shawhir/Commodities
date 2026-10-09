import numpy as np
import pandas as pd

from pmdash.history import outlook, scorecard


def _daily(start, n, f):
    idx = pd.bdate_range(start, periods=n)
    return pd.Series([f(i) for i in range(n)], index=idx, dtype=float)


def test_expected_move_bands_and_calibration():
    rng = np.random.default_rng(0)
    n = 252 * 12
    vol = 0.18
    px = _daily("2008-06-02", n, lambda i: 0.0)
    steps = rng.normal(0, vol / np.sqrt(252), n)
    px[:] = 1000 * np.exp(np.cumsum(steps))
    gvz = _daily("2008-06-02", n, lambda i: vol * 100)
    E = outlook.expected_move(gvz, px, 2000.0, 0.8, px.index[-1].to_period("M") - 1)
    r3 = next(r for r in E["rows"] if r["months"] == 3)
    s = vol * np.sqrt(3 / 12)
    assert abs(r3["usd"]["hi1"] - 2000 * np.exp(s)) < 1e-9 and abs(r3["chf"]["lo1"] - 2000 * np.exp(-s) * 0.8) < 1e-9
    # a random walk with the same volatility should land inside the 1-band range about 68% of the time
    assert 0.5 < r3["check"]["inside1"] < 0.85
    assert next(r for r in E["rows"] if r["months"] == 60)["source"] == "history"


def test_valuation_real_price_and_peaks(gold):
    cpi = pd.Series(np.linspace(50, 320, len(gold)), index=gold.index)
    V = outlook.valuation(gold, cpi, None, None, None, None)
    R = V["real"]
    assert 0 <= R["pct"] <= 100 and set(R["peaks"]) == {"1980", "2011"}
    assert abs(R["now"] - float(gold.iloc[-1])) < 1e-6          # today's dollars: latest price unchanged


def test_scenarios_flags_today_and_counts(gold, fx):
    from pmdash.analogues import state
    st = state.build(gold, fx)
    st["fed_direction"] = "hiking"
    out = outlook.scenarios(st, gold, None, None, 4000.0)
    row = next(r for r in out["rows"] if r["key"] == "fed_hiking")
    assert row["now"] is True and row["n_months"] > 0
    assert 0 <= out["base"]["share_up"] <= 1


def test_scorecard_records_once_and_scores(tmp_path):
    path = tmp_path / "f.csv"
    payload = {"expected": {"price_usd": 100.0, "rows": [{"months": 3, "source": "options", "usd": {"lo1": 90.0, "hi1": 110.0}}]},
               "odds": {"up": 0.1, "down": -0.1, "currencies": {"USD": {"odds": {"rising": .5, "sideways": .3, "falling": .2},
                        "normal_odds": {"rising": .3, "sideways": .5, "falling": .2}, "track": {"skill": -0.01}}}},
               "brief": {"rules": {"USD": {"momentum": {"state": "In"}}}}}
    assert scorecard.record(path, "2025-01", payload) == 3
    assert scorecard.record(path, "2025-01", payload) == 0                     # once a month
    log = scorecard.load(path)
    odds_row = log[log.kind == "odds_12m"].iloc[0]
    assert odds_row["p_rising"] == 0.3                                          # records what the page shows (normal odds)
    months = pd.period_range("2024-01", "2026-06", freq="M")
    avg = pd.Series(100.0, index=months); avg[pd.Period("2026-01", "M")] = 115.0
    fut = pd.Series(100.0, index=months); fut[pd.Period("2025-04", "M")] = 105.0
    sc = scorecard.score(log, avg, fut)
    assert sc["kinds"]["expected_move"]["hit_rate"] == 1.0
    assert sc["kinds"]["odds_12m"]["scored"] == 1 and sc["kinds"]["main_switch"]["n_on"] == 1
