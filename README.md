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
