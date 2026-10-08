import io
import zipfile
from datetime import date

import pandas as pd

from pmdash import config
from pmdash.ingest.generic import CftcDisaggregated, CsvSeries, ManualFile
from pmdash.reports import calendar as cal
from pmdash.reports.check import check, revision_streak, revisions
from pmdash.storage import db, store


def _rel(rid, start, end):
    spec = config.load("reports")["reports"][rid]
    return cal.releases(rid, spec, date.fromisoformat(start), date.fromisoformat(end))


def test_cpi_window_after_month_end():
    r = [x for x in _rel("us_cpi", "2026-09-01", "2026-09-30") if x.period == "2026-08"][0]
    assert (r.window_start, r.window_end) == (date(2026, 9, 9), date(2026, 9, 16))


def test_jobs_first_friday():
    r = [x for x in _rel("us_jobs", "2026-10-01", "2026-10-31") if x.period == "2026-09"][0]
    assert r.window_start == r.window_end == date(2026, 10, 2) and r.window_start.weekday() == 4


def test_cot_tuesday_period_friday_release():
    rows = _rel("cftc_cot", "2026-10-05", "2026-10-11")
    r = [x for x in rows if x.period == "2026-10-06"][0]
    assert r.window_start == date(2026, 10, 9) and r.window_start.weekday() == 4


def test_fomc_fixed_dates_and_snb_thursday():
    assert [x.period for x in _rel("fomc", "2026-09-01", "2026-10-31")] == ["2026-09-16", "2026-10-28"]
    snb = [x for x in _rel("snb", "2026-09-01", "2026-09-30")][0]
    assert snb.window_start.weekday() == 3 and snb.window_end.month == 9


def test_status_received_due_overdue():
    con = db.connect()
    spec = config.load("reports")["reports"]["us_cpi"]
    aug = [x for x in _rel("us_cpi", "2026-09-01", "2026-09-30") if x.period == "2026-08"][0]
    assert cal.status(con, aug, spec, date(2026, 9, 12)).status == "due"
    assert cal.status(con, aug, spec, date(2026, 9, 19)).status == "late"
    assert cal.status(con, aug, spec, date(2026, 10, 1)).status == "overdue"
    df = pd.DataFrame({"ref_date": ["2026-08-01"], "available_date": ["2026-09-15"], "value": [335.0]})
    db.upsert_observations(con, "us_cpi_mirror", df, "t")
    assert cal.status(con, aug, spec, date(2026, 10, 1)).status == "received"


def test_check_records_release_and_headline():
    con = db.connect()
    idx = pd.date_range("2024-01-01", "2026-08-01", freq="MS")
    df = pd.DataFrame({"ref_date": idx, "available_date": idx + pd.Timedelta(days=45), "value": range(300, 300 + len(idx))})
    db.upsert_observations(con, "us_cpi_mirror", df, "t")
    rows = check(con, config.load("reports"), today=date(2026, 9, 20), fetch=False)
    cpi = [r for r in rows if r["report_id"] == "us_cpi" and r["period"] == "2026-08"][0]
    assert cpi["status"] == "received" and cpi["new"]
    assert "y/y" in cpi["detail"] and "no consensus" in cpi["detail"]
    # second run: not new any more
    rows = check(con, config.load("reports"), today=date(2026, 9, 21), fetch=False)
    assert not [r for r in rows if r["report_id"] == "us_cpi" and r["period"] == "2026-08"][0]["new"]


def test_revisions_and_streak():
    con = db.connect()
    base = pd.DataFrame({"ref_date": ["2026-07-01", "2026-08-01"], "available_date": ["2026-08-07", "2026-09-05"], "value": [100.0, 110.0]})
    db.upsert_observations(con, "us_payrolls", base, "t", fetched_at=pd.Timestamp("2026-09-05").to_pydatetime())
    rev = base.assign(value=[103.0, 112.0])
    db.upsert_observations(con, "us_payrolls", rev, "t", fetched_at=pd.Timestamp("2026-10-02").to_pydatetime())
    r = revisions(con, "us_payrolls", date(2026, 10, 1))
    assert list(r["change"]) == [3.0, 2.0]
    assert revision_streak(con, "us_payrolls") == (1, "up")


def test_store_roundtrip(tmp_path):
    con = db.connect()
    df = pd.DataFrame({"ref_date": ["2026-07-01"], "available_date": ["2026-08-01"], "value": [1.5]})
    db.upsert_observations(con, "x", df, "t")
    db.record_health(con, "x", ok=True, latest_ref_date=date(2026, 7, 1), rows_added=1)
    store.save(con, tmp_path)
    con2 = db.connect()
    store.load(con2, tmp_path)
    assert db.get_series(con2, "x").iloc[0] == 1.5
    assert con2.execute("SELECT count(*) FROM data_health").fetchone()[0] == 1


def test_csv_fetcher_filter_and_lag():
    raw = b"Date,Country,Exchange rate\n2026-08-03,Switzerland,0.80\n2026-08-03,Japan,147\n"
    f = CsvSeries(source_id="s", spec={"date_col": "Date", "value_col": "Exchange rate",
                                       "filter": {"Country": "Switzerland"}, "period": "day", "release_lag_days": 7})
    df = f.parse(raw)
    assert len(df) == 1 and df.value[0] == 0.80 and str(df.available_date[0].date()) == "2026-08-10"


def test_cftc_parser_on_synthetic_zip():
    rows = pd.DataFrame({
        "Market_and_Exchange_Names": ["GOLD - COMMODITY EXCHANGE INC.", "SILVER - COMMODITY EXCHANGE INC."],
        "Report_Date_as_YYYY-MM-DD": ["2026-10-06", "2026-10-06"],
        "CFTC_Contract_Market_Code": ["088691", "084691"],
        "Open_Interest_All": [500000, 150000],
        "M_Money_Positions_Long_All": [200000, 50000], "M_Money_Positions_Short_All": [50000, 20000],
        "Prod_Merc_Positions_Long_All": [30000, 10000], "Prod_Merc_Positions_Short_All": [120000, 40000],
    })
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("f_year.txt", rows.to_csv(index=False))
    f = CftcDisaggregated(source_id="cftc_cot", spec={"markets": {"gold": "088691", "silver": "084691"}})
    con = db.connect()
    f.run(con, raw=buf.getvalue())
    s = db.get_series(con, "cftc_gold_mm_net")
    assert s.iloc[0] == 150000
    assert db.get_series(con, "cftc_gold_mm_net", as_of="2026-10-08").empty      # published Friday 9 Oct
    assert db.get_series(con, "cftc_silver_prod_net").iloc[0] == -30000


def test_manual_template_is_ok_when_empty(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("# comment\nseries_id,ref_date,value,available_date,source\n")
    con = db.connect()
    assert ManualFile(source_id="manual", spec={"path": str(p)}).run(con) == 0
    p.write_text("series_id,ref_date,value,available_date,source\nwgc_cb_net_purchases_t,2026-04-01,166.5,2026-07-30,GDT Q2 2026\n")
    ManualFile(source_id="manual", spec={"path": str(p)}).run(con)
    assert db.get_series(con, "wgc_cb_net_purchases_t", as_of="2026-07-29").empty


def test_fred_fetcher_builds_url_and_parses():
    from pmdash.ingest.generic import FredSeries
    f = FredSeries(source_id="real_yield_10y", spec={"fred_id": "DFII10", "period": "day", "release_lag_days": 1})
    assert f.spec["url"] == "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
    df = f.parse(b"observation_date,DFII10\n2026-10-01,2.10\n2026-10-02,.\n2026-10-05,2.15\n")
    assert list(df.value) == [2.10, 2.15]


def test_unreachable_host_is_skipped_after_first_failure(monkeypatch):
    import socket
    from pmdash.ingest import runner
    from pmdash.ingest.base import DownloadError
    from pmdash.ingest.generic import FredSeries
    calls = []

    class Slow(FredSeries):
        def download(self):
            calls.append(self.source_id)
            raise DownloadError(f"{self.source_id}: timed out", socket.timeout("timed out"))

    fs = [Slow(source_id=f"s{i}", spec={"fred_id": f"X{i}"}) for i in range(3)]
    monkeypatch.setattr(runner, "build_fetchers", lambda *a, **k: fs)
    res = runner.fetch_all(db.connect())
    assert calls == ["s0"]
    assert "skipped" in res["s1"] and "skipped" in res["s2"]


def test_http_404_is_not_retried(monkeypatch):
    import urllib.error
    import urllib.request
    from pmdash.ingest.base import DownloadError
    n = []

    def fake(req, timeout=0):
        n.append(1)
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    f = CsvSeries(source_id="x", spec={"url": "https://example.org/x.csv"})
    try:
        f.download()
    except DownloadError as exc:
        assert not exc.host_down
    assert len(n) == 1


def test_fred_api_path_parses_json_and_keeps_key_out(monkeypatch):
    from pmdash.ingest.generic import FredSeries
    monkeypatch.setenv("FRED_API_KEY", "abcdef0123456789abcdef0123456789")
    f = FredSeries(source_id="real_yield_10y", spec={"fred_id": "DFII10", "period": "day", "release_lag_days": 1})
    seen = []

    def fake_download(self):
        seen.append(self.spec["url"])
        return b'{"observations":[{"date":"2026-10-01","value":"2.10"},{"date":"2026-10-02","value":"."}]}'

    monkeypatch.setattr(CsvSeries, "download", fake_download)
    con = db.connect()
    f.run(con)
    assert "api.stlouisfed.org" in seen[0] and "api_key=" in seen[0]
    assert "api_key" not in f.spec["url"]
    src = con.execute("SELECT DISTINCT source FROM observations").fetchone()[0]
    assert "api_key" not in src
    assert list(db.get_series(con, "real_yield_10y")) == [2.10]


def test_fred_without_key_gets_one_short_try(monkeypatch):
    from pmdash.ingest.generic import FredSeries
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    f = FredSeries(source_id="x", spec={"fred_id": "DFF"})
    assert f.retry["attempts"] == 1 and f.retry["timeout_seconds"] <= 15
