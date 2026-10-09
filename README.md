# Precious metals dashboard (pmdash)

A personal, local tool for a Swiss-based investor that tracks gold and silver in CHF and USD.
It labels the regime, watches key price lines, compares today with history, and records
decisions against written rules. **Descriptive, not predictive.** It does not forecast prices,
place trades or give instructions. The full brief is the project spec.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Source verification, section 7 snapshot re-check | Done for the two monthly datasets; other sources listed as candidates in [docs/sources.md](docs/sources.md) |
| 1 | Skeleton, point-in-time DuckDB storage, config, long history import, USD/CHF, trend, regime labeller, weekly summary, data health | Done (macro backdrop waits on FRED access) |
| 2 | Flow, CFTC, ETF, COMEX, stress, curve/carry, daily prices | Macro backfill (CPI from 1913, 10y yield from 1953, VIX, oil, daily USD/CHF); FRED, CFTC and GPR fetchers ready for GitHub Actions; flow indicators not started |
| 3 | Key-level engine and trigger table | State machine, line builder for monthly data, trigger table, replays for 2011–2015 and 2026 |
| 4 | Testing framework | Section 8.3 reproduced; real cash returns, walk-forward and paper mode not started |
| 5–8 | Journal, allocation, geopolitics, analyst agent, linking and alerts | Release calendar and report checks (9.6) with revisions; alerts as GitHub issues; journal, allocation, themes and agent not started |
| 9 | Watch-tier metals, purchasing-power view | Not started |
| 10 | Analogue finder | Section 8.4 reproduced; multi-group matching with dropped-measure reporting; out-of-sample test: **context only** on the data so far |

The reproduced numbers and the findings are in [data/research/README.md](data/research/README.md).

## Setup

```bash
pip install -e ".[app,dev]"
pmdash store load                # rebuild the DB from data/store/*.csv (the committed history)
pmdash fetch                     # or: pmdash import-files tests/fixtures/gold_monthly_2026-10-08.csv tests/fixtures/usdchf_monthly_2026-10-08.csv
pmdash verify-snapshot           # phase 0 check of section 7
pmdash study                     # section 8 regime study -> data/research/
pmdash check-levels --alerts-only --start 2026-01
pmdash analogues                 # add --groups price_shape for the 8.4 seed
pmdash oos --groups price_shape  # out-of-sample test -> data/research/analogue_oos_summary.csv
pmdash summary                   # weekly summary (markdown)
pmdash reports calendar          # what's due, received or overdue
pmdash reports check             # fetch what's due, record releases and revisions
pmdash export-html               # the dashboard as one self-contained file -> data/dashboard.html
streamlit run src/pmdash/app/streamlit_app.py
pytest
```

`python cli.py <command>` works without installing. Every command accepts `--as-of YYYY-MM-DD`
to see only data that was available on that date. The database defaults to `data/pmdash.duckdb`;
set `PMDASH_DB` to override it.

Example cron line (daily at 07:10): `10 7 * * * cd /path/to/repo && pmdash fetch && pmdash check-levels > /dev/null && pmdash export-html`

The HTML dashboard needs no server: open `data/dashboard.html` in a browser. It loads fonts
from Google Fonts when online and falls back to system fonts offline. Every number on it is
computed by the modules above; the template only lays them out and draws the charts.

After each daily and weekly run the workflow also publishes it to GitHub Pages at
https://shawhir.github.io/Commodities/ (one-time setup: Settings -> Pages -> Source: GitHub Actions).

## Scheduled runs (GitHub Actions)

`.github/workflows/pmdash.yml` runs the tool on GitHub's machines:

| When (UTC) | What |
|---|---|
| Daily 05:10 | Fetch prices and macro, check key lines, rebuild `data/dashboard.html` and `data/weekly_summary.md` |
| Weekdays 12:50 and 13:50 | US 08:30 ET releases (CPI, jobs), one run for each side of daylight saving |
| Weekdays 18:20 and 19:20 | FOMC 14:00 ET |
| Fridays 20:50 and 21:50 | CFTC Commitments of Traders |
| Mondays 06:30 | Weekly sources (GPR) and the weekly summary |
| By hand ("Run workflow") | `daily`, `release`, `weekly`, or `backfill` (full history including 20 years of CFTC) |

Each run loads the history from `data/store/*.csv`, runs `pmdash reports check` (it fetches
only what the calendar says is due), and commits the store back. It opens a GitHub issue for any
new confirmed or failed key-line break; a ledger in `data/store/_alerts_sent.csv` stops repeats.
The release calendar is `config/reports.yaml`; check the FOMC dates each year. Run
`pmdash reports calendar` to see what's due.

First-time setup on GitHub:

1. Settings → Actions → General: allow actions, and set **Workflow permissions** to
   **Read and write** (the workflow commits data back and opens alert issues).
2. Scheduled runs only fire from the default branch.
3. Run the workflow once by hand with `backfill` (Actions → pmdash → Run workflow).

## Layout

```
config/            markets, sources, thresholds, levels, themes, agent, allocation (YAML)
src/pmdash/
  storage/db.py    point-in-time observations (ref_date, available_date, vintages), data health, triggers
  ingest/          fetchers with retry, raw cache, schema checks, isolated failures
  indicators/      trend (12-1 momentum, 10-month average), stretch (percentiles, floating-era windows)
  regime/          section 8.1 labeller and sideways episodes
  levels/          close-based state machine (intact/approaching/broken/confirmed/failed) and line builder
  analogues/       state vectors, finder, out-of-sample test
  testing/         backtest, seed study, snapshot check
  reports/         release calendar, report checks, revisions
  digest/          weekly summary
  app/             thin Streamlit front end
  export/          static HTML dashboard (template.html + JSON payload from the modules above)
data/store/        the point-in-time history as CSV, one file per series (committed; rebuilt into DuckDB each run)
data/manual/       figures typed in from reports that can't be downloaded automatically
data/key_moments.csv, data/events.csv (header only, filled in phase 6), data/research/
tests/             pytest; fixtures are frozen copies of the verified datasets
```

## Decision brief

The dashboard and the weekly summary open with a decision brief (`src/pmdash/digest/brief.py`).
It lists your trend rules with the exact next-month average that would flip each one, and the
price ranges that would make next month Up, Sideways or Down. It also shows the nearest key
lines, what is pulling on gold (each factor with its usual effect), conflicts between readings,
the next releases, and what it can't cover yet. It states conditions, never instructions, and a
check rejects the brief if instruction language appears.

### Rule review (October 2026)

A review of the rules from a Swiss holder's point of view changed five things:

1. **Dollar signal for every view.** Both rules are decided on gold's dollar monthly average,
   because gold trades in dollars; franc-priced signals switched twice as often for worse results.
   Franc results apply the dollar signal. The rule lines in `config/levels.yaml` carry
   `currencies: [USD]`.
2. **Main switch and warning light.** Rule 1 (12-1 momentum) is the main switch. Rule 2 (the
   10-month average) is shown as a warning light: acted on alone, it lost money in choppy markets
   (2020-22, 2026) once tested at real prices.
3. **Realistic test.** `testing/seed_study.realistic` decides on monthly averages and trades at
   real month-end closes (COMEX front month, from 2001). The long 1972 table on monthly averages
   stays as the section 8 reproduction, labelled as smoothed.
4. **Cash earns interest.** Time out of gold earns the US 3-month T-bill rate (FRED `TB3MS`) and
   the Swiss 3-month rate (FRED `IR3TIB01CHM156N`, OECD, from mid-1999; negative 2015-22).
5. **Costs by holding.** `backtest.costs` in `config/thresholds.yaml` sets a one-way cost per
   switch for a fund, bars and coins; the page has a switch between them.

## Who's buying and central bank targets

Two sections (`src/pmdash/history/buyers.py`, config in `config/buyers.yaml`):

- **Who's buying**: a card per buyer group (central banks, China, India, US, Europe, Switzerland
  as the refining hub, Turkey and the Middle East), each labelled steady, fickle, cushion or hub,
  with its latest free figures, what to watch, what can be seen in advance, and dated events.
- **Central bank buying and stated targets**: holdings and 12-month buying from official monthly
  figures, gold's share of reserves at today's price, progress against the few stated targets
  (typed in by hand, marked "check source"), a "what if" table for emerging-market banks moving to
  a higher gold share (at today's price and +/-20%, since a higher price shrinks the gap), and the
  walk-forward honesty test of heavy buying against gold's next 12 months.

It deliberately does not estimate "how long the price has left": most demand has no target,
share targets are partly met by the price itself, much buying is unreported, and fund flows can
outweigh a year of central bank buying.

Sources (all free, no key beyond FRED's): IMF IRFCL data API (gold in fine troy ounces),
IMF via FRED (reserves excluding gold), UN Comtrade preview API (HS 7108 trade), SPDR Gold
Shares archive, CFTC. They were checked from GitHub Actions with `pmdash probe`
(`config/probe.yaml`); new sources are fetched with full history by the workflow job `sources`.

## Weighed-up odds, educated guess, history counts and technical picture

- **Weighed-up odds** (top of the page, `src/pmdash/history/odds.py`): one probability each for
  rising (+10% or more), sideways and falling (-10% or worse) over 12 months, weighing 17 measures
  at once. Tested walk-forward since 2000; the shown odds blend the model with gold's normal odds
  by whatever mix scored best in that test, so an unproven model stays close to normal odds. It
  lists what tips the odds each way. The owner relaxed the brief's "no combined score" and "no
  forecasting" rules on 8 October 2026 for this view. News enters only via the GPR index.

- **Educated guess** (top of the page): for 1, 3 and 5 years, the middle half of past outcomes
  after situations like today, applied to today's price, next to the same range for any month,
  with a trust rating. This is history's range, not a forecast model, and it says so. (The brief's
  "no forecasting" rule was relaxed by the owner on 8 October 2026 for this ranged view.)
- **What happened after setups like this**: counts for today's setups at 3, 6 and 12 months,
  with separate spells and a walk-forward honesty test (`src/pmdash/history/base_rates.py`).
- **Technical picture**: daily gold and silver (Yahoo Finance futures, unofficial) with RSI,
  MACD, Bollinger bands, 50/200-day averages, ATR, the past year's range and volume, each with
  the same counts and honesty test (`src/pmdash/indicators/technical.py`). On random prices about
  1 in 25 signals still passes the test, so a single pass is weak evidence.

## Design notes

- **Closes, not touches.** Lines are judged on closes with a buffer. With only monthly
  research data, every close is a monthly close, so a break is confirmed on the same close.
  Daily data (phase 2) will separate *broken* from *confirmed* with the same engine.
- Manual lines carry `active_from`, so a replay never judges a line before it existed.
- Two-sided lines (moving averages, momentum zero, stretch percentiles) flip the watched
  side once a confirmed break has held through the fail window. Each transition records
  which side it is watching.
- The analogue finder never fills missing measures. Absent groups are listed as dropped.
  Distances weight groups equally whatever their size; with one group the distance is plain
  Euclidean (the 8.4 seed).
