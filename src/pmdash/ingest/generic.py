"""Config-driven fetchers: CSV (GitHub mirrors, FRED), Excel (GPR index), CFTC COT, manual files.

Availability: ``available_date`` is when a value could first have been known.
- period "month": period end + ``release_lag_days`` (CPI ~15, monthly averages 1).
- period "day": the day itself + ``release_lag_days`` (daily closes 0, weekly-published FX 7).
"""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd

from .base import Fetcher, SchemaError


def _available(ref: pd.Series, period: str, lag_days: int) -> pd.Series:
    if period == "month":
        return ref + pd.offsets.MonthEnd(0) + pd.Timedelta(days=lag_days)
    if period == "quarter":
        return ref + pd.offsets.QuarterEnd(0) + pd.Timedelta(days=lag_days)
    if period == "year":
        return ref + pd.offsets.YearEnd(0) + pd.Timedelta(days=lag_days)
    return ref + pd.Timedelta(days=lag_days)


def frame(dates, values, spec: dict) -> pd.DataFrame:
    period = spec.get("period", "day")
    ref = pd.to_datetime(pd.Series(dates), format=spec.get("date_format"))
    if period == "month":
        ref = ref.dt.to_period("M").dt.to_timestamp()
    elif period == "quarter":
        ref = ref.dt.to_period("Q").dt.to_timestamp()
    elif period == "year":
        ref = ref.dt.to_period("Y").dt.to_timestamp()
    vals = pd.to_numeric(pd.Series(values), errors="coerce")
    df = pd.DataFrame({"ref_date": ref.to_numpy(), "value": vals.to_numpy()})
    df = df.dropna().drop_duplicates("ref_date", keep="last").sort_values("ref_date").reset_index(drop=True)
    if spec.get("scale"):
        df["value"] = df["value"] * float(spec["scale"])
    df["available_date"] = _available(df["ref_date"], period, int(spec.get("release_lag_days", 0)))
    return df


class CsvSeries(Fetcher):
    """Any CSV with a date column and a value column, optionally filtered by column values."""

    def parse(self, raw: bytes) -> pd.DataFrame:
        df = pd.read_csv(io.BytesIO(raw), na_values=[".", ""])
        date_col = self.spec.get("date_col") or df.columns[0]
        value_col = self.spec.get("value_col") or df.columns[1]
        for col in (date_col, value_col):
            if col not in df.columns:
                raise SchemaError(f"column {col!r} missing; got {list(df.columns)}")
        for col, val in (self.spec.get("filter") or {}).items():
            df = df[df[col] == val]
        return frame(df[date_col], df[value_col], self.spec)


class FredSeries(CsvSeries):
    """FRED graph CSV (no API key): first column is the date, second the series."""

    def __post_init__(self):
        sid = self.spec["fred_id"]
        self.spec = {"url": f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", **self.spec}

    def parse(self, raw: bytes) -> pd.DataFrame:
        df = pd.read_csv(io.BytesIO(raw), na_values=[".", ""])
        if df.shape[1] < 2:
            raise SchemaError(f"unexpected FRED columns {list(df.columns)}")
        return frame(df.iloc[:, 0], df.iloc[:, 1], self.spec)


class ExcelSeries(Fetcher):
    """Excel file (e.g. the Caldara-Iacoviello GPR index). Needs xlrd for .xls, openpyxl for .xlsx."""

    def parse(self, raw: bytes) -> pd.DataFrame:
        df = pd.read_excel(io.BytesIO(raw), sheet_name=self.spec.get("sheet", 0))
        date_col, value_col = self.spec["date_col"], self.spec["value_col"]
        if date_col not in df.columns or value_col not in df.columns:
            raise SchemaError(f"columns {date_col!r}/{value_col!r} missing; got {list(df.columns)[:12]}")
        return frame(df[date_col], df[value_col], self.spec)


class CftcDisaggregated(Fetcher):
    """CFTC disaggregated futures-only COT, yearly zip files.

    Produces, per configured market: managed-money net (long - short), its long and short legs,
    open interest, and producer/merchant net. Report dates are Tuesdays; data is published the
    following Friday, so available_date = report date + 3 days.
    """

    URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
    COLS = {
        "mm_net": ("M_Money_Positions_Long_All", "M_Money_Positions_Short_All"),
        "prod_net": ("Prod_Merc_Positions_Long_All", "Prod_Merc_Positions_Short_All"),
    }

    def years(self) -> list[int]:
        this = date.today().year
        return list(range(this - int(self.spec.get("years_back", 0)), this + 1))

    def download(self) -> bytes:
        parts = []
        for y in self.years():
            self.spec = {**self.spec, "url": self.URL.format(year=y)}
            parts.append(super().download())
        return b"\x00ZIPSEP\x00".join(parts)

    @staticmethod
    def _read_zip(blob: bytes) -> pd.DataFrame:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = z.namelist()[0]
            with z.open(name) as fh:
                return pd.read_csv(fh, low_memory=False)

    def parse(self, raw: bytes) -> pd.DataFrame:
        frames = [self._read_zip(b) for b in raw.split(b"\x00ZIPSEP\x00") if b]
        df = pd.concat(frames, ignore_index=True)
        df.columns = [c.strip() for c in df.columns]
        need = {"Report_Date_as_YYYY-MM-DD", "CFTC_Contract_Market_Code", "Open_Interest_All",
                *self.COLS["mm_net"], *self.COLS["prod_net"]}
        missing = need - set(df.columns)
        if missing:
            raise SchemaError(f"CFTC columns missing: {sorted(missing)}")
        df["CFTC_Contract_Market_Code"] = df["CFTC_Contract_Market_Code"].astype(str).str.strip().str.zfill(6)
        out = []
        for market, code in self.spec["markets"].items():
            m = df[df["CFTC_Contract_Market_Code"] == str(code).zfill(6)].copy()
            if m.empty:
                continue
            ref = pd.to_datetime(m["Report_Date_as_YYYY-MM-DD"])
            series = {
                f"cftc_{market}_mm_net": m[self.COLS["mm_net"][0]] - m[self.COLS["mm_net"][1]],
                f"cftc_{market}_mm_long": m[self.COLS["mm_net"][0]],
                f"cftc_{market}_mm_short": m[self.COLS["mm_net"][1]],
                f"cftc_{market}_prod_net": m[self.COLS["prod_net"][0]] - m[self.COLS["prod_net"][1]],
                f"cftc_{market}_oi": m["Open_Interest_All"],
            }
            for sid, vals in series.items():
                f = frame(ref, vals, {"period": "day", "release_lag_days": 3})
                f["series_id"] = sid
                out.append(f)
        if not out:
            raise SchemaError("no configured CFTC markets found")
        return pd.concat(out, ignore_index=True)


class ManualFile(Fetcher):
    """Figures typed or exported by hand from reports whose terms forbid scraping (WGC, Silver Institute).

    CSV columns: series_id, ref_date, value, available_date, source. ``available_date`` is the
    report's publication date; ``source`` names the report and edition.
    """

    def download(self) -> bytes:
        with open(self.spec["path"], "rb") as fh:
            return fh.read()

    def parse(self, raw: bytes) -> pd.DataFrame:
        df = pd.read_csv(io.BytesIO(raw), comment="#")
        need = {"series_id", "ref_date", "value", "available_date", "source"}
        if not need <= set(df.columns):
            raise SchemaError(f"manual file needs columns {sorted(need)}")
        df = df.dropna(subset=["value"])         # an empty template is fine: nothing entered yet
        return df[["series_id", "ref_date", "available_date", "value"]]
