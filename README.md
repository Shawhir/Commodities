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
| 2 | Flow, CFTC, ETF, COMEX, stress, curve/carry, daily prices | Not started |
| 3 | Key-level engine and trigger table | State machine, line builder for monthly data, trigger table, replays for 2011–2015 and 2026 |
| 4 | Testing framework | Section 8.3 reproduced; real cash returns, walk-forward and paper mode not started |
| 5–8 | Journal, allocation, geopolitics, analyst agent, linking and alerts | Not started (config placeholders only) |
| 9 | Watch-tier metals, purchasing-power view | Not started |
| 10 | Analogue finder | Section 8.4 reproduced; multi-group matching with dropped-measure reporting; out-of-sample test: **context only** on the data so far |

The reproduced numbers and the findings are in [data/research/README.md](data/research/README.md).

## Setup

```bash
pip install -e ".[app,dev]"
pmdash fetch                     # or: pmdash import-files tests/fixtures/gold_monthly_2026-10-08.csv tests/fixtures/usdchf_monthly_2026-10-08.csv
pmdash verify-snapshot           # phase 0 check of section 7
pmdash study                     # section 8 regime study -> data/research/
pmdash check-levels --alerts-only --start 2026-01
pmdash analogues                 # add --groups price_shape for the 8.4 seed
pmdash oos --groups price_shape  # out-of-sample test -> data/research/analogue_oos_summary.csv
pmdash summary                   # weekly summary (markdown)
streamlit run src/pmdash/app/streamlit_app.py
pytest
```

`python cli.py <command>` works without installing. Every command accepts `--as-of YYYY-MM-DD`
to see only data that was available on that date. The database defaults to `data/pmdash.duckdb`;
set `PMDASH_DB` to override it.

Example cron line (daily at 07:10): `10 7 * * * cd /path/to/repo && pmdash fetch && pmdash check-levels > /dev/null`

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
  digest/          weekly summary
  app/             thin Streamlit front end
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
