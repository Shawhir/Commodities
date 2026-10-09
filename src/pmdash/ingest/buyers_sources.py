"""Sources for the "who's buying" section: central bank gold (IMF), gold trade flows (UN Comtrade)
and the largest gold fund's holdings (SPDR Gold Shares). Each was checked from GitHub Actions
with `pmdash probe` (October 2026); the development sandbox cannot reach these hosts.
"""
from __future__ import annotations

import io
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd

from ..storage import db
from .base import DownloadError, Fetcher, SchemaError
from .generic import frame

OZ_PER_TONNE = 32150.7466


class ImfGold(Fetcher):
    """Central bank gold holdings, fine troy ounces -> tonnes, monthly, from the IMF's IRFCL
    dataset (new data API). One request covers every configured country.

    Key layout: COUNTRY.INDICATOR.SECTOR.FREQUENCY; IRFCLDT1_IRFCL56V_FTO is gold (including
    gold deposits and swaps) in fine troy ounces, monetary authorities (S1XS1311).
    """

    URL = ("https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IRFCL/{countries}.IRFCLDT1_IRFCL56V_FTO.S1XS1311.M"
           "?startPeriod={start}")

    def __post_init__(self):
        cc = self.spec["countries"]              # ISO3 -> short code used in series ids
        self.spec = {**self.spec, "url": self.URL.format(countries="+".join(cc), start=self.spec.get("start", "2000-01"))}

    def parse(self, raw: bytes) -> pd.DataFrame:
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise SchemaError(f"IMF answer is not XML: {raw[:200]!r}") from e
        out = []
        for s in root.iter():
            if not s.tag.endswith("Series"):
                continue
            iso3 = s.attrib.get("COUNTRY")
            code = self.spec["countries"].get(iso3)
            if not code:
                continue
            scale = float(s.attrib.get("UNIT_MULT", 0) or 0)   # values come in units; SCALE is display only
            dates, vals = [], []
            for o in s:
                if not o.tag.endswith("Obs"):
                    continue
                tp, v = o.attrib.get("TIME_PERIOD", ""), o.attrib.get("OBS_VALUE")
                m = re.match(r"(\d{4})-M(\d{2})", tp)
                if not m or v in (None, "", "NaN"):
                    continue
                dates.append(f"{m.group(1)}-{m.group(2)}-01")
                vals.append(float(v) * 10 ** scale / OZ_PER_TONNE)
            if dates:
                f = frame(dates, vals, {"period": "month", "release_lag_days": self.spec.get("release_lag_days", 40)})
                f["series_id"] = f"cb_gold_t_{code}"
                out.append(f)
        if not out:
            raise SchemaError("IMF answer has no gold series")
        return pd.concat(out, ignore_index=True)


class ComtradeMonthly(Fetcher):
    """Monthly gold trade (HS 7108) from UN Comtrade's free preview API, net weight -> tonnes.

    The free API takes one month per request and limits bursts, so this asks only for months not
    yet stored (plus the latest few again, for revisions), with a pause between requests.
    spec: reporter, flow (X/M), partners {code: suffix} or partner_total suffix, prefix,
    backfill_months, recheck_months.
    """

    URL = ("https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode={reporter}&period={period}"
           "&cmdCode=7108&flowCode={flow}{partner}")

    def _months(self, con) -> list[str]:
        today = pd.Period(date.today(), "M")
        last = today - int(self.spec.get("lag_months", 2))
        first = last - int(self.spec.get("backfill_months", 36)) + 1
        if con is not None:
            probe_sid = f"{self.spec['prefix']}_{next(iter(self.spec['partners'].values()))}"
            s = db.get_series(con, probe_sid)
            if len(s):
                first = max(first, pd.Period(s.index.max(), "M") - int(self.spec.get("recheck_months", 3)) + 1)
        return [p.strftime("%Y%m") for p in pd.period_range(first, last, freq="M")]

    def run(self, con, raw: bytes | None = None) -> int:
        self._con = con
        return super().run(con, raw)

    def download(self) -> bytes:
        partners = self.spec["partners"]
        pq = "" if self.spec.get("all_partners") else "&partnerCode=" + ",".join(str(k) for k in partners)
        if len(partners) == 1:
            pq = f"&partnerCode={next(iter(partners))}"
        got, last_err = [], None
        for period in self._months(getattr(self, "_con", None)):
            url = self.URL.format(reporter=self.spec["reporter"], period=period, flow=self.spec["flow"], partner=pq)
            for attempt in range(4):
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "pmdash/0.1"})
                    with urllib.request.urlopen(req, timeout=40) as r:
                        got.append(json.loads(r.read()))
                    break
                except urllib.error.HTTPError as e:
                    last_err = e
                    if e.code == 429:
                        time.sleep(6 * (attempt + 1))
                        continue
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    time.sleep(3)
            time.sleep(float(self.spec.get("pause_seconds", 3)))
        if not got:
            raise DownloadError(f"{self.source_id}: no months downloaded: {last_err}", last_err)
        self.spec = {**self.spec, "url": self.URL.format(reporter=self.spec["reporter"], period="<month>",
                                                         flow=self.spec["flow"], partner=pq)}
        return json.dumps(got).encode()

    def parse(self, raw: bytes) -> pd.DataFrame:
        pages = json.loads(raw)
        rows = []
        for page in pages:
            for d in page.get("data") or []:
                code = d.get("partnerCode")
                suffix = self.spec["partners"].get(code, self.spec["partners"].get(str(code)))
                if suffix is None:
                    continue
                kg = d.get("netWgt") or d.get("qty")
                if kg is None:
                    continue
                rows.append({"series_id": f"{self.spec['prefix']}_{suffix}", "date": f"{d['period'][:4]}-{d['period'][4:6]}-01",
                             "value": float(kg) / 1000.0})
        if not rows:
            raise SchemaError("Comtrade answers had no matching rows")
        df = pd.DataFrame(rows).groupby(["series_id", "date"], as_index=False)["value"].sum()
        out = []
        for sid, part in df.groupby("series_id"):
            f = frame(part["date"], part["value"], {"period": "month", "release_lag_days": self.spec.get("release_lag_days", 75)})
            f["series_id"] = sid
            out.append(f)
        return pd.concat(out, ignore_index=True)


class GldHoldings(Fetcher):
    """SPDR Gold Shares (GLD) daily holdings in tonnes, from the issuer's historical archive
    (an Excel workbook). The column holding tonnes is found by name."""

    def parse(self, raw: bytes) -> pd.DataFrame:
        try:
            sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None, header=None)
        except Exception as e:  # noqa: BLE001
            raise SchemaError(f"GLD archive is not a readable workbook: {e}") from e
        for name, df in sheets.items():
            for r in range(min(15, len(df))):
                hdr = [str(x).strip().lower() for x in df.iloc[r].tolist()]
                t_col = next((i for i, h in enumerate(hdr) if "tonnes" in h), None)
                d_col = next((i for i, h in enumerate(hdr) if h == "date" or h.startswith("date")), None)
                if t_col is None or d_col is None:
                    continue
                body = df.iloc[r + 1:, [d_col, t_col]].copy()
                body.columns = ["date", "tonnes"]
                body["date"] = pd.to_datetime(body["date"], errors="coerce", dayfirst=True)
                body["tonnes"] = pd.to_numeric(body["tonnes"].astype(str).str.replace(",", ""), errors="coerce")
                body = body.dropna()
                body = body[body["tonnes"] > 0]
                if len(body) > 100:
                    return frame(body["date"], body["tonnes"], {"period": "day", "release_lag_days": 1})
        raise SchemaError(f"no Date/Tonnes columns found in sheets {list(sheets)[:5]}")
