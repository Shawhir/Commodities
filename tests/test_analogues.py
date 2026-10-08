"""Section 8.4 price-only analogue result must reproduce (phase 10 acceptance)."""
import pandas as pd
import pytest

from pmdash.analogues import finder, state

PRICE = {"price_shape": ["fall_from_24m_high", "dist_10y_avg", "return_3y", "dist_10m_avg"]}


@pytest.fixture(scope="module")
def result(gold, fx):
    st = state.build(gold, fx)
    return finder.find(st, "2026-09", PRICE, prices={"USD": gold, "CHF": (gold * fx).dropna()})


def test_seed_matches(result):
    got = [(str(m.month), round(m.distance, 2), round(m.outcomes["fwd_12m_usd"] * 100),
            round(m.outcomes["fwd_24m_usd"] * 100)) for m in result.matches]
    assert got == [("2008-08", 0.59, 13, 45), ("1975-08", 0.72, -33, -11), ("2012-05", 0.93, -11, -19),
                   ("2006-10", 1.33, 29, 38), ("2010-07", 1.58, 32, 34), ("1978-12", 1.71, 119, 159)]


def test_disagreement_is_visible(result):
    assert result.disagreement
    assert "opposite directions" in result.summary()
    assert result.spread["n"] == 6
    assert result.baseline["n"] > 600


def test_target_state(gold, fx):
    now = state.build(gold, fx).loc["2026-09"]
    assert round(now.fall_from_24m_high, 2) == -0.14
    assert round(now.dist_10y_avg, 2) == 1.08
    assert round(now.return_3y, 2) == 1.25
    assert round(now.dist_10m_avg, 2) == -0.05


def test_missing_measures_dropped_not_invented(gold, fx):
    st = state.build(gold, fx)
    res = finder.find(st, "2026-09", {**PRICE, "rates_money": ["real_yield_10y"]}, prices={"USD": gold})
    assert res.dropped_measures == ["real_yield_10y"]
    assert [str(m.month) for m in res.matches][:2] == ["2008-08", "1975-08"]


def test_matches_are_collapsed_and_have_known_outcomes(result):
    months = [m.month for m in result.matches]
    for i, a in enumerate(months):
        assert a <= pd.Period("2024-09", "M")
        for b in months[i + 1:]:
            assert abs((a - b).n) >= 18


def test_out_of_sample_uses_only_earlier_history(gold, fx):
    st = state.build(gold, fx)
    df = finder.out_of_sample(st, gold, PRICE, start="2010-01")
    assert len(df) > 100
    s = finder.oos_summary(df)
    assert s["label"] in ("useful", "context only")
    # spot-check: a 2010 run never matches months after its cutoff
    res = finder.find(st, "2010-06", PRICE, prices={"USD": gold})
    assert all(m.month <= pd.Period("2008-06", "M") for m in res.matches)
