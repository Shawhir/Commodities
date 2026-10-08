"""Fetchers for the verified GitHub ``datasets`` monthly files (section 6.1)."""
from __future__ import annotations

import pandas as pd

from .base import Fetcher, SchemaError, monthly_available_date, read_csv_bytes


class GoldMonthly(Fetcher):
    """datasets/gold-prices data/monthly.csv: Date (YYYY-MM), Price (USD/oz)."""

    def parse(self, raw: bytes) -> pd.DataFrame:
        df = read_csv_bytes(raw)
        if list(df.columns[:2]) != ["Date", "Price"]:
            raise SchemaError(f"unexpected columns {list(df.columns)}")
        ref = pd.to_datetime(df["Date"], format="%Y-%m")
        return pd.DataFrame({
            "ref_date": ref,
            "available_date": monthly_available_date(ref, self.spec.get("release_lag_days", 1)),
            "value": pd.to_numeric(df["Price"], errors="raise"),
        })


class FxMonthly(Fetcher):
    """datasets/exchange-rates data/monthly.csv: Date, Country, Exchange rate."""

    def parse(self, raw: bytes) -> pd.DataFrame:
        df = read_csv_bytes(raw)
        expected = {"Date", "Country", "Exchange rate"}
        if not expected <= set(df.columns):
            raise SchemaError(f"unexpected columns {list(df.columns)}")
        df = df[df["Country"] == self.spec.get("country", "Switzerland")].dropna(subset=["Exchange rate"])
        ref = pd.to_datetime(df["Date"]).dt.to_period("M").dt.to_timestamp()
        return pd.DataFrame({
            "ref_date": ref.to_numpy(),
            "available_date": monthly_available_date(ref, self.spec.get("release_lag_days", 1)).to_numpy(),
            "value": pd.to_numeric(df["Exchange rate"], errors="raise").to_numpy(),
        })


FETCHERS = {
    "github_gold_monthly": GoldMonthly,
    "github_fx_monthly": FxMonthly,
}
