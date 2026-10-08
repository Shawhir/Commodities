"""Weekly summary: the page the tool opens to. Built as plain data, rendered thinly."""
from __future__ import annotations

from datetime import date

import pandas as pd

from .. import DISCLAIMER, config
from ..analogues import finder, state
from ..indicators.stretch import stretch_table
from ..indicators.trend import ma_signal, momentum_12_1, trend_reading
from ..levels.lines import evaluate_market, latest_states
from ..regime.labeller import label_from_config


def build(gold_usd: pd.Series, usdchf: pd.Series, health: pd.DataFrame | None = None) -> dict:
    th = config.load("thresholds")
    mk = config.load("markets")
    float_start = mk["markets"]["gold"]["float_start"]
    gold_chf = (gold_usd * usdchf).dropna()
    as_of = gold_usd.index[-1]

    regime_rows = []
    for cur, p in (("CHF", gold_chf), ("USD", gold_usd)):
        lab = label_from_config(p, th).iloc[-1]
        regime_rows.append({
            "market": "gold", "currency": cur, "month": str(p.index[-1]), "close": float(p.iloc[-1]),
            "regime": lab["regime"], "return_12m": float(lab["ret"]), "efficiency_ratio": float(lab["er"]),
            "trend": trend_reading(p),
            "momentum_12_1": float(momentum_12_1(p).iloc[-1]),
            "rule_mom": "In" if momentum_12_1(p).iloc[-1] > 0 else "Out",
            "rule_10m": "In" if ma_signal(p).iloc[-1] == 1 else "Out",
        })
    regime_df = pd.DataFrame(regime_rows)

    levels_cfg = config.load("levels")
    trans, notes = evaluate_market("gold", {"USD": gold_usd, "CHF": gold_chf}, levels_cfg, th,
                                   usdchf=usdchf, since=float_start)
    states = latest_states(trans)
    recent = [t.to_dict() for t in trans if pd.Timestamp(t.date) >= as_of.to_timestamp() - pd.DateOffset(months=3)]

    a = th["analogues"]
    st = state.build(gold_usd, usdchf)
    km = pd.read_csv(config.DATA_DIR / "key_moments.csv")
    res = finder.find(st, as_of, a["groups"], a["group_weights"],
                      prices={"USD": gold_usd, "CHF": gold_chf},
                      regime=label_from_config(gold_usd, th)["regime"],
                      candidate_start=a["candidate_start"], exclude_recent=a["exclude_recent_months"],
                      collapse=a["collapse_months"], top_n=a["top_n"],
                      categorical_penalty=a["categorical_penalty"], standardise=a["standardise"],
                      key_moments=km, baseline_start=float_start)

    return {
        "as_of": str(as_of), "built": str(date.today()), "disclaimer": DISCLAIMER,
        "regime": regime_df,
        "stretch": {"CHF": stretch_table(gold_chf, float_start), "USD": stretch_table(gold_usd, float_start)},
        "level_states": states, "recent_transitions": recent, "level_notes": notes,
        "analogues": res, "health": health,
        "pending": [
            "Weekly-close regime reading: needs daily prices (phase 2).",
            "Silver, flows, positioning, stress, macro backdrop: not ingested yet (phase 2).",
            "Theme register and agent weekly read: phases 6 and 7.",
        ],
    }


def _pct(x: float) -> str:
    return "n/a" if pd.isna(x) else f"{x:+.1%}"


def to_markdown(s: dict) -> str:
    out = [f"# Weekly summary (data to {s['as_of']})", "", f"_{s['disclaimer']}_", "", "## Regime (gold, monthly closes)", ""]
    out.append("| Currency | Close | Regime | 12m return | ER | Trend | 12-1 rule | 10m rule |")
    out.append("|---|---|---|---|---|---|---|---|")
    for _, r in s["regime"].iterrows():
        out.append(f"| {r.currency} | {r.close:,.0f} | {r.regime} | {_pct(r.return_12m)} | {r.efficiency_ratio:.2f} "
                   f"| {r.trend} | {r.rule_mom} | {r.rule_10m} |")
    out += ["", "## Stretch (percentiles since the float, floating-era windows)", ""]
    for cur, t in s["stretch"].items():
        out.append(f"**{cur}**")
        out.append("")
        out.append("| Measure | Value | Pct since 1971 (n) | Pct 10y (n) |")
        out.append("|---|---|---|---|")
        for m, r in t.iterrows():
            out.append(f"| {m} | {_pct(r.value)} | {r.pct_since_float:.0f} ({int(r.n_since_float)}) | {r.pct_10y:.0f} ({int(r.n_10y)}) |")
        out.append("")
    out += ["## Key lines (latest state per line)", ""]
    ls = s["level_states"]
    if len(ls):
        out.append("| Line | Currency | State | Watching for break | Since | Close | Line value | Severity |")
        out.append("|---|---|---|---|---|---|---|---|")
        for (lid, cur), r in ls.iterrows():
            cur = cur if isinstance(cur, str) else "-"
            watch = r.watching if isinstance(r.watching, str) else "-"
            out.append(f"| {lid} | {cur} | {r.state} | {watch} | {pd.Timestamp(r.date).date()} | {r.close:,.4g} | {r.line_value:,.4g} | {r.severity} |")
    for n in s["level_notes"]:
        out.append(f"- {n}")
    res = s["analogues"]
    out += ["", "## Closest past months (groups with data)", "", res.summary(), ""]
    out.append("| Month | Distance | Key moment | Next 12m USD | Next 12m CHF | Main differences |")
    out.append("|---|---|---|---|---|---|")
    for m in res.matches[:3]:
        out.append(f"| {m.month} | {m.distance:.2f} | {m.key_moment or ''} | {_pct(m.outcomes.get('fwd_12m_usd'))} "
                   f"| {_pct(m.outcomes.get('fwd_12m_chf'))} | {'; '.join(m.differences)} |")
    out += ["", "## Not yet available", ""] + [f"- {p}" for p in s["pending"]]
    if s.get("health") is not None and len(s["health"]):
        out += ["", "## Data health", "", "| Source | Latest month | Status |", "|---|---|---|"]
        for _, r in s["health"].iterrows():
            out.append(f"| {r.source_id} | {pd.Timestamp(r.latest_ref_date):%Y-%m} | {r.status} |")
    return "\n".join(out) + "\n"
