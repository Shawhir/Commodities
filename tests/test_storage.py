from datetime import date

import pandas as pd

from pmdash.ingest.github_datasets import GoldMonthly
from pmdash.ingest.base import SchemaError
from pmdash.storage import db

import pytest


def _df(vals, ref=("2026-07-01", "2026-08-01"), avail=("2026-08-01", "2026-09-01")):
    return pd.DataFrame({"ref_date": list(ref), "available_date": list(avail), "value": vals})


def test_vintages_kept_and_point_in_time():
    con = db.connect()
    db.upsert_observations(con, "x", _df([1.0, 2.0]), "t", fetched_at=pd.Timestamp("2026-09-02").to_pydatetime())
    assert db.upsert_observations(con, "x", _df([1.0, 2.0]), "t") == 0          # unchanged: nothing stored
    db.upsert_observations(con, "x", _df([1.0, 2.5]), "t", fetched_at=pd.Timestamp("2026-10-01").to_pydatetime())
    assert con.execute("SELECT count(*) FROM observations").fetchone()[0] == 3
    assert db.get_series(con, "x").iloc[-1] == 2.5
    # before the revision was seen, the old vintage is what was known
    assert db.get_series(con, "x", as_of=date(2026, 9, 15)).iloc[-1] == 2.0
    # before release, nothing for August
    assert len(db.get_series(con, "x", as_of=date(2026, 8, 15))) == 1


def test_monthly_available_after_month_end(con):
    row = con.execute("SELECT available_date FROM observations WHERE series_id='gold_usd_monthly' "
                      "AND ref_date='2026-09-01'").fetchone()
    assert row[0] == date(2026, 10, 1)
    assert db.get_series(con, "gold_usd_monthly", as_of="2026-09-30").index[-1] == pd.Timestamp("2026-08-01")


def test_schema_validation_fails_loudly_and_records_health():
    con = db.connect()
    f = GoldMonthly(source_id="g", spec={"url": "x"})
    with pytest.raises(SchemaError):
        f.run(con, raw=b"Month,Value\n2026-01,1\n")
    h = db.health_table(con)
    assert h.loc[0, "status"] == "never succeeded"
    assert "SchemaError" in h.loc[0, "last_error"]
