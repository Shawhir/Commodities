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

MOOD = {"Up": "rising steadily", "Sideways": "going sideways", "Down": "falling steadily"}
ONOFF = {"In": "ON", "Out": "OFF"}
LIGHT = {"In": "CLEAR", "Out": "WARNING"}      # rule 2 is a warning light, not a second switch

FORBIDDEN = ("buy", "sell", "should", "recommend", "target price", "price target", "go long", "go short")


def _month_name(p: pd.Period) -> str:
    return p.strftime("%B %Y")


def ordinal(x: float) -> str:
    n = int(round(x))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# --- 1. trend rules ----------------------------------------------------------------------------

def _chf(x: float, chf_rate: float | None) -> str:
    return f" (about CHF {x * chf_rate:,.0f} at today's exchange rate)" if chf_rate else ""


def momentum_rule(p: pd.Series, horizon: int = 3, chf_rate: float | None = None) -> dict:
    """12-1 momentum now, and for each of the next closes either its known value or the price
    that would flip it. Momentum at close t+k = p[t+k-1] / p[t+k-12] - 1.
    ``p`` is the dollar price: the rules are decided on it for every view (Oct 2026 review)."""
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
                          "text": f"End of {_month_name(month)}: stays {'ON' if val > 0 else 'OFF'} whatever happens "
                                  f"(already set by {_month_name(p.index[num_i])}'s average price)",
                          "tech": f"12-1 momentum at {month} close = P({p.index[num_i]}) / P({p.index[den_i]}) - 1 "
                                  f"= {float(p.iloc[num_i]):,.0f} / {den:,.0f} - 1 = {val:+.2%}: known now"})
        else:
            needed_month = p.index[-1] + (num_i - t)
            flip = "below" if state == "In" else "above"
            steps.append({"month": str(month), "known": False, "threshold": den, "depends_on": str(needed_month),
                          "text": f"End of {_month_name(month)}: switches {'OFF' if state == 'In' else 'ON'} if gold's "
                                  f"average price in {_month_name(needed_month)} is {flip} ${den:,.0f}{_chf(den, chf_rate)}",
                          "tech": f"12-1 momentum at {month} close = P({needed_month}) / P({p.index[den_i]}) - 1; "
                                  f"sign flips when P({needed_month}) crosses P({p.index[den_i]}) = {den:,.2f}"})
    hold = float(p.iloc[-1])
    turn = None
    q = p.copy()
    for k in range(1, 13):
        q.loc[p.index[-1] + k] = hold
        v = momentum_12_1(q).iloc[-1]
        if (v > 0) != (now > 0):
            turn = str(p.index[-1] + k)
            break
    up = "higher" if now > 0 else "lower"
    return {"rule": "12-1 momentum", "name": "Main switch (rule 1): the 12-month trend", "role": "switch",
            "state": state, "onoff": ONOFF[state],
            "value": now, "steps": steps,
            "tech": f"Time-series momentum, 12-1 (Moskowitz, Ooi and Pedersen 2012): sign of the return from t-12 to t-1 "
                    f"on monthly averages = {now:+.2%}, so In. Section 8.3: 9.1% CAGR in USD, max drawdown -36%, "
                    f"53 switches since 1972-08.",
            "if_flat_tech": f"Hold P = {hold:,.2f} for every future month; first close where the sign changes: {turn}",
            "explain": f"ON when gold's dollar price is higher than a year ago (leaving out the latest month). "
                       f"Right now it is {abs(now):.0%} {up}, so the switch is {ONOFF[state]}. It is decided on the "
                       f"dollar price in both views, because gold trades in dollars: the franc's jumps would otherwise "
                       f"cause extra switching. Your results are still measured in francs.",
            "if_flat": f"If gold stays around ${hold:,.0f}, the main switch turns {'OFF' if state == 'In' else 'ON'} at the end "
                       f"of {_month_name(pd.Period(turn, 'M'))}" if turn else
                       f"If gold stays around ${hold:,.0f}, the main switch does not change within 12 months"}


def ma_rule(p: pd.Series, window: int = 10, chf_rate: float | None = None) -> dict:
    """10-month rule now, and the next month's average that would flip it.
    In next month if P > (sum of last window-1 + P) / window, i.e. P > mean of the last window-1."""
    state = "In" if ma_signal(p, window).iloc[-1] == 1 else "Out"
    ma = float(p.rolling(window).mean().iloc[-1])
    threshold = float(p.iloc[-(window - 1):].mean())
    nxt = p.index[-1] + 1
    flip = "above" if state == "Out" else "below"
    pos = "above" if state == "In" else "below"
    return {"rule": f"{window}-month average", "name": f"Warning light (rule 2): the {window}-month average",
            "role": "warning", "state": state,
            "onoff": LIGHT[state], "value": float(p.iloc[-1] / ma - 1), "average": ma,
            "threshold": threshold, "month": str(nxt),
            "tech": f"{window}-month simple moving average rule: In if P > SMA{window}. P = {float(p.iloc[-1]):,.2f}, "
                    f"SMA{window} = {ma:,.2f} ({float(p.iloc[-1] / ma - 1):+.2%}), so {state}. Next month's breakeven "
                    f"P = mean of the last {window - 1} monthly averages = {threshold:,.2f}.",
            "explain": f"A warning light, not a second switch. It shows when gold's dollar price drops below its "
                       f"average of the last {window} months. Now gold is ${float(p.iloc[-1]):,.0f}, {pos} its average of "
                       f"${ma:,.0f}, so the light is {'showing' if state == 'Out' else 'clear'}. Tested at real month-end "
                       f"prices, acting on this light alone lost money in choppy markets, so it is shown as a caution only.",
            "text": f"{'Clears' if state == 'Out' else 'Shows'} if gold's average price in {_month_name(nxt)} is "
                    f"{flip} ${threshold:,.0f}{_chf(threshold, chf_rate)}"}


# --- 2. regime boundaries ----------------------------------------------------------------------

def regime_boundaries(p: pd.Series, cfg: dict) -> dict:
    """Range of next month's average that gives each regime label (grid search, 0.1% steps)."""
    r = cfg["regime"]
    last = float(p.iloc[-1])
    nxt = p.index[-1] + 1
    grid = last * np.arange(0.60, 1.60, 0.001)
    n = r["lookback_months"]
    # For next month's price P: 12-month return = P / p[t-11] - 1 and efficiency ratio =
    # |P - p[t-11]| / (sum of the last 11 monthly moves + |P - p[t]|): same rule as labeller.label.
    tail = p.iloc[-n:].to_numpy(dtype=float)              # p[t-11] .. p[t]
    base, path = tail[0], np.abs(np.diff(tail)).sum()
    ret = grid / base - 1
    er = np.abs(grid - base) / (path + np.abs(grid - tail[-1]))
    labels = np.where((er >= r["er_min"]) & (ret >= r["up_return_min"]), "Up",
                      np.where((er >= r["er_min"]) & (ret <= r["down_return_max"]), "Down", "Sideways")).tolist()
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
        span = f"below {hi}" if lo is None and hi else f"above {lo}" if hi is None and lo else f"between {lo} and {hi}" if lo else "at any level"
        parts.append(f"{MOOD[x['regime']]} if {span}")
    for i, c in enumerate(cuts):
        ranges[i]["high_cut"] = c
        ranges[i + 1]["low_cut"] = c
    return {"now": now["regime"], "er": float(now["er"]), "ret": float(now["ret"]), "month": str(nxt), "ranges": ranges,
            "now_plain": MOOD[now["regime"]],
            "tech": f"Regime labeller (section 8.1): ER = |P(t) - P(t-12)| / sum|monthly changes| over 12 months. "
                    f"Up if ER >= {r['er_min']:.2f} and r12 >= {r['up_return_min']:+.0%}; Down if ER >= {r['er_min']:.2f} and "
                    f"r12 <= {r['down_return_max']:+.0%}; else Sideways. Now r12 = {float(now['ret']):+.2%}, ER = {float(now['er']):.3f}. "
                    f"Next-month boundaries found by grid search on P({nxt}) in 0.1% steps.",
            "text": f"Depending on gold's average price in {_month_name(nxt)}: " + "; ".join(parts)}


# --- 4. pressures --------------------------------------------------------------------------------

def pressures(state_row: pd.Series, macro: dict, as_of: pd.Period) -> list[dict]:
    """Backdrop readings with the effect they usually have on gold (themes.yaml), by fixed thresholds."""
    out = []

    def add(factor, reading, effect, why, theme, tech=""):
        out.append({"factor": factor, "reading": reading, "usual_effect": effect, "why": why, "theme": theme,
                    "tech": tech})

    fed = state_row.get("fed_direction")
    if isinstance(fed, str):
        eff = {"hiking": "headwind", "cutting": "support", "on hold": "neutral"}[fed]
        rate = macro.get("fed_rate")
        lvl = f", now {rate.dropna().iloc[-1]:.2f}%" if rate is not None and len(rate.dropna()) else ""
        doing = {"hiking": "raising rates", "cutting": "cutting rates", "on hold": "holding rates steady"}[fed]
        add("US interest rates (the Fed)", f"{doing}{lvl}", eff,
            "Gold pays no interest, so higher rates make it less attractive to hold", "fed_real_rates",
            "Fed direction: 6-month change in the month-end policy rate (FRED DFEDTARU from 2008-12, DFF before); "
            ">= +25 bp hiking, <= -25 bp cutting. Effect: opportunity cost of a zero-yield asset (theme fed_real_rates).")
    tips = macro.get("real_yield_tips")
    if tips is not None and len(tips.dropna()) > 6:
        t = tips.dropna()
        chg = t.iloc[-1] - t.iloc[-7]
        eff = "headwind" if chg > 0.25 else "support" if chg < -0.25 else "neutral"
        add("Interest rates after inflation", f"{t.iloc[-1]:.2f}%, {'up' if chg > 0 else 'down'} {abs(chg):.2f} points in 6 months", eff,
            "This is the return on safe bonds after inflation; when it rises, gold usually struggles", "fed_real_rates",
            f"10-year TIPS real yield (FRED DFII10), monthly mean {t.iloc[-1]:.2f}%, 6-month change {chg:+.2f} pp; "
            f"headwind if > +0.25 pp, support if < -0.25 pp.")
    y2 = macro.get("yield_2y")
    if y2 is not None and len(y2.dropna()) > 7:
        t2 = y2.dropna()
        c6 = t2.iloc[-1] - t2.iloc[-7]
        eff = "headwind" if c6 > 0.25 else "support" if c6 < -0.25 else "neutral"
        add("Where markets expect US rates to go", f"2-year US yield {t2.iloc[-1]:.2f}%, {'up' if c6 > 0 else 'down'} {abs(c6):.2f} points in 6 months", eff,
            "The 2-year yield moves with what markets expect the Fed to do next; falling expectations usually help gold",
            "fed_real_rates",
            f"2-year Treasury yield (FRED DGS2), monthly mean {t2.iloc[-1]:.2f}%, 6-month change {c6:+.2f} pp; "
            f"headwind if > +0.25 pp, support if < -0.25 pp.")
    cv = macro.get("curve_10y3m")
    if cv is not None and len(cv.dropna()) > 6:
        k = cv.dropna()
        inv = int((k.iloc[-6:] < 0).sum())
        add("Recession warning (yield curve)", f"10-year minus 3-month {k.iloc[-1]:+.2f} points; below zero in {inv} of the last 6 months",
            "mixed" if inv >= 3 else "neutral",
            "When long rates sit below short rates, a US recession has often followed within 1-2 years; recessions bring rate cuts "
            "(good for gold) but can also force selling at first", "fed_real_rates",
            f"FRED T10Y3M monthly mean {k.iloc[-1]:+.2f} pp; inverted months in last 6 = {inv}; mixed if >= 3.")
    chy, chc = macro.get("ch_yield_10y"), macro.get("ch_cpi_yoy")
    if chy is not None and chc is not None and len(chy.dropna()) > 7 and len(chc.dropna()) > 1:
        y = chy.dropna()
        r_ = (chy - chc.shift(1)).dropna()
        r_ = r_[r_.index >= y.index[-1] - 3]          # only a current figure; never an old one
        ch6 = y.iloc[-1] - y.iloc[-7]
        eff = "headwind" if ch6 > 0.25 else "support" if ch6 < -0.25 else "neutral"
        add("Swiss interest rates", f"10-year Swiss bonds pay {y.iloc[-1]:.2f}%, {'up' if ch6 > 0 else 'down'} {abs(ch6):.2f} points in 6 months"
            + (f"; after Swiss inflation {r_.iloc[-1]:+.2f}%" if len(r_) else ""), eff,
            "What a franc saver gives up by holding gold instead of Swiss bonds; low Swiss rates make holding gold cheap in francs",
            "chf_snb",
            f"Swiss 10-year government bond yield (OECD IRLTLT01CHM156N via FRED), {y.index[-1]}: {y.iloc[-1]:.2f}%, "
            f"6-month change {ch6:+.2f} pp; real = yield - Swiss CPI y/y (SNB cube plkopr VVP, lagged 1 month). "
            f"Headwind if > +0.25 pp in 6 months, support if < -0.25 pp.")
    d = state_row.get("dollar_chg_6m")
    if d is not None and not pd.isna(d):
        add("US dollar", f"{'up' if d > 0 else 'down'} {abs(d):.1%} in 6 months", "headwind" if d > 0.03 else "support" if d < -0.03 else "neutral",
            "Gold is priced in dollars; a stronger dollar usually means a lower gold price", "fed_real_rates",
            f"Broad trade-weighted dollar index (FRED DTWEXBGS), 6-month change {d:+.2%}; thresholds +/-3%.")
    g = state_row.get("gpr_pct")
    if g is not None and not pd.isna(g):
        add("War and political risk", f"higher than {g:.0f}% of the last 10 years", "support" if g >= 80 else "neutral",
            "People turn to gold as a safe place in times of conflict; the effect often fades when tensions ease", "middle_east_iran",
            f"Caldara-Iacoviello Geopolitical Risk index (GPR), percentile within the trailing 120 months = {g:.1f}; "
            f"support if >= 80th. Safe-haven bid; event studies show it often mean-reverts.")
    o = state_row.get("oil_chg_12m")
    if o is not None and not pd.isna(o):
        add("Oil price", f"{'up' if o > 0 else 'down'} {abs(o):.0%} in 12 months", "mixed" if abs(o) >= 0.3 else "neutral",
            "Expensive oil raises inflation, which helps gold, but can make the Fed raise rates, which hurts it", "middle_east_iran",
            f"Brent crude (EIA), 12-month change {o:+.1%}; mixed if |change| >= 30%: inflation-hedge demand vs "
            f"hawkish Fed reaction function.")
    c = state_row.get("cftc_mm_pct")
    if c is not None and not pd.isna(c):
        mm = macro.get("cftc_gold_mm")
        trend = ""
        if mm is not None and len(mm.dropna()) > 2:
            m = mm.dropna()
            trend = f", {'shrinking' if m.iloc[-1] < m.iloc[-2] else 'growing'} this month"
        eff = "crowded" if c >= 90 else "washed out" if c <= 10 else "neutral"
        size = "very large" if c >= 90 else "very small" if c <= 10 else "middling"
        add("Speculators' bets on gold", f"{size} (higher than {c:.0f}% of the last 3 years){trend}", eff,
            "When almost everyone has already bet on gold, a rush to exit can cause sharp drops", "cb_diversification",
            f"CFTC disaggregated COT, COMEX gold (088691), managed-money net long (long - short), monthly mean; "
            f"percentile within the trailing 36 months = {c:.1f}. Crowded >= 90th, washed out <= 10th.")
    v = state_row.get("vix_pct")
    if v is not None and not pd.isna(v):
        add("Stock market fear", f"{'high' if v >= 80 else 'calm' if v <= 40 else 'normal'} (higher than {v:.0f}% of the last 10 years)",
            "mixed" if v >= 80 else "neutral",
            "Panic can send people to gold, or force them to cash in gold to raise money", "fed_real_rates",
            f"VIX (CBOE), monthly mean, percentile within the trailing 120 months = {v:.1f}; mixed if >= 80th "
            f"(safe-haven bid vs liquidation / margin-call selling).")
    u = state_row.get("usdchf_chg_12m")
    if u is not None and not pd.isna(u):
        franc = "franc weaker" if u > 0 else "franc stronger"
        add("Swiss franc", f"{franc} against the dollar by {abs(u):.1%} in 12 months",
            "lowers CHF returns" if u < -0.03 else "raises CHF returns" if u > 0.03 else "neutral",
            "A stronger franc lowers what your gold is worth in francs, even if gold's dollar price is unchanged", "chf_snb",
            f"USD/CHF 12-month change {u:+.2%} (Fed H.10, CHF per USD). Gold in CHF = gold in USD x USD/CHF; "
            f"thresholds +/-3%.")
    cpi = state_row.get("cpi_yoy")
    if cpi is not None and not pd.isna(cpi):
        add("US inflation", f"{cpi:.1%} a year (figures arrive a month late)", "mixed" if cpi > 0.03 else "neutral",
            "High inflation makes gold attractive as protection, but keeps the Fed raising rates", "fed_real_rates",
            f"US CPI-U (NSA) y/y = {cpi:.2%}, lagged one month for the BLS publication date; mixed if > 3%.")
    return out


# --- 5. conflicts ----------------------------------------------------------------------------------

def conflicts(rules: dict, regimes: dict, stretch: dict, press: list[dict]) -> list[dict]:
    """Each item: {"text": plain, "tech": technical}."""
    out = []
    for cur, r in rules.items():
        m, a = r["momentum"]["state"], r["ma"]["state"]
        if m == "In" and a == "Out":
            out.append({"text": "The main switch is ON, but the warning light is showing: gold is still above a year ago, "
                                "yet below its 10-month average.",
                        "tech": f"{cur}: 12-1 momentum {m} ({r['momentum']['value']:+.2%}) vs 10-month SMA rule {a} "
                                f"(P/SMA10 - 1 = {r['ma']['value']:+.2%})."})
    labs = {cur: x["now"] for cur, x in regimes.items()}
    if len(set(labs.values())) > 1:
        out.append({"text": "The market mood depends on the currency: " +
                            " but ".join(f"{MOOD[v]} in {'francs' if k == 'CHF' else 'dollars'}" for k, v in labs.items()) +
                            ". The franc's moves against the dollar make the difference.",
                    "tech": "Regime label by currency: " + ", ".join(
                        f"{k} {v} (r12 {regimes[k]['ret']:+.1%}, ER {regimes[k]['er']:.2f})" for k, v in labs.items()) +
                            ". The section 8 study labels on USD."})
    for cur, s in stretch.items():
        if s is not None and s >= 90 and rules.get(cur, {}).get("ma", {}).get("state") == "Out":
            out.append({"text": f"In {cur}, gold is far above its 10-year average (higher than {s:.0f}% of the time "
                                f"since 1971), yet below its 10-month average: high over the long run, slipping in the short run.",
                        "tech": f"{cur}: distance from the 120-month average at the {s:.1f} percentile since 1971-08 "
                                f"(floating-era windows) while P < SMA10."})
    heads = [p["factor"] for p in press if p["usual_effect"] == "headwind"]
    sups = [p["factor"] for p in press if p["usual_effect"] == "support"]
    if heads and sups:
        out.append({"text": "Outside influences pull both ways. Usually pushing gold down: " + ", ".join(heads) +
                            ". Usually pushing gold up: " + ", ".join(sups) + ".",
                    "tech": "Backdrop classification (fixed thresholds, themes.yaml usual effects): headwinds " +
                            ", ".join(heads) + "; supports " + ", ".join(sups) + ". No combined score (principle 4)."})
    return out


# --- assemble ------------------------------------------------------------------------------------

def build(gold: pd.Series, fx: pd.Series, state: pd.DataFrame, macro: dict, lines: list[dict],
          reports: list[dict], stretch_pct: dict, thresholds: dict, today: date | None = None,
          allocation: dict | None = None, journal_open: int | None = None) -> dict:
    today = today or date.today()
    chf = (gold * fx).dropna()
    series = {"CHF": chf, "USD": gold}
    rate = float(fx.dropna().iloc[-1]) if len(fx.dropna()) else None
    # both rules are decided on the dollar price for every view; franc amounts are shown alongside
    rules = {"USD": {"momentum": momentum_rule(gold, chf_rate=rate), "ma": ma_rule(gold, chf_rate=rate)}}
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
        gaps.append({"text": "You haven't written down your plan yet (how much gold and silver you want), so this page "
                             "can't tell you whether you've drifted from it.",
                     "tech": "config/allocation.yaml has no targets or bands: no rebalance check, position sizer or "
                             "leverage check (section 9.9)."})
    if not journal_open:
        gaps.append({"text": "There's no decision diary yet, so the page can't check your past decisions against these price levels.",
                     "tech": "Decision journal (section 9.11, phase 5) not built: no open theses or invalidation "
                             "conditions linked to trigger ids."})
    gaps.append({"text": "Prices here are monthly averages, not daily closing prices, so the switch levels are close but not exact.",
                 "tech": "Research series = monthly average (datasets/gold-prices). Rules and the line state machine "
                         "run on monthly averages as closes until daily settlement data (Databento / LBMA) is ingested."})
    missing = [m for m in ("cb_purchases_12m", "etf_holdings_chg_6m") if m not in state.columns]
    if missing:
        gaps.append({"text": "Gold buying by central banks and by funds isn't included yet; those figures have to be typed in "
                             "from World Gold Council reports.",
                     "tech": "cb_purchases_12m and etf_holdings_chg_6m missing from the demand_flow group (WGC Goldhub; "
                             "manual entry in data/manual/report_figures.csv)."})

    out = {
        "as_of": str(as_of), "built": str(today), "rules": rules, "regimes": regimes, "near_lines": near[:6],
        "pressures": press, "conflicts": conflicts(rules, regimes, stretch_pct, press),
        "upcoming": upcoming, "waiting": waiting, "gaps": gaps,
        "headline": headline(rules, regimes, press),
        "headline_tech": f"Regime {regimes['CHF']['now']} (CHF) / {regimes['USD']['now']} (USD); USD trend rules: "
                         f"12-1 momentum {rules['USD']['momentum']['state']}, SMA10 {rules['USD']['ma']['state']}; "
                         f"backdrop {sum(p['usual_effect'] == 'headwind' for p in press)} headwinds, "
                         f"{sum(p['usual_effect'] == 'support' for p in press)} supports.",
    }
    return out


def headline(rules: dict, regimes: dict, press: list[dict]) -> str:
    rc, ru = regimes["CHF"]["now"], regimes["USD"]["now"]
    parts = [f"In francs, gold has been {MOOD[rc]}; in dollars it has been {MOOD[ru]}." if rc != ru
             else f"Gold has been {MOOD[rc]} in both francs and dollars."]
    m, a = rules["USD"]["momentum"]["state"], rules["USD"]["ma"]["state"]
    parts.append(f"Your main switch is {ONOFF[m]}" + (" and the warning light is showing." if a == "Out"
                                                       else " and the warning light is clear."))
    heads = sum(p["usual_effect"] == "headwind" for p in press)
    sups = sum(p["usual_effect"] == "support" for p in press)
    parts.append(f"Of the outside influences, {heads} usually push{'es' * (heads == 1)} gold down and "
                 f"{sups} usually push{'es' * (sups == 1)} it up.")
    return " ".join(parts)


def text_of(brief: dict) -> str:
    """All prose in the brief, for the instruction-language check."""
    def t(x):
        return x["text"] if isinstance(x, dict) else x
    bits = [brief["headline"], *[t(c) for c in brief["conflicts"]], *[t(g) for g in brief["gaps"]]]
    for r in brief["rules"].values():
        bits += [r["momentum"]["if_flat"], r["ma"]["text"], r["momentum"]["explain"], r["ma"]["explain"],
                 *[s["text"] for s in r["momentum"]["steps"]]]
    bits += [x["text"] for x in brief["regimes"].values()]
    bits += [p["why"] for p in brief["pressures"]] + [p["reading"] for p in brief["pressures"]]
    bits += [p.get("tech", "") for p in brief["pressures"]] + [brief.get("headline_tech", "")]
    return "\n".join(bits)


def check_language(brief: dict) -> list[str]:
    low = text_of(brief).lower()
    return [w for w in FORBIDDEN if f" {w} " in f" {low} "]


STATE_PLAIN = {"intact": "not crossed", "approaching": "getting close", "broken": "crossed",
               "confirmed": "crossed and held", "failed": "crossed, then recovered"}
EFFECT_PLAIN = {"headwind": "down", "support": "up", "mixed": "either way", "neutral": "little effect now",
                "crowded": "risk of a sharp drop", "washed out": "room to recover",
                "lowers CHF returns": "down, in francs", "raises CHF returns": "up, in francs"}


def to_markdown(b: dict) -> str:
    out = [f"## This month at a glance (prices to {b['as_of']})", "", f"**{b['headline']}**", "",
           "What your rules say and what would change them. Not advice.", "",
           "### Your main switch and warning light (decided on the dollar price)"]
    for cur, r in b["rules"].items():
        for rule in (r["momentum"], r["ma"]):
            out.append(f"- **{rule['name']}: {rule['onoff']}.** {rule['explain']}")
            if rule.get("steps"):
                out += [f"  - {s['text']}." for s in rule["steps"]] + [f"  - {rule['if_flat']}."]
            else:
                out.append(f"  - {rule['text']}.")
    out += ["", "### Market mood"]
    for cur, x in b["regimes"].items():
        out.append(f"- **{'In francs' if cur == 'CHF' else 'In dollars'}: {x['now_plain']}.** {x['text']}.")
    if b["near_lines"]:
        out += ["", "### Price levels to watch", "", "| Level | Currency | Status | Gold vs level | What it means |",
                "|---|---|---|---|---|"]
        for L in b["near_lines"]:
            out.append(f"| {L['label']} | {L['currency']} | {STATE_PLAIN.get(L['state'], L['state'])} | "
                       f"{L['distance']:+.1%} | {L.get('note') or ''} |")
    out += ["", "### What is pushing gold up or down", "", "| What | Now | Usually pushes gold | Why |", "|---|---|---|---|"]
    for p in b["pressures"]:
        out.append(f"| {p['factor']} | {p['reading']} | {EFFECT_PLAIN.get(p['usual_effect'], p['usual_effect'])} | {p['why']} |")
    if b["conflicts"]:
        out += ["", "### Mixed signals"] + [f"- {c['text']}" for c in b["conflicts"]]
    if b["upcoming"]:
        out += ["", "### Dates to know"]
        for r in b["upcoming"]:
            when = r["window_start"] if r["window_start"] == r["window_end"] else f"{r['window_start']} to {r['window_end']}"
            why = r.get("plain_why") or r.get("why")
            out.append(f"- {when}: {r.get('plain_name') or r['name']}" + (f". {why}" if why else ""))
    out += ["", "### What this page can't tell you yet"] + [f"- {g['text']}" for g in b["gaps"]]
    return "\n".join(out) + "\n"
