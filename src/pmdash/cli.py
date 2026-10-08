"""Command-line entry points, run by cron or a systemd timer.

    pmdash fetch              download sources into DuckDB (--schedule daily|weekly|on_release)
    pmdash backfill           fetch every source once for full history
    pmdash store load|save    rebuild the DB from data/store/*.csv, or write it back
    pmdash reports calendar   what is due, received or overdue
    pmdash reports check      fetch due reports, record releases, summarise changes
    pmdash import-files G F   load the monthly gold and FX CSVs from disk (offline)
    pmdash verify-snapshot    phase 0: check section 7 figures against stored data
    pmdash study              reproduce the section 8 regime study, write data/research/
    pmdash check-levels       run the key-line state machine, store triggers
    pmdash analogues          analogue finder for the latest month (or --as-of)
    pmdash oos                analogue out-of-sample test since 2000
    pmdash summary            weekly summary as markdown
    pmdash export-html        dashboard as one self-contained HTML file
    pmdash health             data health table
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config, data
from .storage import db


def _con():
    return db.connect(config.db_path())


def _health(con):
    stale = {k: v.get("stale_after_days") for k, v in config.load("sources")["sources"].items()}
    return db.health_table(con, stale)


def cmd_fetch(args):
    from .ingest.runner import fetch_all
    con = _con()
    schedules = set(args.schedule.split(",")) if args.schedule else None
    ids = set(args.source.split(",")) if args.source else None
    results = fetch_all(con, schedules=schedules, ids=ids)
    for k, v in results.items():
        print(f"{k}: {v}")
    return 0 if all(not v.startswith("FAILED") for v in results.values()) else 1


def cmd_backfill(args):
    """Fetch every configured source once, including report sources, for full history."""
    from .ingest import runner
    con = _con()
    cfg = config.load("sources")
    if args.cftc_years is not None:
        cfg["sources"]["cftc_cot"]["years_back"] = args.cftc_years
    results = runner.fetch_all(con)
    for k, v in results.items():
        print(f"{k}: {v}")
    ok = sum(not v.startswith("FAILED") for v in results.values())
    print(f"\n{ok} of {len(results)} sources fetched. Failures are recorded in data health and do not stop the rest.")
    return 0


def cmd_store(args):
    from .storage import store
    con = _con()
    d = config.DATA_DIR / "store"
    if args.action == "load":
        print(f"loaded {store.load(con, d)} series from {d}")
    else:
        print(f"saved {store.save(con, d)} series to {d}")
    return 0


def cmd_reports(args):
    from datetime import date as _date, timedelta
    from .reports import calendar as cal
    from .reports.check import check, to_markdown
    con = _con()
    rcfg = config.load("reports")
    today = _date.fromisoformat(args.today) if args.today else _date.today()
    if args.action == "calendar":
        rows = cal.calendar(con, rcfg, today, back_days=args.back, ahead_days=args.days)
        print(f"{'window':<25} {'status':<10} {'period':<11} report")
        for r in rows:
            when = str(r.window_start) if r.window_start == r.window_end else f"{r.window_start} to {r.window_end}"
            print(f"{when:<25} {r.status:<10} {r.period:<11} {r.name}" + (f"  [{r.detail}]" if r.detail else ""))
        return 0
    rows = check(con, rcfg, today, fetch=not args.no_fetch)
    upcoming = [r for r in cal.calendar(con, rcfg, today, back_days=0, ahead_days=30) if r.status == "upcoming"]
    md = to_markdown(rows, upcoming)
    if args.out:
        Path(args.out).write_text(md)
    print(md)
    return 0


def cmd_import(args):
    print(data.import_files(_con(), Path(args.gold), Path(args.fx)))
    return 0


def cmd_verify(args):
    from .testing.snapshot_check import check
    gold, fx = data.load_monthly(_con(), args.as_of)
    df = check(gold, fx, args.month)
    print(df.to_string())
    return 0


def cmd_study(args):
    from .testing.seed_study import run_study, write_outputs
    gold, fx = data.load_monthly(_con(), args.as_of)
    cfg = dict(config.load("thresholds"), float_start=config.load("markets")["markets"]["gold"]["float_start"])
    st = run_study(gold, fx, cfg)
    print(f"Window {st['window'][0]} to {st['window'][1]}, cash at 0%, cost 0.2% per switch\n")
    print(st["summary"].round(4).to_string(), "\n")
    print("Per regime (USD, 12-1 momentum vs buy and hold):")
    print(st["per_regime"].round(4).to_string(), "\n")
    print("Regime shares since the float:", st["regime_shares_since_float"].round(3).to_dict(), "\n")
    print(st["sideways_episodes"].to_string(index=False))
    if not args.no_write:
        for p in write_outputs(st, config.DATA_DIR / "research"):
            print("wrote", p)
    return 0


def cmd_levels(args):
    from .levels.lines import evaluate_market, latest_states
    con = _con()
    gold, fx = data.load_monthly(con, args.as_of)
    th = config.load("thresholds")
    trans, notes = evaluate_market("gold", {"USD": gold, "CHF": (gold * fx).dropna()}, config.load("levels"),
                                   th, usdchf=fx, since=args.since)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for t in trans:
        con.execute(
            "INSERT OR IGNORE INTO triggers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [t.trigger_id, t.line_id, t.market, t.currency, t.state, t.prev_state, pd.Timestamp(t.date).date(),
             None if pd.isna(t.close) else t.close, None if pd.isna(t.line_value) else t.line_value,
             t.severity, t.alert, t.monthly_close, now],
        )
    df = pd.DataFrame([t.to_dict() for t in trans])
    if args.new_alerts_out:
        _write_new_alerts(df, args.start, Path(args.new_alerts_out))
    if args.alerts_only and len(df):
        df = df[df.alert]
    if args.start and len(df):
        df = df[df.date >= pd.Timestamp(args.start)]
    if args.end and len(df):
        df = df[df.date <= pd.Timestamp(args.end)]
    with pd.option_context("display.width", 200, "display.max_rows", 500):
        cols = ["date", "line_id", "currency", "prev_state", "state", "watching", "close", "line_value",
                "severity", "alert"]
        print(df[cols].to_string(index=False) if len(df) else "no transitions")
        print("\nLatest state per line:")
        print(latest_states(trans)[["state", "watching", "date", "close", "line_value"]].to_string())
    for n in notes:
        print("note:", n)
    return 0


def _write_new_alerts(df: pd.DataFrame, start: str | None, out: Path) -> None:
    """Write alerts not sent before (ledger: data/store/_alerts_sent.csv) as markdown; append them."""
    ledger = config.DATA_DIR / "store" / "_alerts_sent.csv"
    sent = set(pd.read_csv(ledger)["trigger_id"]) if ledger.exists() else set()
    new = df[df.alert & ~df.trigger_id.isin(sent)] if len(df) else df
    if start is not None and len(new):
        new = new[new.date >= pd.Timestamp(start)]
    out.write_text("")
    if not len(new):
        return
    lines = ["## Key line alerts", "", "Descriptive, not predictive. Alerts fire only on confirmed or failed breaks, judged on closes.", "",
             "| Close | Line | Currency | Change | Close value | Line value | Severity |", "|---|---|---|---|---|---|---|"]
    for r in new.itertuples():
        cur = r.currency if isinstance(r.currency, str) else "-"
        close = "-" if pd.isna(r.close) else f"{r.close:,.4g}"
        line = "-" if pd.isna(r.line_value) else f"{r.line_value:,.4g}"
        lines.append(f"| {pd.Timestamp(r.date).date()} | {r.line_id} | {cur} | {r.prev_state} to {r.state} "
                     f"| {close} | {line} | {r.severity} |")
    out.write_text("\n".join(lines) + "\n")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    rows = pd.DataFrame({"trigger_id": new.trigger_id, "sent_on": str(pd.Timestamp.today().date())})
    rows.to_csv(ledger, mode="a", header=not ledger.exists(), index=False)


def _finder_args():
    a = config.load("thresholds")["analogues"]
    return dict(weights=a["group_weights"], candidate_start=a["candidate_start"],
                exclude_recent=a["exclude_recent_months"], collapse=a["collapse_months"], top_n=a["top_n"],
                categorical_penalty=a["categorical_penalty"], standardise=a["standardise"]), a["groups"]


def _groups(arg, all_groups):
    if not arg:
        return all_groups
    return {g: all_groups[g] for g in arg.split(",")}


def cmd_analogues(args):
    from .analogues import finder, state
    from .regime.labeller import label_from_config
    gold, fx = data.load_monthly(_con(), args.as_of)
    kw, groups = _finder_args()
    st = state.build(gold, fx, data.load_macro(_con(), args.as_of))
    target = args.month or str(gold.index[-1])
    res = finder.find(st, target, _groups(args.groups, groups), prices={"USD": gold, "CHF": (gold * fx).dropna()},
                      regime=label_from_config(gold, config.load("thresholds"))["regime"],
                      key_moments=pd.read_csv(config.DATA_DIR / "key_moments.csv"), **kw)
    print(f"Target {res.target}; measures used: {', '.join(res.used_measures)}\n")
    for m in res.matches:
        o = m.outcomes
        print(f"{m.month}  d={m.distance:.2f}  12m USD {o.get('fwd_12m_usd', float('nan')):+.0%}  "
              f"24m USD {o.get('fwd_24m_usd', float('nan')):+.0%}  12m CHF {o.get('fwd_12m_chf', float('nan')):+.0%}  "
              f"{m.key_moment or ''}")
        print("    differs: " + "; ".join(m.differences))
    print("\n" + res.summary())
    print("Descriptive, not predictive.")
    return 0


def cmd_oos(args):
    from .analogues import finder, state
    gold, fx = data.load_monthly(_con(), args.as_of)
    kw, groups = _finder_args()
    st = state.build(gold, fx, data.load_macro(_con(), args.as_of))
    df = finder.out_of_sample(st, gold, _groups(args.groups, groups), start=args.start, **kw)
    from .analogues.finder import oos_summary
    summ = oos_summary(df)
    print(f"Out-of-sample months: {summ['months']} (overlapping 12-month outcomes, so not independent)")
    print(f"Actual inside matched range: {summ['in_range']:.0%}")
    print(f"Matched median closer than unconditional median: {summ['median_beats_baseline']:.0%}")
    print(f"Direction right: matched median {summ['direction_right']:.0%} vs unconditional "
          f"{summ['baseline_direction_right']:.0%}")
    print("Label:", summ["label"])
    if args.out:
        df.to_csv(args.out, index=False, float_format="%.4f")
        print("wrote", args.out)
    if not args.no_write:
        path = config.DATA_DIR / "research" / "analogue_oos_summary.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with_data = [g for g, ms in _groups(args.groups, groups).items() if any(m in st.columns for m in ms)]
        row = pd.DataFrame([{"groups": "+".join(with_data), "start": args.start,
                             "run_on": str(pd.Timestamp.today().date()), **summ}])
        if path.exists():
            old = pd.read_csv(path)
            row = pd.concat([old[old.groups != row.groups[0]], row])
        row.to_csv(path, index=False, float_format="%.4f")
        print("wrote", path)
    return 0


def cmd_summary(args):
    from .digest.summary import build, to_markdown
    con = _con()
    gold, fx = data.load_monthly(con, args.as_of)
    md = to_markdown(build(gold, fx, _health(con), data.load_macro(con, args.as_of)))
    if args.out:
        Path(args.out).write_text(md)
        print("wrote", args.out)
    else:
        print(md)
    return 0


def cmd_export_html(args):
    from .export.html import build_payload, render
    con = _con()
    gold, fx = data.load_monthly(con, args.as_of)
    from datetime import date as _date
    from .reports import calendar as cal
    today = _date.fromisoformat(args.as_of) if args.as_of else _date.today()
    rels = cal.calendar(con, config.load("reports"), today, back_days=45, ahead_days=45)
    stored = {(r[0], r[1]): r[2] for r in con.execute("SELECT report_id, period, detail FROM releases").fetchall()}
    reports = [{**r.as_dict(), "detail": stored.get((r.report_id, r.period)) or r.detail} for r in rels]
    fx_daily = db.get_series(con, "usdchf_daily", as_of=args.as_of)
    payload = build_payload(gold, fx, _health(con), data.load_macro(con, args.as_of), include_oos=not args.no_oos,
                            reports=reports, fx_daily=fx_daily if len(fx_daily) else None)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(payload, fragment=args.fragment))
    print("wrote", out)
    return 0


def cmd_health(args):
    print(_health(_con()).to_string(index=False))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pmdash", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--as-of", default=None, help="point-in-time date (only data available by then)")
        p.set_defaults(fn=fn)
        return p

    p = add("fetch", cmd_fetch, "download sources")
    p.add_argument("--schedule", help="comma-separated: daily, weekly, on_release (default: all)")
    p.add_argument("--source", help="comma-separated source ids")
    p = add("backfill", cmd_backfill, "fetch every source once for full history")
    p.add_argument("--cftc-years", type=int, default=None, help="years of CFTC history (disaggregated starts 2006)")
    p = add("store", cmd_store, "load the DB from data/store/*.csv, or save it there")
    p.add_argument("action", choices=["load", "save"])
    p = add("reports", cmd_reports, "release calendar and report checks")
    p.add_argument("action", choices=["calendar", "check"])
    p.add_argument("--days", type=int, default=60, help="calendar: days ahead")
    p.add_argument("--back", type=int, default=14, help="calendar: days back")
    p.add_argument("--today", help="pretend today is YYYY-MM-DD")
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--out", help="also write the markdown summary here")
    p = add("import-files", cmd_import, "load monthly CSVs from disk")
    p.add_argument("gold")
    p.add_argument("fx")
    p = add("verify-snapshot", cmd_verify, "check section 7 against stored data")
    p.add_argument("--month", default="2026-09")
    p = add("study", cmd_study, "reproduce the section 8 regime study")
    p.add_argument("--no-write", action="store_true")
    p = add("check-levels", cmd_levels, "run key-line state machine")
    p.add_argument("--since", default="1971-08")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--alerts-only", action="store_true")
    p.add_argument("--new-alerts-out", help="write alerts not sent before as markdown (and record them)")
    p = add("analogues", cmd_analogues, "analogue finder")
    p.add_argument("--month")
    p.add_argument("--groups", help="comma-separated groups, e.g. price_shape")
    p = add("oos", cmd_oos, "analogue out-of-sample test")
    p.add_argument("--start", default="2000-01")
    p.add_argument("--groups")
    p.add_argument("--out")
    p.add_argument("--no-write", action="store_true")
    p = add("summary", cmd_summary, "weekly summary markdown")
    p.add_argument("--out")
    p = add("export-html", cmd_export_html, "write the dashboard as one self-contained HTML file")
    p.add_argument("--out", default=str(config.DATA_DIR / "dashboard.html"))
    p.add_argument("--fragment", action="store_true", help="omit the <html> wrapper (for hosts that add their own)")
    p.add_argument("--no-oos", action="store_true", help="skip the out-of-sample test (faster)")
    add("health", cmd_health, "data health")
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
