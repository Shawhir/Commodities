# Report figures entered by hand

Some reports matter for gold but can't be downloaded automatically: their terms forbid scraping,
or they only come as PDFs. Enter their headline figures in `report_figures.csv`. The daily run
loads them like any other series, with `available_date` set to the publication date, so they
are point-in-time like everything else.

| Report | Where | What to copy | series_id |
|---|---|---|---|
| WGC Gold Demand Trends (quarterly) | gold.org, Goldhub (free account), "Gold Demand Trends" data file | Central bank net purchases, ETF flows, total demand, tonnes, per quarter | `wgc_cb_net_purchases_t`, `wgc_etf_flows_t`, `wgc_total_demand_t` |
| WGC Central Bank Gold Reserves Survey (annual, usually June) | gold.org | Share of central banks expecting global official gold reserves to rise over the next 12 months | `wgc_cb_survey_increase_pct` |
| Silver Institute World Silver Survey (annual, usually April) | silverinstitute.org | Market balance (surplus/deficit), million oz | `si_silver_deficit_moz` |
| IMF COFER (quarterly) | data.imf.org (COFER) | US dollar share of allocated reserves, % | `imf_cofer_usd_share_pct` |
| China official PMI (monthly, last day of month) | stats.gov.cn | Manufacturing PMI | `cn_nbs_pmi` |

The Goldhub data file holds the full quarterly history back to 2010. Pasting that history once
fills the backfill. Use the release date of each quarter's report as `available_date`, or the
download date if you only have the latest edition. In that case the history is marked as known
only from that date, which is honest but limits backtests until editions build up.

The release calendar (`config/reports.yaml`) shows when each is due. Once its window opens,
`pmdash reports check` lists it under "enter by hand".
