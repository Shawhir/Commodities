# Weekly summary (data to 2026-09)

_Descriptive, not predictive. This tool does not forecast prices or give instructions._

## Regime (gold, monthly closes)

| Currency | Close | Regime | 12m return | ER | Trend | 12-1 rule | 10m rule |
|---|---|---|---|---|---|---|---|
| CHF | 3,541 | Up | +21.3% | 0.34 | Flat | In | Out |
| USD | 4,319 | Sideways | +17.7% | 0.24 | Flat | In | Out |

## Stretch (percentiles since the float, floating-era windows)

**CHF**

| Measure | Value | Pct since 1971 (n) | Pct 10y (n) |
|---|---|---|---|
| dist_10m_avg | -1.6% | 33 (653) | 18 (120) |
| dist_3y_avg | +31.2% | 90 (627) | 83 (120) |
| dist_10y_avg | +90.5% | 97 (543) | 92 (120) |
| return_3y | +105.4% | 93 (626) | 95 (120) |
| fall_from_24m_high | -8.7% | 45 (639) | 10 (120) |

**USD**

| Measure | Value | Pct since 1971 (n) | Pct 10y (n) |
|---|---|---|---|
| dist_10m_avg | -4.6% | 19 (653) | 9 (120) |
| dist_3y_avg | +33.1% | 85 (627) | 82 (120) |
| dist_10y_avg | +107.8% | 91 (543) | 90 (120) |
| return_3y | +125.4% | 92 (626) | 92 (120) |
| fall_from_24m_high | -14.0% | 28 (639) | 2 (120) |

## Key lines (latest state per line)

| Line | Currency | State | Watching for break | Since | Close | Line value | Severity |
|---|---|---|---|---|---|---|---|
| gold_stretch_10y_p50 | CHF | intact | below | 2019-05-31 | 50.66 | 50 | watch |
| gold_stretch_10y_p50 | USD | intact | below | 2019-10-31 | 56.64 | 50 | watch |
| gold_mom_12_1 | USD | intact | below | 2023-08-31 | 0.1054 | 0 | important |
| gold_mom_12_1 | CHF | intact | below | 2024-03-31 | 0.002198 | 0 | important |
| gold_stretch_10y_p90 | CHF | intact | below | 2025-10-31 | 99.62 | 90 | watch |
| gold_stretch_10y_p90 | USD | intact | below | 2025-12-31 | 99.25 | 90 | watch |
| gold_round_5000 | CHF | intact | above | 2026-03-31 | 3,823 | 3,936 | info |
| gold_round_5000 | USD | intact | above | 2026-03-31 | 4,856 | 5,000 | info |
| gold_round_4000 | USD | intact | below | 2026-08-31 | 4,411 | 4,000 | info |
| gold_round_4000 | CHF | intact | below | 2026-08-31 | 3,562 | 3,230 | info |
| gold_regime | - | Sideways | - | 2026-09-30 | nan | nan | watch |
| gold_10m_avg | USD | intact | above | 2026-09-30 | 4,319 | 4,528 | important |
| gold_10m_avg | CHF | intact | above | 2026-09-30 | 3,541 | 3,598 | important |
- real_yield_jump: needs series DFII10 (not ingested yet)
- fed_hikes_priced: needs series fed_hikes_priced_12m (not ingested yet)

## Closest past months (groups with data)

6 matches; next-12-month USD outcomes from -26% to +41%, median +15%. Unconditional median since 1971: +5% (n=638). The closest matches point in opposite directions; the measures used do not separate them. Dropped (no data): fed_direction, dollar_chg_6m, breakeven_10y, cb_purchases_12m, etf_holdings_chg_6m, cftc_mm_pct.

| Month | Distance | Key moment | Next 12m USD | Next 12m CHF | Main differences |
|---|---|---|---|---|---|
| 2006-07 | 2.51 |  | +4.9% | +2.3% | distance from 10-month average: +13% then vs -5% now; oil (Brent) 12-month change: +28% then vs +68% now |
| 2011-03 | 2.71 | 2011 peak (6 months away) | +17.8% | +17.1% | USD/CHF 12-month change: -14% then vs +3% now; distance from 10-month average: +8% then vs -5% now |
| 2008-08 | 2.78 | Financial crisis liquidation (2 months away) | +13.1% | +11.5% | geopolitical risk percentile (10y): 41 then vs 85 now; USD/CHF 12-month change: -10% then vs +3% now |

## Not yet available

- Weekly-close regime reading: needs daily prices (phase 2).
- Silver, flows, positioning, stress, macro backdrop: not ingested yet (phase 2).
- Theme register and agent weekly read: phases 6 and 7.

## Data health

| Source | Latest month | Status |
|---|---|---|
| breakeven_10y | - | never succeeded |
| brent_monthly | 2026-09 | ok |
| cftc_cot | 2026-09 | ok |
| dollar_broad | - | never succeeded |
| fed_funds_eff | - | never succeeded |
| fed_target_upper | - | never succeeded |
| gold_usd_monthly | 2026-09 | ok |
| gold_vol | - | never succeeded |
| gpr_daily | 2026-10 | ok |
| gpr_monthly | 2026-09 | ok |
| manual_reports | - | ok |
| real_yield_10y | - | never succeeded |
| us_10y_yield_monthly | 2026-08 | stale (68 days) |
| us_core_cpi | - | never succeeded |
| us_cpi_fred | - | never succeeded |
| us_cpi_mirror | 2026-08 | stale (68 days) |
| us_payrolls | - | never succeeded |
| us_unemployment | - | never succeeded |
| usdchf_daily | 2026-10 | ok |
| usdchf_fred | - | never succeeded |
| usdchf_monthly | 2026-09 | ok |
| vix_daily_mirror | 2026-09 | stale (16 days) |
| vix_fred | - | never succeeded |
| wti_monthly | 2026-09 | ok |
