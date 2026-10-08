"""Fetcher base: retry, raw-response cache, schema validation, health record.

Each fetcher fails on its own; a failure is recorded in ``data_health`` and
does not stop other sources.
"""
from __future__ import annotations

import io
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .. import config
from ..storage import db


class SchemaError(ValueError):
    pass


@dataclass
class Fetcher:
    source_id: str
    spec: dict
    retry: dict = field(default_factory=dict)
    raw_dir: Path = field(default_factory=lambda: config.DATA_DIR / "raw")

    # --- subclasses implement ---
    def parse(self, raw: bytes) -> pd.DataFrame:
        """Return columns ref_date, available_date, value."""
        raise NotImplementedError

    # --- shared behaviour ---
    def download(self) -> bytes:
        attempts = self.retry.get("attempts", 4)
        backoff = self.retry.get("backoff_seconds", [2, 4, 8, 16])
        timeout = self.retry.get("timeout_seconds", 30)
        last: Exception | None = None
        for i in range(attempts):
            try:
                req = urllib.request.Request(self.spec["url"], headers={"User-Agent": "pmdash/0.1"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read()
            except Exception as exc:  # noqa: BLE001 - recorded and re-raised below
                last = exc
                if i < attempts - 1:
                    time.sleep(backoff[min(i, len(backoff) - 1)])
        raise RuntimeError(f"{self.source_id}: download failed after {attempts} attempts: {last}")

    def cache_raw(self, raw: bytes) -> Path:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.raw_dir / f"{self.source_id}_{stamp}.raw"
        path.write_bytes(raw)
        return path

    @staticmethod
    def validate(df: pd.DataFrame) -> pd.DataFrame:
        missing = {"ref_date", "available_date", "value"} - set(df.columns)
        if missing:
            raise SchemaError(f"missing columns {missing}")
        if df.empty:
            raise SchemaError("no rows")
        if df["value"].isna().any():
            raise SchemaError("null values")
        if df["ref_date"].duplicated().any():
            raise SchemaError("duplicate ref_date")
        if (pd.to_datetime(df["available_date"]) < pd.to_datetime(df["ref_date"])).any():
            raise SchemaError("available_date before ref_date")
        return df

    def run(self, con, raw: bytes | None = None) -> int:
        """Fetch (or use given raw bytes), store, record health. Re-raises on failure."""
        try:
            if raw is None:
                raw = self.download()
                self.cache_raw(raw)
            df = self.validate(self.parse(raw))
            added = db.upsert_observations(con, self.source_id, df, source=self.spec.get("url", "file"))
            db.record_health(con, self.source_id, ok=True,
                             latest_ref_date=pd.to_datetime(df["ref_date"]).max().date(), rows_added=added)
            return added
        except Exception as exc:
            db.record_health(con, self.source_id, ok=False, error=f"{type(exc).__name__}: {exc}")
            raise


def monthly_available_date(ref: pd.Series, lag_days: int = 1) -> pd.Series:
    """Monthly averages are known only after the month ends."""
    return ref + pd.offsets.MonthEnd(0) + pd.Timedelta(days=lag_days)


def read_csv_bytes(raw: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw))
