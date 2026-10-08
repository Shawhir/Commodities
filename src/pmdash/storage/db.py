"""Point-in-time storage in a single DuckDB file.

Every observation carries ``ref_date`` (the period it describes) and
``available_date`` (when it could first have been known). A changed value for
the same ``ref_date`` is stored as a new vintage; nothing is overwritten.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    series_id      VARCHAR NOT NULL,
    ref_date       DATE    NOT NULL,
    available_date DATE    NOT NULL,
    value          DOUBLE  NOT NULL,
    source         VARCHAR NOT NULL,
    fetched_at     TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS data_health (
    source_id     VARCHAR PRIMARY KEY,
    last_attempt  TIMESTAMP,
    last_success  TIMESTAMP,
    last_failure  TIMESTAMP,
    last_error    VARCHAR,
    latest_ref_date DATE,
    rows_added    INTEGER
);
CREATE TABLE IF NOT EXISTS releases (
    report_id      VARCHAR NOT NULL,
    period         VARCHAR NOT NULL,     -- the period the release covers, e.g. 2026-08 or 2026-Q3
    expected_start DATE,
    expected_end   DATE,
    received_at    TIMESTAMP,
    status         VARCHAR NOT NULL,     -- expected | received | overdue | manual
    detail         VARCHAR,
    PRIMARY KEY (report_id, period)
);
CREATE TABLE IF NOT EXISTS triggers (
    trigger_id   VARCHAR PRIMARY KEY,
    line_id      VARCHAR NOT NULL,
    market       VARCHAR,
    currency     VARCHAR,
    state        VARCHAR NOT NULL,
    prev_state   VARCHAR,
    close_date   DATE    NOT NULL,
    close_value  DOUBLE,
    line_value   DOUBLE,
    severity     VARCHAR,
    alert        BOOLEAN,
    monthly_close BOOLEAN,
    created_at   TIMESTAMP NOT NULL
);
"""


def connect(path: str | Path = ":memory:") -> duckdb.DuckDBPyConnection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upsert_observations(con, series_id: str, df: pd.DataFrame, source: str,
                        fetched_at: datetime | None = None) -> int:
    """Insert rows whose value is new or changed versus the latest vintage.

    ``df`` needs columns ref_date, available_date, value. Returns rows added.
    """
    fetched_at = fetched_at or _now()
    new = df[["ref_date", "available_date", "value"]].copy()
    new["ref_date"] = pd.to_datetime(new["ref_date"]).dt.date
    new["available_date"] = pd.to_datetime(new["available_date"]).dt.date
    latest = con.execute(
        """
        SELECT ref_date, value FROM (
            SELECT ref_date, value,
                   row_number() OVER (PARTITION BY ref_date ORDER BY available_date DESC, fetched_at DESC) AS rn
            FROM observations WHERE series_id = ?
        ) WHERE rn = 1
        """,
        [series_id],
    ).df()
    if not latest.empty:
        latest["ref_date"] = pd.to_datetime(latest["ref_date"]).dt.date
        merged = new.merge(latest, on="ref_date", how="left", suffixes=("", "_old"))
        changed = merged["value_old"].isna() | ((merged["value"] - merged["value_old"]).abs() > 1e-12)
        new = merged.loc[changed, ["ref_date", "available_date", "value"]].copy()
        # A revision is only knowable when we saw it, not at the original release date.
        revised = merged.loc[changed, "value_old"].notna().to_numpy()
        if revised.any():
            seen = max(fetched_at.date(), *new.loc[revised, "available_date"])
            new.loc[revised, "available_date"] = seen
    if new.empty:
        return 0
    new.insert(0, "series_id", series_id)
    new["source"] = source
    new["fetched_at"] = fetched_at
    con.register("_new_obs", new)
    con.execute(
        "INSERT INTO observations SELECT series_id, ref_date, available_date, value, source, fetched_at FROM _new_obs"
    )
    con.unregister("_new_obs")
    return len(new)


def get_series(con, series_id: str, as_of: date | str | None = None,
               start: date | str | None = None, end: date | str | None = None) -> pd.Series:
    """Latest vintage of each ref_date that was available on or before ``as_of``."""
    as_of = pd.Timestamp(as_of).date() if as_of is not None else date.max
    df = con.execute(
        """
        SELECT ref_date, value FROM (
            SELECT ref_date, value,
                   row_number() OVER (PARTITION BY ref_date ORDER BY available_date DESC, fetched_at DESC) AS rn
            FROM observations WHERE series_id = ? AND available_date <= ?
        ) WHERE rn = 1 ORDER BY ref_date
        """,
        [series_id, as_of],
    ).df()
    s = pd.Series(df["value"].to_numpy(), index=pd.to_datetime(df["ref_date"]), name=series_id, dtype=float)
    if start is not None:
        s = s[s.index >= pd.Timestamp(start)]
    if end is not None:
        s = s[s.index <= pd.Timestamp(end)]
    return s


def get_monthly(con, series_id: str, as_of=None) -> pd.Series:
    """Series indexed by monthly Period."""
    s = get_series(con, series_id, as_of=as_of)
    s.index = s.index.to_period("M")
    return s


def record_health(con, source_id: str, ok: bool, error: str | None = None,
                  latest_ref_date=None, rows_added: int = 0) -> None:
    now = _now()
    con.execute("INSERT OR IGNORE INTO data_health (source_id) VALUES (?)", [source_id])
    if ok:
        con.execute(
            "UPDATE data_health SET last_attempt=?, last_success=?, latest_ref_date=?, rows_added=?, last_error=NULL WHERE source_id=?",
            [now, now, latest_ref_date, rows_added, source_id],
        )
    else:
        con.execute(
            "UPDATE data_health SET last_attempt=?, last_failure=?, last_error=? WHERE source_id=?",
            [now, now, (error or "")[:500], source_id],
        )


def health_table(con, stale_after_days: dict[str, int] | None = None, today: date | None = None) -> pd.DataFrame:
    df = con.execute("SELECT * FROM data_health ORDER BY source_id").df()
    today = today or date.today()
    stale_after_days = stale_after_days or {}

    def status(row):
        if pd.isna(row["last_success"]):
            return "never succeeded"
        limit = stale_after_days.get(row["source_id"])
        if limit and not pd.isna(row["latest_ref_date"]):
            age = (today - pd.Timestamp(row["latest_ref_date"]).date()).days
            if age > limit:
                return f"stale ({age} days)"
        if not pd.isna(row["last_failure"]) and row["last_failure"] > row["last_success"]:
            return "last attempt failed"
        return "ok"

    if not df.empty:
        df["status"] = df.apply(status, axis=1)
    return df
