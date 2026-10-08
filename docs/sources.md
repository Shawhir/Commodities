# Data sources (phase 0)

Status as of 8 October 2026. **Verified** means it was downloaded, parsed and checked by this
codebase. **Candidate** means it is listed in the brief but has not been checked yet. The
build sandbox could not reach the FRED, SNB, CFTC, GPR or EPU hosts (connections were
refused at the network policy), so all of those are still candidates. Check them from the
machine that will run the tool.

## Verified

| Series id | Source | URL | Notes |
|---|---|---|---|
| `gold_usd_monthly` | GitHub `datasets/gold-prices` | https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv | 1833-01 to 2026-09, 2,325 rows. Columns `Date` (YYYY-MM), `Price`. Monthly averages; pre-1968 values are official fixed prices. Treated as available on the first day after month end. Research baseline only. |
| `usdchf_monthly` | GitHub `datasets/exchange-rates` | https://raw.githubusercontent.com/datasets/exchange-rates/main/data/monthly.csv | `Country == Switzerland`, 1971-01 to 2026-09, 669 rows. CHF per USD. Same availability rule. |

Frozen copies of both files as fetched on 2026-10-08 are in `tests/fixtures/` so the tests
and the seed study are reproducible offline.

## Candidates (not yet verified)

| Data | Candidate | Planned phase | Notes |
|---|---|---|---|
| Daily futures, all contract months | Databento (CME Globex) | 2 | Paid; open decision 2 |
| Prototype daily prices | yfinance | 2 | Unofficial; prototyping only |
| Daily FX | SNB data portal, FRED `DEXSZUS` | 2 | |
| Real yield, breakeven, dollar, VIX, GVZ | FRED `DFII10`, `T10YIE`, `DTWEXBGS`, `VIXCLS`, `GVZCLS` | 2 | `fredgraph.csv?id=` endpoint unreachable from the sandbox |
| CPI (purchasing-power view) | FRED `CPIAUCNS`; historical CPI before 1913 | 9 | Pre-1913 coverage to check |
| Fed funds futures path | CME FedWatch or derived from futures | 2 | Access to check |
| SNB policy rate, CHF indices, intervention | SNB data portal | 2 | |
| CFTC disaggregated COT | cftc.gov yearly zip files | 2 | |
| ETF holdings | Issuer pages, WGC | 2 | Check terms |
| COMEX stocks, margins | CME daily reports / notices | 2 | Check terms |
| Central bank purchases | WGC Goldhub, IMF IFS | 2 | Check terms |
| Swiss exports by destination | Swiss-Impex | 2 | |
| Shanghai premium | SGE and LBMA prices | 2 | LBMA licensing |
| GPR index (daily) | matteoiacoviello.com | 6 | |
| EPU index | policyuncertainty.com | 6 | |
| GDELT, curated RSS | | 6 | |

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
