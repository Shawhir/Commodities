# Data sources (phase 0)

Status as of 8 October 2026. **Verified** means it was downloaded, parsed and checked by this
codebase. **Candidate** means it is listed in the brief but has not been checked yet. The
build sandbox could not reach the FRED, SNB, CFTC, GPR or EPU hosts (connections were
refused at the network policy), so all of those are still candidates. Check them from the
machine that will run the tool.

## Verified

All sources are configured in `config/sources.yaml`.

| Series id | Source | URL | Notes |
|---|---|---|---|
| `us_cpi_mirror` | BLS CPI-U via GitHub `datasets/cpi-us` | .../cpi-us/main/data/cpiai.csv | 1913-01 to 2026-08. Available 15 days after month end. |
| `us_10y_yield_monthly` | FRED GS10 via `datasets/bond-yields-us-10y` | .../monthly.csv | 1953-04 to 2026-08, monthly average |
| `vix_daily_mirror` | CBOE VIX via `datasets/finance-vix` | .../vix-daily.csv | 1990 to 2026-09-22 |
| `brent_monthly`, `wti_monthly` | EIA via `datasets/oil-prices` | .../brent-monthly.csv | From 1987 / 1986 |
| `usdchf_daily` | Fed H.10 via `datasets/exchange-rates` daily | .../daily.csv | 1971 to 2026-10-02. Available 7 days later (weekly release). |
| `gold_usd_monthly` | GitHub `datasets/gold-prices` | https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv | 1833-01 to 2026-09, 2,325 rows. Columns `Date` (YYYY-MM), `Price`. Monthly averages; pre-1968 values are official fixed prices. Treated as available on the first day after month end. Research baseline only. |
| `usdchf_monthly` | GitHub `datasets/exchange-rates` | https://raw.githubusercontent.com/datasets/exchange-rates/main/data/monthly.csv | `Country == Switzerland`, 1971-01 to 2026-09, 669 rows. CHF per USD. Same availability rule. |

Frozen copies of both files as fetched on 2026-10-08 are in `tests/fixtures/` so the tests
and the seed study are reproducible offline.

## Candidates: run on GitHub Actions

The build sandbox's network policy blocks these hosts (proxy 403), so their first live run will
be the scheduled workflow. Parsers follow the documented formats and are tested on synthetic
samples. A format surprise shows up in data health and does not stop the other sources.

| Data | Source id(s) | Endpoint |
|---|---|---|
| Real yield, breakeven, broad dollar, VIX, GVZ | `real_yield_10y`, `breakeven_10y`, `dollar_broad`, `vix_fred`, `gold_vol` | FRED `fredgraph.csv?id=DFII10` etc. (no key) |
| Fed funds effective and target upper bound | `fed_funds_eff`, `fed_target_upper` | FRED `DFF`, `DFEDTARU` |
| US CPI, core CPI, payrolls, unemployment | `us_cpi_fred`, `us_core_cpi`, `us_payrolls`, `us_unemployment` | FRED `CPIAUCNS`, `CPILFESL`, `PAYEMS`, `UNRATE` |
| Daily USD/CHF (official) | `usdchf_fred` | FRED `DEXSZUS` |
| CFTC disaggregated COT (gold, silver, platinum, copper) | `cftc_cot` | cftc.gov `fut_disagg_txt_{year}.zip`; history from 2006 with `pmdash backfill --cftc-years 20` |
| Geopolitical Risk Index, monthly and daily | `gpr_monthly`, `gpr_daily` | matteoiacoviello.com `.xls` files (needs `xlrd`) |

## Entered by hand

WGC Gold Demand Trends, the WGC central bank survey, the Silver Institute World Silver Survey,
IMF COFER and China's official PMI: see `data/manual/README.md`. Their terms rule out automated
download, or they come only as PDFs or web pages.

## Not configured yet

| Data | Candidate | Planned phase |
|---|---|---|
| Daily futures, all contract months | Databento (CME Globex) | 2; paid, open decision 2 |
| Fed funds futures path | CME FedWatch or derived from futures | 2 |
| SNB policy rate, CHF indices, intervention | SNB data portal (cube ids to confirm) | 2 |
| ETF holdings, COMEX stocks, margins | Issuer pages, WGC, CME | 2; check terms |
| Swiss exports by destination | Swiss-Impex | 2 |
| Shanghai premium | SGE and LBMA prices | 2; LBMA licensing |
| EPU index, GDELT, curated RSS | | 6 |

TradingView is not used: it has no public data API.

## Section 7 snapshot re-check

`pmdash verify-snapshot` compares each section 7 figure with the stored data. Results on the
2026-10-08 vintage:

| Item | Brief | Computed | Status |
|---|---|---|---|
| Sep 2026 monthly average | ~$4,300 / ~CHF 3,540 | $4,319 / CHF 3,541 | confirmed |
| Peak monthly average | ~$5,020, Feb 2026 | $5,020, Feb 2026 | confirmed |
| Distance from 10-month average | ~−5% | −4.6% | confirmed |
| Distance from 3-year average | ~+33%, 85th pct | +33.1%, 85th pct | confirmed |
| Distance from 10-year average | ~+108%, 91st pct | +107.8%, 91st pct | confirmed |
| 3-year return | ~+125%, 92nd pct | +125.4%, 92nd pct | confirmed |
| Regime | Sideways, +18%, ER 0.24 | Sideways, +17.7%, ER 0.24 | confirmed |
| 10-month rule / 12-1 rule | Out / In | Out / In | confirmed |
| 12-1 turns negative if ~$4,300 holds | Jan to Feb 2027 | signal turns on the Dec 2026 close, position changes Jan 2027 | confirmed |
| Intraday peak >$5,500, low $3,955, drawdown ~28% | | | not checkable from monthly averages; needs daily data |

The percentiles match only when the long averages are built from **floating-era prices
only** (so the 10-year average starts in August 1981). That is now the documented convention
in `indicators/stretch.py`.

Fed, central bank, ETF and geopolitics items in section 7 come from secondary sources and
are not checked here. They need the phase 2 and phase 6 feeds.
