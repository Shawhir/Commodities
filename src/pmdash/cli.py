"""Command-line entry points, run by cron or a systemd timer.

    pmdash fetch              download sources into DuckDB
    pmdash import-files G F   load the monthly gold and FX CSVs from disk (offline)
    pmdash verify-snapshot    phase 0: check section 7 figures against stored data
    pmdash study              reproduce the section 8 regime study, write data/research/
    pmdash check-levels       run the key-line state machine, store triggers
    pmdash analogues          analogue finder for the latest month (or --as-of)
    pmdash oos                analogue out-of-sample test since 2000
    pmdash summary            weekly summary as markdown
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
    results = fetch_all(con)
    for k, v in results.items():
        print(f"{k}: {v}")
    return 0 if all(not v.startswith("FAILED") for v in results.values()) else 1


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
    st = state.build(gold, fx)
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
    st = state.build(gold, fx)
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
    md = to_markdown(build(gold, fx, _health(con)))
    if args.out:
        Path(args.out).write_text(md)
        print("wrote", args.out)
    else:
        print(md)
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

    add("fetch", cmd_fetch, "download all sources")
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
    add("health", cmd_health, "data health")
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
