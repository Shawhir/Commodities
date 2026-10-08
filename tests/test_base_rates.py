import json

import numpy as np
import pandas as pd

from pmdash.history import base_rates as br
from pmdash.indicators import technical as ta


def _walk(seed=0, n=3000, start="2010-01-01"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    return pd.DataFrame({"close": c, "high": c * 1.005, "low": c * 0.995}, index=idx)


def test_rate_counts_only_known_outcomes_and_spells():
    p = pd.Series(np.arange(1, 25, dtype=float), index=pd.period_range("2000-01", periods=24, freq="M"))
    cond = pd.Series(True, index=p.index)
    r = br.rate(p, cond, 12, "x")
    assert r.n_periods == 12                 # the last 12 months have no 12-month outcome yet
    assert r.share_up == 1.0 and r.n_spells == 1


def test_spells_counts_separate_episodes():
    c = pd.Series([1, 1, 0, 0, 0, 1, 0, 1], dtype=bool)
    assert br.spells(c, 3) == 2


def test_honesty_test_uses_only_past_outcomes():
    # a setup that is always true and a price that only rises: the setup carries no extra information
    p = pd.Series(np.linspace(100, 200, 400), index=pd.period_range("1980-01", periods=400, freq="M"))
    cond = pd.Series(True, index=p.index)
    r = br.honesty_test(p, cond, 12, pd.Period("1990-01", "M"))
    assert r["n"] > 0 and r["label"] == "context only"
    assert abs(r["brier_setup"] - r["brier_base"]) < 1e-12


def test_noise_rarely_passes():
    passes = tests = 0
    for seed in range(4):
        df = _walk(seed, 4000, "2000-01-01")
        ind = ta.compute(df)
        for s in ta.signals(ind).values():
            r = br.honesty_test(df.close, s["cond"].fillna(False), 63, pd.Timestamp("2008-01-01"), min_cases=60)
            if r["n"]:
                tests += 1
                passes += r["label"] == "useful"
    assert tests > 20 and passes / tests < 0.15


def test_rsi_extremes_and_known_value():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert ta.rsi(up).iloc[-1] == 100
    flat_alt = pd.Series([10, 11] * 30, dtype=float)
    assert abs(ta.rsi(flat_alt).iloc[-1] - 50) < 5


def test_moving_average_cross_and_readings_text():
    df = _walk(1)
    ind = ta.compute(df)
    rd = {r["key"]: r for r in ta.readings(ind)}
    assert set(rd) >= {"rsi", "macd", "bands", "ma200", "cross", "range52"}
    assert ("above" in rd["ma200"]["value"]) == bool(ind["above_200"].iloc[-1])


def test_build_technical_only_lists_signals_true_today():
    out = br.build_technical(_walk(2), "test")
    for a in out["active"]:
        assert a["rates"][0]["n_periods"] > 0
    assert len(out["chart"]["close"]) == 260


def test_yahoo_and_stooq_parsers():
    from pmdash.ingest.generic import StooqDaily, YahooChart
    js = {"chart": {"result": [{"timestamp": [1759708800, 1759795200],
                                "indicators": {"quote": [{"open": [4000, 4010], "high": [4050, 4060], "low": [3990, 4000],
                                                          "close": [4020, None], "volume": [1000, 1200]}]}}]}}
    f = YahooChart(source_id="gold_fut_daily", spec={"ticker": "GC=F", "prefix": "gold_fut", "today": "2026-10-10"})
    assert "GC=F" in f.spec["url"]
    df = f.parse(json.dumps(js).encode())
    closes = df[df.series_id == "gold_fut_close"]
    assert list(closes.value) == [4020]                 # null close dropped, not invented
    s = StooqDaily(source_id="gold_spot_daily", spec={"symbol": "xauusd", "prefix": "gold_spot"})
    d2 = s.parse(b"Date,Open,High,Low,Close\n2026-10-06,4000,4050,3990,4020\n2026-10-07,4020,4070,4010,4060\n")
    assert sorted(d2.series_id.unique()) == ["gold_spot_close", "gold_spot_high", "gold_spot_low", "gold_spot_open"]


def test_load_daily_prefers_futures_and_falls_back():
    from pmdash import data
    from pmdash.storage import db
    con = db.connect()
    idx = pd.bdate_range("2024-01-01", periods=400)
    vals = pd.DataFrame({"ref_date": idx, "available_date": idx + pd.Timedelta(days=1), "value": np.linspace(1, 2, 400)})
    db.upsert_observations(con, "gold_spot_close", vals, "t")
    df, src = data.load_daily(con, "gold")
    assert len(df) == 400 and "spot" in src
    db.upsert_observations(con, "gold_fut_close", vals, "t")
    df, src = data.load_daily(con, "gold")
    assert "futures" in src


def test_yahoo_drops_todays_unfinished_bar():
    from pmdash.ingest.generic import YahooChart
    js = {"chart": {"result": [{"timestamp": [1759708800, 1759795200],      # 2025-10-06, 2025-10-07
                                "indicators": {"quote": [{"close": [4020, 4030]}]}}]}}
    f = YahooChart(source_id="x", spec={"ticker": "GC=F", "prefix": "gold_fut", "today": "2025-10-07"})
    df = f.parse(json.dumps(js).encode())
    assert list(df.value) == [4020]


def test_educated_guess_ranges_and_trust(gold, fx, thresholds):
    from pmdash.indicators.stretch import measures
    from pmdash.indicators.trend import ma_signal, momentum_signal
    from pmdash.regime.labeller import label_from_config
    reg = label_from_config(gold, thresholds)["regime"]
    g = br.build_guess(gold, (gold * fx).dropna(), reg, momentum_signal(gold), ma_signal(gold),
                       measures(gold["1971-08":])["dist_10y_avg"])
    for cur in ("USD", "CHF"):
        rows = g["currencies"][cur]["rows"]
        assert [r["years"] for r in rows] == [1, 3, 5]
        for r in rows:
            for k in ("like_today", "any_time"):
                x = r[k]
                assert x["price_lo"] <= x["price_mid"] <= x["price_hi"]
            assert r["trust"] in ("very low", "low", "moderate")
    assert g["currencies"]["USD"]["rows"][2]["trust"] == "very low"     # too few 5-year spells
