"""Decision brief: what the rules say now, what would change them, and what is pulling on gold.

Everything here is computed from stored data. It states conditions ("the 10-month rule turns In
if October's average is above X"), never instructions. A test scans the rendered text for
instruction language, as the agent validator in the brief will.

Prices are monthly averages (the research series), so "close" means the month's average until
daily closes are ingested.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ..indicators.trend import ma_signal, momentum_12_1
from ..regime.labeller import label

FORBIDDEN = ("buy", "sell", "should", "recommend", "target price", "price target", "go long", "go short")


def _month_name(p: pd.Period) -> str:
    return p.strftime("%B %Y")


def ordinal(x: float) -> str:
    n = int(round(x))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# --- 1. trend rules ----------------------------------------------------------------------------

def momentum_rule(p: pd.Series, horizon: int = 3) -> dict:
    """12-1 momentum now, and for each of the next closes either its known value or the price
    that would flip it. Momentum at close t+k = p[t+k-1] / p[t+k-12] - 1."""
    t = len(p) - 1
    now = float(momentum_12_1(p).iloc[-1])
    state = "In" if now > 0 else "Out"
    steps = []
    for k in range(1, horizon + 1):
        month = p.index[-1] + k
        num_i, den_i = t + k - 1, t + k - 12
        den = float(p.iloc[den_i])
        if num_i <= t:
            val = float(p.iloc[num_i]) / den - 1
            steps.append({"month": str(month), "known": True, "value": val, "state": "In" if val > 0 else "Out",
                          "text": f"{_month_name(month)} close: already fixed at {val:+.1%} "
                                  f"({'In' if val > 0 else 'Out'}), from {_month_name(p.index[num_i])}'s average"})
        else:
            needed_month = p.index[-1] + (num_i - t)
            flip = "below" if state == "In" else "above"
            steps.append({"month": str(month), "known": False, "threshold": den, "depends_on": str(needed_month),
                          "text": f"{_month_name(month)} close: turns {'Out' if state == 'In' else 'In'} if "
                                  f"{_month_name(needed_month)}'s average is {flip} {den:,.0f}"})
    hold = float(p.iloc[-1])
    turn = None
    q = p.copy()
    for k in range(1, 13):
        q.loc[p.index[-1] + k] = hold
        v = momentum_12_1(q).iloc[-1]
        if (v > 0) != (now > 0):
            turn = str(p.index[-1] + k)
            break
    return {"rule": "12-1 momentum", "state": state, "value": now, "steps": steps,
            "if_flat": f"If prices stay at {hold:,.0f}, it turns {'Out' if state == 'In' else 'In'} on the "
                       f"{_month_name(pd.Period(turn, 'M'))} close" if turn else
                       f"If prices stay at {hold:,.0f}, it does not change within 12 months"}


def ma_rule(p: pd.Series, window: int = 10) -> dict:
    """10-month rule now, and the next month's average that would flip it.
    In next month if P > (sum of last window-1 + P) / window, i.e. P > mean of the last window-1."""
    state = "In" if ma_signal(p, window).iloc[-1] == 1 else "Out"
    ma = float(p.rolling(window).mean().iloc[-1])
    threshold = float(p.iloc[-(window - 1):].mean())
    nxt = p.index[-1] + 1
    flip = "above" if state == "Out" else "below"
    return {"rule": f"{window}-month average", "state": state, "value": float(p.iloc[-1] / ma - 1), "average": ma,
            "threshold": threshold, "month": str(nxt),
            "text": f"Turns {'In' if state == 'Out' else 'Out'} if {_month_name(nxt)}'s average is {flip} "
                    f"{threshold:,.0f} (today's 10-month average: {ma:,.0f})"}


# --- 2. regime boundaries ----------------------------------------------------------------------

def regime_boundaries(p: pd.Series, cfg: dict) -> dict:
    """Range of next month's average that gives each regime label (grid search, 0.1% steps)."""
    r = cfg["regime"]
    last = float(p.iloc[-1])
    nxt = p.index[-1] + 1
    grid = last * np.arange(0.60, 1.60, 0.001)
    labels = []
    for price in grid:
        q = pd.concat([p.iloc[-(r["lookback_months"] + 1):], pd.Series([price], index=[nxt])])
        labels.append(label(q, r["lookback_months"], r["er_min"], r["up_return_min"], r["down_return_max"])["regime"].iloc[-1])
    ranges = []
    start = 0
    for i in range(1, len(grid) + 1):
        if i == len(grid) or labels[i] != labels[start]:
            ranges.append({"regime": labels[start], "low": float(grid[start]), "high": float(grid[i - 1])})
            start = i
    now = label(p, r["lookback_months"], r["er_min"], r["up_return_min"], r["down_return_max"]).iloc[-1]
    # boundaries halfway between adjacent grid ranges
    cuts = [(ranges[i]["high"] + ranges[i + 1]["low"]) / 2 for i in range(len(ranges) - 1)]
    parts = []
    for i, x in enumerate(ranges):
        lo = f"{cuts[i - 1]:,.0f}" if i > 0 else None
        hi = f"{cuts[i]:,.0f}" if i < len(cuts) else None
        span = f"below {hi}" if lo is None and hi else f"above {lo}" if hi is None and lo else f"{lo} to {hi}" if lo else "any level"
        parts.append(f"{x['regime']} {span}")
    for i, c in enumerate(cuts):
        ranges[i]["high_cut"] = c
        ranges[i + 1]["low_cut"] = c
    return {"now": now["regime"], "er": float(now["er"]), "ret": float(now["ret"]), "month": str(nxt), "ranges": ranges,
            "text": f"{_month_name(nxt)} average: " + "; ".join(parts)}


# --- 4. pressures --------------------------------------------------------------------------------

def pressures(state_row: pd.Series, macro: dict, as_of: pd.Period) -> list[dict]:
    """Backdrop readings with the effect they usually have on gold (themes.yaml), by fixed thresholds."""
    out = []

    def add(factor, reading, effect, why, theme):
        out.append({"factor": factor, "reading": reading, "usual_effect": effect, "why": why, "theme": theme})

    fed = state_row.get("fed_direction")
    if isinstance(fed, str):
        eff = {"hiking": "headwind", "cutting": "support", "on hold": "neutral"}[fed]
        rate = macro.get("fed_rate")
        lvl = f" (policy rate {rate.dropna().iloc[-1]:.2f}%)" if rate is not None and len(rate.dropna()) else ""
        add("Fed direction", f"{fed}{lvl}", eff, "Higher policy rates raise the cost of holding a non-yielding asset", "fed_real_rates")
    tips = macro.get("real_yield_tips")
    if tips is not None and len(tips.dropna()) > 6:
        t = tips.dropna()
        chg = t.iloc[-1] - t.iloc[-7]
        eff = "headwind" if chg > 0.25 else "support" if chg < -0.25 else "neutral"
        add("10-year real yield (TIPS)", f"{t.iloc[-1]:.2f}%, {chg:+.2f} pp over 6 months", eff,
            "Rising real yields usually weigh on gold; falling ones help", "fed_real_rates")
    d = state_row.get("dollar_chg_6m")
    if d is not None and not pd.isna(d):
        add("Broad dollar", f"{d:+.1%} over 6 months", "headwind" if d > 0.03 else "support" if d < -0.03 else "neutral",
            "A stronger dollar usually lowers the dollar price of gold", "fed_real_rates")
    g = state_row.get("gpr_pct")
    if g is not None and not pd.isna(g):
        add("Geopolitical risk", f"{ordinal(g)} percentile of 10 years", "support" if g >= 80 else "neutral",
            "High geopolitical risk tends to lift safe-haven demand; the effect often fades when tensions ease", "middle_east_iran")
    o = state_row.get("oil_chg_12m")
    if o is not None and not pd.isna(o):
        add("Oil (Brent)", f"{o:+.0%} over 12 months", "mixed" if abs(o) >= 0.3 else "neutral",
            "An oil surge lifts inflation hedging demand, but can also push the Fed to hike", "middle_east_iran")
    c = state_row.get("cftc_mm_pct")
    if c is not None and not pd.isna(c):
        mm = macro.get("cftc_gold_mm")
        trend = ""
        if mm is not None and len(mm.dropna()) > 2:
            m = mm.dropna()
            trend = f", {'falling' if m.iloc[-1] < m.iloc[-2] else 'rising'} vs last month"
        eff = "crowded" if c >= 90 else "washed out" if c <= 10 else "neutral"
        add("Speculative positioning (CFTC managed money)", f"{ordinal(c)} percentile of 3 years{trend}", eff,
            "Crowded longs can unwind sharply; washed-out positioning leaves room to rebuild", "cb_diversification")
    v = state_row.get("vix_pct")
    if v is not None and not pd.isna(v):
        add("Equity stress (VIX)", f"{ordinal(v)} percentile of 10 years", "mixed" if v >= 80 else "neutral",
            "Stress can lift safe-haven demand, or force selling of gold to raise cash", "fed_real_rates")
    u = state_row.get("usdchf_chg_12m")
    if u is not None and not pd.isna(u):
        add("Swiss franc vs dollar", f"USD/CHF {u:+.1%} over 12 months",
            "lowers CHF returns" if u < -0.03 else "raises CHF returns" if u > 0.03 else "neutral",
            "A stronger franc cuts the CHF value of dollar-priced gold", "chf_snb")
    cpi = state_row.get("cpi_yoy")
    if cpi is not None and not pd.isna(cpi):
        add("US inflation", f"{cpi:.1%} y/y (published a month late)", "mixed" if cpi > 0.03 else "neutral",
            "High inflation supports gold as a hedge, but keeps the Fed hawkish", "fed_real_rates")
    return out


# --- 5. conflicts ----------------------------------------------------------------------------------

def conflicts(rules: dict, regimes: dict, stretch: dict, press: list[dict]) -> list[str]:
    out = []
    for cur, r in rules.items():
        if r["momentum"]["state"] != r["ma"]["state"]:
            out.append(f"In {cur}, the two trend rules disagree: 12-1 momentum is {r['momentum']['state']}, "
                       f"the 10-month rule is {r['ma']['state']}.")
    labs = {cur: x["now"] for cur, x in regimes.items()}
    if len(set(labs.values())) > 1:
        out.append("The regime label differs by currency: " + ", ".join(f"{v} in {k}" for k, v in labs.items()) +
                   ". The section 8 study labels on USD.")
    for cur, s in stretch.items():
        if s is not None and s >= 90 and rules.get(cur, {}).get("ma", {}).get("state") == "Out":
            out.append(f"In {cur}, gold is stretched ({ordinal(s)} percentile vs its 10-year average) "
                       f"while the 10-month rule is Out: far above the long-run trend, below the short-run one.")
    heads = [p["factor"] for p in press if p["usual_effect"] == "headwind"]
    sups = [p["factor"] for p in press if p["usual_effect"] == "support"]
    if heads and sups:
        out.append("Backdrop pulls both ways. Usual headwinds: " + ", ".join(heads) +
                   ". Usual supports: " + ", ".join(sups) + ".")
    return out


# --- assemble ------------------------------------------------------------------------------------

def build(gold: pd.Series, fx: pd.Series, state: pd.DataFrame, macro: dict, lines: list[dict],
          reports: list[dict], stretch_pct: dict, thresholds: dict, today: date | None = None,
          allocation: dict | None = None, journal_open: int | None = None) -> dict:
    today = today or date.today()
    chf = (gold * fx).dropna()
    series = {"CHF": chf, "USD": gold}
    rules = {cur: {"momentum": momentum_rule(p), "ma": ma_rule(p)} for cur, p in series.items()}
    regimes = {cur: regime_boundaries(p, thresholds) for cur, p in series.items()}
    as_of = gold.index[-1]
    row = state.loc[as_of] if as_of in state.index else pd.Series(dtype=object)
    press = pressures(row, macro, as_of)

    near = []
    for L in lines:
        if L.get("distance") is None or L.get("severity") not in ("important", "watch"):
            continue
        near.append({**L, "abs_distance": abs(L["distance"])})
    near.sort(key=lambda x: x["abs_distance"])

    upcoming, seen = [], set()
    for r in reports:                       # first upcoming release of each report only
        if r.get("status") == "upcoming" and r["report_id"] not in seen:
            seen.add(r["report_id"])
            upcoming.append(r)
    waiting = [r for r in reports if r.get("status") in ("due", "late", "overdue", "enter")]

    gaps = []
    if not (allocation or {}).get("targets"):
        gaps.append("No allocation targets or bands set (config/allocation.yaml), so the brief cannot say whether "
                    "holdings are inside their bands.")
    if not journal_open:
        gaps.append("No decision journal yet, so no open theses or invalidation conditions are checked against the lines.")
    gaps.append("Prices are monthly averages; daily closes (phase 2) will make line breaks and rule flips exact.")
    missing = [m for m in ("cb_purchases_12m", "etf_holdings_chg_6m") if m not in state.columns]
    if missing:
        gaps.append("Central bank buying and ETF flows are not in yet (WGC figures entered by hand, data/manual/).")

    out = {
        "as_of": str(as_of), "built": str(today), "rules": rules, "regimes": regimes, "near_lines": near[:6],
        "pressures": press, "conflicts": conflicts(rules, regimes, stretch_pct, press),
        "upcoming": upcoming, "waiting": waiting, "gaps": gaps,
        "headline": headline(rules, regimes, press),
    }
    return out


def headline(rules: dict, regimes: dict, press: list[dict]) -> str:
    rc, ru = regimes["CHF"]["now"], regimes["USD"]["now"]
    parts = [f"Gold reads {rc} in francs and {ru} in dollars." if rc != ru else f"Gold reads {rc} in francs and dollars."]
    m, a = rules["USD"]["momentum"]["state"], rules["USD"]["ma"]["state"]
    parts.append(f"The trend rules disagree (momentum {m}, 10-month {a})." if m != a
                 else f"Both trend rules are {m}.")
    heads = sum(p["usual_effect"] == "headwind" for p in press)
    sups = sum(p["usual_effect"] == "support" for p in press)
    parts.append(f"The backdrop has {heads} usual headwind{'s' * (heads != 1)} and {sups} support{'s' * (sups != 1)}.")
    return " ".join(parts)


def text_of(brief: dict) -> str:
    """All prose in the brief, for the instruction-language check."""
    bits = [brief["headline"], *brief["conflicts"], *brief["gaps"]]
    for r in brief["rules"].values():
        bits += [r["momentum"]["if_flat"], r["ma"]["text"], *[s["text"] for s in r["momentum"]["steps"]]]
    bits += [x["text"] for x in brief["regimes"].values()]
    bits += [p["why"] for p in brief["pressures"]]
    return "\n".join(bits)


def check_language(brief: dict) -> list[str]:
    low = text_of(brief).lower()
    return [w for w in FORBIDDEN if f" {w} " in f" {low} "]


def to_markdown(b: dict) -> str:
    out = [f"## Decision brief (data to {b['as_of']})", "", f"**{b['headline']}**", "",
           "Conditions, not instructions. Monthly averages stand in for closes.", "", "### Rules"]
    for cur, r in b["rules"].items():
        m, a = r["momentum"], r["ma"]
        out.append(f"- **{cur}, 12-1 momentum: {m['state']}** ({m['value']:+.1%}). " +
                   " ".join(s["text"] + "." for s in m["steps"]) + f" {m['if_flat']}.")
        out.append(f"- **{cur}, 10-month rule: {a['state']}.** {a['text']}.")
    out += ["", "### Regime"]
    for cur, x in b["regimes"].items():
        out.append(f"- **{cur}: {x['now']}** (12m {x['ret']:+.1%}, ER {x['er']:.2f}). {x['text']}.")
    if b["near_lines"]:
        out += ["", "### Nearest key lines", "", "| Line | Currency | State | Gap | Note |", "|---|---|---|---|---|"]
        for L in b["near_lines"]:
            out.append(f"| {L['label']} | {L['currency']} | {L['state']} | {L['distance']:+.1%} | {L.get('note') or ''} |")
    out += ["", "### Pressures", "", "| Factor | Reading | Usually | Why |", "|---|---|---|---|"]
    for p in b["pressures"]:
        out.append(f"| {p['factor']} | {p['reading']} | {p['usual_effect']} | {p['why']} |")
    if b["conflicts"]:
        out += ["", "### Conflicts"] + [f"- {c}" for c in b["conflicts"]]
    if b["upcoming"]:
        out += ["", "### Coming up"]
        for r in b["upcoming"]:
            when = r["window_start"] if r["window_start"] == r["window_end"] else f"{r['window_start']} to {r['window_end']}"
            out.append(f"- {when}: {r['name']} ({r['period']})" + (f". {r['why']}" if r.get("why") else ""))
    out += ["", "### Not covered yet"] + [f"- {g}" for g in b["gaps"]]
    return "\n".join(out) + "\n"
