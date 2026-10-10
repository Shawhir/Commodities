"""Weekly-close lines: only completed weeks count, one weekly close beyond the line confirms."""
import pandas as pd

from pmdash.levels.weekly import evaluate, weekly_closes

ITEM = {"id": "w4000", "label": "Weekly close below $4,000", "type": "weekly_close", "value_usd": 4000,
        "direction": "below", "buffer_pct": 0.0, "fail_window_weeks": 2, "severity": "important",
        "since": "2026-01-01", "next_lo_usd": 3500, "next_hi_usd": 3700}


def _daily(vals, start="2026-01-05"):           # a Monday
    return pd.Series(vals, index=pd.bdate_range(start, periods=len(vals)), dtype=float)


def test_last_close_of_each_completed_week():
    c = _daily(range(1, 13))                   # Mon 5 Jan .. Tue 20 Jan
    wc = weekly_closes(c, today="2026-01-21")
    assert list(wc.index.date.astype(str)) == ["2026-01-09", "2026-01-16"]   # week of 19 Jan not finished
    assert list(wc) == [5.0, 10.0]


def test_holiday_friday_uses_thursday_and_today_friday_is_not_complete():
    c = _daily([1, 2, 3, 4, 5, 6, 7, 8, 9]).drop(pd.Timestamp("2026-01-09"))   # Friday holiday
    wc = weekly_closes(c, today="2026-01-15")
    assert str(wc.index[0].date()) == "2026-01-08"
    # on a Friday the daily loader has dropped today's bar; Thursday's close must not count
    assert len(weekly_closes(_daily([1, 2, 3, 4]), today="2026-01-09")) == 0


def test_dip_inside_week_does_not_trigger_but_weekly_close_does():
    wk1 = [4100, 3950, 3980, 4050, 4020]      # dips below during the week, closes above
    wk2 = [4010, 3990, 3970, 3960, 3980]      # closes below
    tr, st = evaluate(ITEM, _daily(wk1 + wk2), today="2026-01-20")
    assert [t.state for t in tr] == ["broken", "confirmed"]
    assert tr[-1].alert and str(tr[-1].date.date()) == "2026-01-16"
    assert st["triggered"] and st["closes_beyond"] == 1 and st["lowest"] == 3980


def test_holding_status():
    tr, st = evaluate(ITEM, _daily([4300] * 5 + [4200] * 5), today="2026-01-20")
    assert tr == [] and st["state"] == "holding" and not st["triggered"]
    assert round(st["distance"], 3) == 0.05
