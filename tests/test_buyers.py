import numpy as np
import pandas as pd

from pmdash.history import buyers as B


def _m(start, vals):
    return pd.Series(vals, index=pd.period_range(start, periods=len(vals), freq="M"), dtype=float)


def test_share_and_tonnes_needed_are_consistent():
    price = 4000.0
    g, non_gold = 500.0, 200e9
    need = B.tonnes_for_share(0.30, g, non_gold, price)
    gv = (g + need) * B.OZ_PER_TONNE * price
    assert abs(gv / (gv + non_gold) - 0.30) < 1e-9
    # a higher price shrinks the tonnes needed for a share target
    assert B.tonnes_for_share(0.30, g, non_gold, price * 1.2) < need


def test_target_progress_and_years_left():
    gold = {"CZ": _m("2024-01", np.linspace(40, 76, 33))}          # ~1.1 t a month
    rows = B.bank_rows(gold, {}, {"CZ": {"plain": "Czech"}},
                       [{"bank": "CZ", "tonnes": 100, "by": "2028-12"}], 4000.0)
    t = rows[0]["target"]["goals"][0]
    assert abs(rows[0]["tonnes"] - 76) < 1e-9 and t["remaining_t"] > 0
    assert abs(t["years_left_at_pace"] - t["remaining_t"] / rows[0]["pace_12m"]) < 1e-9
    assert t["on_track"] is True


def test_scenario_shrinks_with_price_and_skips_missing():
    gold = {"AA": _m("2025-01", [100.0] * 20), "BB": _m("2025-01", [50.0] * 20)}
    res = {"AA": _m("2025-01", [100e9] * 20)}                       # BB has no reserves figure
    rows = B.bank_rows(gold, res, {"AA": {"plain": "A"}, "BB": {"plain": "B"}}, [], 4000.0)
    sc = B.scenario(rows, ["AA", "BB"], [0.5], 4000.0, 3600)
    assert sc["banks"] == ["AA"]
    r = sc["rows"][0]
    assert r["tonnes_up20"] < r["tonnes_now"] < r["tonnes_down20"]


def test_flow_reading_needs_full_years():
    s = _m("2024-01", [10.0] * 24)
    f = B.flow_reading(s, "x", "y")
    assert f["sum12_t"] == 120 and f["prev12_t"] == 120 and f["chg_vs_prev12"] == 0
    assert B.flow_reading(_m("2025-06", [1.0] * 5), "x", "y")["sum12_t"] is None


def test_imf_gold_parser_reads_tonnes():
    from pathlib import Path
    from pmdash.ingest.buyers_sources import ImfGold
    f = ImfGold("cb_gold_imf", {"countries": {"CHN": "cn"}, "start": "2026-01"})
    df = f.parse((Path(__file__).parent / "fixtures" / "imf_irfcl_chn.xml").read_bytes())
    s = df[df.series_id == "cb_gold_t_cn"].set_index("ref_date")["value"]
    assert len(s) == 8 and abs(s.iloc[-1] - 76_730_000 / 32150.7466) < 1e-6     # Aug 2026, ~2,387 t
    assert (pd.to_datetime(df.available_date) > pd.to_datetime(df.ref_date)).all()


def test_comtrade_parser_maps_partners_to_series():
    from pathlib import Path
    from pmdash.ingest.buyers_sources import ComtradeMonthly
    page = (Path(__file__).parent / "fixtures" / "comtrade_ch_202606.json").read_text()
    f = ComtradeMonthly("trade_ch_exports", {"reporter": 757, "flow": "X", "partners": {0: "total", 40: "at"},
                                             "prefix": "trade_ch_x"})
    df = f.parse(("[" + page + "]").encode())
    tot = df[df.series_id == "trade_ch_x_total"]["value"].iloc[0]
    assert abs(tot - 106.717742) < 1e-6 and set(df.series_id) == {"trade_ch_x_total", "trade_ch_x_at"}


def test_build_section_with_partial_data(gold):
    from pmdash import config
    from pmdash.digest.brief import FORBIDDEN
    idx = pd.period_range("2005-01", "2026-08", freq="M")
    ser = {"cb_gold_t_cn": pd.Series(np.linspace(600, 2387, len(idx)), index=idx),
           "cb_gold_t_pl": pd.Series(np.linspace(100, 520, len(idx)), index=idx),
           "res_exgold_cn": pd.Series(3.2e12, index=idx),
           "trade_in_m_total": pd.Series(60.0, index=idx[-30:]),
           "gld_holdings_m": pd.Series(np.linspace(800, 950, len(idx)), index=idx)}
    out = B.build(ser, gold, 4150.0, config.load("buyers"), pd.Timestamp("2026-10-09"))
    assert {g["id"] for g in out["groups"]} >= {"central_banks", "china", "india", "usa", "switzerland"}
    cn = next(r for r in out["banks"] if r["bank"] == "CN")
    assert 0 < cn["share_now"] < 1 and cn["pace_12m"] > 0
    assert any(r.get("missing") for r in out["banks"])                     # banks without data are shown as such
    pl = next(r for r in out["banks"] if r["bank"] == "PL")
    assert "target" in pl and pl["target"]["goals"][0]["goal"] == 700
    assert out["scenario"]["banks"] == ["CN"]                              # only banks with reserves data
    low = " " + (out["headline"] + " " + out["honesty"]["plain"]).lower() + " "
    assert not [w for w in FORBIDDEN if f" {w} " in low]
    assert all(d["date"] >= "2026-10-09" for g in out["groups"] for d in g["dates"])


def test_snb_cube_parser_reads_swiss_inflation():
    from pathlib import Path
    from pmdash.ingest.buyers_sources import SnbCube
    f = SnbCube("ch_cpi_yoy_snb", {"cube": "plkopr", "dim": "VVP"})
    df = f.parse((Path(__file__).parent / "fixtures" / "snb_plkopr.csv").read_bytes())
    last = df.sort_values("ref_date").iloc[-1]
    assert str(last.ref_date)[:7] == "2026-08" and abs(last.value - 0.80724605) < 1e-9
