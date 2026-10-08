"""Decision brief: thresholds must be exact (re-run the rule at the threshold) and the text must
never contain instruction language."""
from datetime import date

import pandas as pd
import pytest

from pmdash import config
from pmdash.analogues import state
from pmdash.digest import brief
from pmdash.indicators.trend import ma_signal, momentum_12_1
from pmdash.regime.labeller import label_from_config


def _extend(p, *prices):
    q = p.copy()
    for i, v in enumerate(prices, 1):
        q.loc[p.index[-1] + i] = v
    return q


def test_momentum_steps_match_rule(gold):
    r = brief.momentum_rule(gold)
    first = r["steps"][0]
    assert first["known"] and abs(first["value"] - (4319 / 4058 - 1)) < 1e-9
    nov = r["steps"][1]
    assert not nov["known"] and nov["threshold"] == 4087.0
    # an October average just below / above the threshold flips / keeps the November reading
    assert momentum_12_1(_extend(gold, 4086, 4300)).iloc[-1] < 0
    assert momentum_12_1(_extend(gold, 4088, 4300)).iloc[-1] > 0
    assert "January 2027" in r["if_flat"]


def test_ma_threshold_is_exact(gold):
    r = brief.ma_rule(gold)
    assert r["state"] == "Out"
    t = r["threshold"]
    assert ma_signal(_extend(gold, t + 1)).iloc[-1] == 1
    assert ma_signal(_extend(gold, t - 1)).iloc[-1] == 0


def test_regime_boundaries_hold(gold, thresholds):
    b = brief.regime_boundaries(gold, thresholds)
    assert b["now"] == "Sideways"
    for z in b["ranges"]:
        mid = (z.get("low_cut", z["low"]) + z.get("high_cut", z["high"])) / 2
        assert label_from_config(_extend(gold, mid), thresholds)["regime"].iloc[-1] == z["regime"]


def test_brief_has_no_instruction_language(gold, fx, thresholds):
    st = state.build(gold, fx)
    b = brief.build(gold, fx, st, {}, [], [], {"CHF": 97, "USD": 91}, thresholds, date(2026, 10, 8))
    assert brief.check_language(b) == []
    assert "disagree" in b["headline"]


def test_language_check_catches_instructions():
    fake = {"headline": "You should buy now.", "conflicts": [], "gaps": [], "rules": {}, "regimes": {}, "pressures": []}
    assert set(brief.check_language(fake)) >= {"should", "buy"}
