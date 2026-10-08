"""Text store: one CSV per series under data/store/, committed to git.

GitHub Actions runs start on a fresh machine, so the DuckDB file is rebuilt from
these CSVs at the start of each run and written back at the end. Plain CSV keeps
every vintage visible in git diffs and survives any change of database engine.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

COLS = ["series_id", "ref_date", "available_date", "value", "source", "fetched_at"]


def save(con, store_dir: Path) -> int:
    """Write every series (all vintages) to <store_dir>/<series_id>.csv. Returns series count."""
    store_dir.mkdir(parents=True, exist_ok=True)
    ids = [r[0] for r in con.execute("SELECT DISTINCT series_id FROM observations ORDER BY 1").fetchall()]
    for sid in ids:
        df = con.execute(
            "SELECT * FROM observations WHERE series_id = ? ORDER BY ref_date, available_date, fetched_at", [sid]
        ).df()[COLS]
        df.to_csv(store_dir / f"{sid}.csv", index=False, date_format="%Y-%m-%d")
    for name, query in (("_data_health", "SELECT * FROM data_health ORDER BY source_id"),
                        ("_releases", "SELECT * FROM releases ORDER BY report_id, period")):
        con.execute(query).df().to_csv(store_dir / f"{name}.csv", index=False)
    return len(ids)


def load(con, store_dir: Path) -> int:
    """Replace DB contents with the CSV store. Returns series count."""
    if not store_dir.exists():
        return 0
    files = sorted(p for p in store_dir.glob("*.csv") if not p.name.startswith("_"))
    con.execute("DELETE FROM observations")
    for p in files:
        df = pd.read_csv(p, dtype={"series_id": str, "source": str})
        if df.empty:
            continue
        df["ref_date"] = pd.to_datetime(df["ref_date"]).dt.date
        df["available_date"] = pd.to_datetime(df["available_date"]).dt.date
        df["fetched_at"] = pd.to_datetime(df["fetched_at"])
        con.register("_load", df[COLS])
        con.execute("INSERT INTO observations SELECT * FROM _load")
        con.unregister("_load")
    for name, table in (("_data_health", "data_health"), ("_releases", "releases")):
        p = store_dir / f"{name}.csv"
        if p.exists() and p.stat().st_size > 0:
            df = pd.read_csv(p)
            if not df.empty:
                con.execute(f"DELETE FROM {table}")
                con.register("_load", df)
                con.execute(f"INSERT INTO {table} SELECT * FROM _load")
                con.unregister("_load")
    return len(files)
