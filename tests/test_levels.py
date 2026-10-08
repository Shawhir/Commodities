"""State machine on synthetic daily series (phase 3 acceptance)."""
import pandas as pd

from pmdash.levels.engine import LineSpec, run_line


def _closes(vals, start="2026-01-05"):
    return pd.Series(vals, index=pd.bdate_range(start, periods=len(vals)), dtype=float)


def states(tr):
    return [t.state for t in tr]


def test_touch_within_buffer_is_not_a_break():
    spec = LineSpec("l", direction="below", buffer_pct=1.0)
    tr = run_line(spec, _closes([110, 105, 101.5, 99.5, 101, 106]), 100.0)
    assert states(tr) == ["approaching", "intact"]
    assert not any(t.alert for t in tr)


def test_break_then_confirm_on_second_close():
    spec = LineSpec("l", direction="below", buffer_pct=1.0)
    tr = run_line(spec, _closes([110, 98.5, 98.0]), 100.0)
    assert states(tr) == ["broken", "confirmed"]
    assert [t.alert for t in tr] == [False, True]


def test_second_close_must_be_consecutive():
    spec = LineSpec("l", direction="below", buffer_pct=1.0)
    # 99.5 is past the line but inside the buffer, which resets the count
    tr = run_line(spec, _closes([110, 98.5, 99.5, 98.5, 98.0]), 100.0)
    assert states(tr) == ["broken", "confirmed"]
    assert tr[-1].date == _closes([0] * 5).index[4]


def test_weekly_close_confirms_immediately():
    c = _closes([110, 98.5])
    weekly = pd.Series([False, True], index=c.index)
    tr = run_line(LineSpec("l", direction="below"), c, 100.0, weekly=weekly)
    assert states(tr) == ["broken", "confirmed"]
    assert tr[0].date == tr[1].date


def test_failed_break_within_window():
    spec = LineSpec("l", direction="below", buffer_pct=1.0, fail_window=3)
    tr = run_line(spec, _closes([110, 98, 97, 101, 110]), 100.0)
    assert states(tr) == ["broken", "confirmed", "failed", "intact"]
    assert [t.alert for t in tr] == [False, True, True, False]


def test_recovery_after_window_is_not_failure():
    spec = LineSpec("l", direction="below", buffer_pct=1.0, fail_window=2)
    tr = run_line(spec, _closes([110, 98, 97, 96, 95, 110]), 100.0)
    assert states(tr) == ["broken", "confirmed", "intact"]


def test_above_direction():
    spec = LineSpec("l", direction="above", buffer_pct=1.0)
    tr = run_line(spec, _closes([90, 99, 102, 103]), 100.0)
    assert states(tr) == ["approaching", "broken", "confirmed"]


def test_both_direction_flips_after_holding():
    spec = LineSpec("ma", direction="both", buffer_pct=1.0, fail_window=2)
    c = _closes([110, 108, 97, 96, 95, 94, 104, 105])
    tr = run_line(spec, c, 100.0)
    assert states(tr) == ["broken", "confirmed", "intact", "broken", "confirmed"]
    assert tr[2].watching == "above"


def test_time_varying_line_and_absolute_buffer():
    c = _closes([0.05, 0.02, -0.01, -0.02])
    tr = run_line(LineSpec("mom", direction="both", buffer_pct=None, buffer_abs=0.0), c, 0.0)
    assert states(tr) == ["broken", "confirmed"]
    line = pd.Series([100, 100, 90, 90], index=c.index, dtype=float)
    tr = run_line(LineSpec("l", direction="below"), _closes([110, 105, 95, 95]), line)
    assert states(tr) == []


def test_active_from_skips_history():
    c = _closes([90, 90, 90, 110, 98, 97])
    spec = LineSpec("l", direction="below", active_from=str(c.index[3].date()))
    assert states(run_line(spec, c, 100.0)) == ["broken", "confirmed"]


def test_trigger_id_format():
    c = _closes([110, 98, 97])
    tr = run_line(LineSpec("gold_jun26_low", direction="below", currency="USD"), c, 100.0)
    assert tr[-1].trigger_id == f"gold_jun26_low:USD:confirmed:{c.index[-1].date()}"


def test_historical_replay_2011_2015_and_2026(gold, fx, thresholds):
    from pmdash import config
    from pmdash.levels.lines import evaluate_market
    trans, _ = evaluate_market("gold", {"USD": gold, "CHF": (gold * fx).dropna()}, config.load("levels"),
                               thresholds, usdchf=fx)
    df = pd.DataFrame([t.to_dict() for t in trans])
    usd_ma = df[(df.line_id == "gold_10m_avg") & (df.currency == "USD") & (df.state == "confirmed")]
    # 2013 bear market: price confirmed below its 10-month average by early 2013
    assert ((usd_ma.date >= "2012-10-01") & (usd_ma.date <= "2013-06-30")).any()
    # 2026: June close confirmed below the 10-month average (10-month rule "Out", section 7)
    assert (usd_ma.date == pd.Timestamp("2026-06-30")).any()
    # manual 2026 lines are never judged before they existed
    jun = df[df.line_id == "gold_jun26_low"]
    assert jun.empty or (jun.date >= "2026-07-01").all()
