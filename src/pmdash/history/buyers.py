"""Who's buying gold, central bank targets, and the "what if" gap. Descriptive, never a forecast.

Inputs are monthly series (Period index):
- cb_gold_t_<CC>      central bank gold holdings, tonnes (IMF IRFCL, fine troy ounces / 32150.7466)
- res_exgold_<CC>     reserves excluding gold, US dollars (IMF via FRED TRESEG<CC>M052N, millions)
- trade series        tonnes a month of unwrought gold (HS 7108) from UN Comtrade

What this module will not do: turn any of this into "how long the price has left". Targets
stated as a share of reserves are reached partly by the price itself, most demand has no target,
and fund flows can outweigh a year of central bank buying in weeks. It reports pace, progress,
years left at the current pace, and a clearly labelled scenario.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

OZ_PER_TONNE = 32150.7466

KIND_PLAIN = {
    "steady": "Steady buyer: keeps buying almost whatever the price",
    "fickle": "Fickle buyer: buys when gold rises, sells when it falls",
    "cushion": "Cushion: buys more after falls and less after rises",
    "hub": "Hub: shows where gold is flowing, not who keeps it",
}


def _last(s: pd.Series | None):
    if s is None:
        return None, None
    s = s.dropna()
    return (float(s.iloc[-1]), s.index[-1]) if len(s) else (None, None)


def _chg(s: pd.Series, months: int) -> float | None:
    """Change in level over ``months`` calendar months to the latest month (None if missing)."""
    s = s.dropna()
    if not len(s):
        return None
    t = s.index[-1]
    prev = s.get(t - months)
    return None if prev is None or pd.isna(prev) else float(s.iloc[-1] - prev)


def _sum_last(s: pd.Series, months: int) -> float | None:
    """Sum of the latest ``months`` calendar months; None unless all are present."""
    s = s.dropna()
    if not len(s):
        return None
    t = s.index[-1]
    w = s.reindex(pd.period_range(t - months + 1, t, freq="M"))
    return None if w.isna().any() else float(w.sum())


def tonnes_for_share(share: float, gold_t: float, non_gold_usd: float, price_usd_oz: float) -> float:
    """Tonnes a bank would need to hold for gold to be ``share`` of reserves at ``price``:
    G' * P / (G' * P + X) = s  =>  G' = s * X / ((1 - s) * P)."""
    g_new = share * non_gold_usd / ((1 - share) * price_usd_oz) / OZ_PER_TONNE
    return g_new - gold_t


def bank_rows(gold: dict[str, pd.Series], non_gold: dict[str, pd.Series], names: dict[str, dict],
              targets: list[dict], price_now: float) -> list[dict]:
    """One row per tracked central bank: holdings, pace, gold share at today's price, target progress.
    ``non_gold`` is reserves excluding gold in US dollars (IMF via FRED)."""
    tg = {t["bank"]: t for t in targets}
    rows = []
    for cc, meta in names.items():
        g = gold.get(cc)
        if g is None or not len(g.dropna()):
            rows.append({"bank": cc, "plain": meta["plain"], "missing": True})
            continue
        now, t = _last(g)
        monthly = g.dropna().diff()
        pace12 = _sum_last(monthly, 12)
        months_bought = int((monthly.dropna().iloc[-12:] > 0.05).sum())
        row = {"bank": cc, "plain": meta["plain"], "tonnes": now, "as_of": str(t),
               "chg_3m": _chg(g, 3), "chg_12m": _chg(g, 12), "pace_12m": pace12, "months_bought_12": months_bought}
        x, xt = _last(non_gold.get(cc))
        if x is not None and x > 0:
            gv = now * OZ_PER_TONNE * price_now
            row.update({"non_gold_usd": x, "non_gold_as_of": str(xt), "share_now": gv / (gv + x)})
        if cc in tg:
            row["target"] = target_progress(tg[cc], row, price_now)
        rows.append(row)
    return rows


def target_progress(t: dict, row: dict, price_now: float) -> dict:
    """Where a bank stands against its stated target, and the time left at its 12-month pace."""
    out = {"source": t.get("source", ""), "verify": bool(t.get("verify")), "stated": t.get("stated"), "by": t.get("by")}
    now, pace = row["tonnes"], row.get("pace_12m")
    goals = []
    if t.get("tonnes"):
        goals.append(("tonnes", float(t["tonnes"]), float(t["tonnes"]) - now))
    if t.get("share_of_reserves") and row.get("non_gold_usd"):
        s = float(t["share_of_reserves"])
        need = tonnes_for_share(s, now, row["non_gold_usd"], price_now)
        need_up = tonnes_for_share(s, now, row["non_gold_usd"], price_now * 1.2)
        goals.append(("share", s, need))
        out["share_need_if_price_up_20"] = need_up
    out["goals"] = []
    for kind, goal, remaining in goals:
        g = {"kind": kind, "goal": goal, "remaining_t": remaining, "done": remaining <= 0}
        if kind == "tonnes":
            g["progress"] = now / goal if goal else None
        if remaining > 0 and pace and pace > 0:
            g["years_left_at_pace"] = remaining / pace
        if kind == "tonnes" and t.get("by") and remaining > 0:
            months = (pd.Period(t["by"], "M") - pd.Period(row["as_of"], "M")).n
            if months > 0:
                g["needed_per_year"] = remaining / months * 12
                g["on_track"] = bool(pace is not None and pace >= g["needed_per_year"])
        out["goals"].append(g)
    return out


def scenario(rows: list[dict], banks: list[str], shares: list[float], price_now: float,
             mine_supply: float) -> dict:
    """If these banks moved gold to each share of reserves, how many tonnes would that take?
    Shown at today's price and at +/-20%, since a higher price shrinks the gap by itself."""
    use = [r for r in rows if r["bank"] in banks and not r.get("missing") and r.get("non_gold_usd")]
    if not use:
        return {"banks": [], "rows": []}
    pace = sum(r["pace_12m"] or 0 for r in use)
    held = sum(r["tonnes"] for r in use)
    non_gold = sum(r["non_gold_usd"] for r in use)
    share_now = held * OZ_PER_TONNE * price_now / (held * OZ_PER_TONNE * price_now + non_gold)
    out = []
    for s in shares:
        row = {"share": s}
        for lab, px in (("now", price_now), ("down20", price_now * 0.8), ("up20", price_now * 1.2)):
            need = sum(max(0.0, tonnes_for_share(s, r["tonnes"], r["non_gold_usd"], px)) for r in use)
            row[f"tonnes_{lab}"] = need
        row["years_of_mine_supply"] = row["tonnes_now"] / mine_supply
        row["years_at_pace"] = row["tonnes_now"] / pace if pace > 0 else None
        out.append(row)
    return {"banks": [r["bank"] for r in use], "held_t": held, "share_now": share_now, "pace_12m": pace,
            "mine_supply": mine_supply, "rows": out}


def total_buying(gold: dict[str, pd.Series], banks: list[str]) -> pd.Series:
    """Monthly tonnage change summed over banks with data that month."""
    parts = [gold[b].dropna().diff() for b in banks if b in gold and len(gold[b].dropna())]
    if not parts:
        return pd.Series(dtype=float)
    return pd.concat(parts, axis=1).sum(axis=1, min_count=1)


def honesty(gold_usd: pd.Series, buying: pd.Series, start: str = "2008-01") -> dict:
    """Did heavy central bank buying (12-month total above its own median so far) come before
    gold rising over the next 12 months more often than usual? Walk-forward, as elsewhere."""
    from .base_rates import honesty_test, rate
    b12 = buying.rolling(12).sum()
    med = b12.expanding(min_periods=36).median()
    cond = (b12 > med).reindex(gold_usd.index).fillna(False)
    if cond.sum() < 12:
        return {"label": "not enough history", "n": 0}
    test = honesty_test(gold_usd, cond, 12, pd.Period(start, "M"))
    r = rate(gold_usd, cond, 12, "cb_heavy", start=pd.Period(start, "M"))
    return {**test, "share_up": r.share_up, "base_share_up": r.base_share_up, "n_months": r.n_periods,
            "n_spells_counted": r.n_spells, "first": str(b12.dropna().index[0]) if len(b12.dropna()) else None,
            "heavy_now": bool(cond.iloc[-1]) if len(cond) else None}


def flow_reading(s: pd.Series | None, plain: str, tech: str) -> dict | None:
    """Latest month, 12-month total and change vs the 12 months before (tonnes)."""
    if s is None or not len(s.dropna()):
        return None
    v, t = _last(s)
    s12 = _sum_last(s, 12)
    prev = s.dropna()
    prev12 = None
    if len(prev):
        w = prev.reindex(pd.period_range(t - 23, t - 12, freq="M"))
        prev12 = None if w.isna().any() else float(w.sum())
    return {"plain": plain, "tech": tech, "latest_t": v, "as_of": str(t), "sum12_t": s12, "prev12_t": prev12,
            "chg_vs_prev12": (s12 / prev12 - 1) if s12 is not None and prev12 else None}


# --- page section ---------------------------------------------------------------------------------

def _fmt_t(x: float | None) -> str:
    return "n/a" if x is None else f"{x:,.0f} t"


def _vs(cur: float | None, prev: float | None) -> str | None:
    if cur is None or not prev:
        return None
    ch = cur / prev - 1
    return "about the same as the year before" if abs(ch) < 0.05 else f"{'up' if ch > 0 else 'down'} {abs(ch):.0%} on the year before"


def _flow(s, label, tech):
    f = flow_reading(s, label, tech)
    if not f or f["sum12_t"] is None:
        return None
    return {"label": label, "value": _fmt_t(f["sum12_t"]) + " in 12 months",
            "sub": "; ".join(x for x in (_vs(f["sum12_t"], f["prev12_t"]), f"to {pd.Period(f['as_of'], 'M').strftime('%b %Y')}") if x),
            "tech": f"{tech}: 12-month total {f['sum12_t']:.1f} t (previous 12 months {f['prev12_t'] if f['prev12_t'] is None else round(f['prev12_t'], 1)} t); "
                    f"latest month {f['latest_t']:.1f} t ({f['as_of']})"}


def build(series: dict[str, pd.Series], gold_usd: pd.Series, price_now: float, cfg: dict,
          today: pd.Timestamp | None = None) -> dict:
    """Everything the two page sections show. ``series`` maps stored series ids to Period-indexed
    monthly series (daily ones already reduced), ``gold_usd`` is the monthly average price."""
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    names = cfg["central_banks"]
    gold = {cc: series.get(f"cb_gold_t_{cc.lower()}") for cc in names}
    gold = {k: v for k, v in gold.items() if v is not None and len(v.dropna())}
    non_gold = {cc: series.get(f"res_exgold_{cc.lower()}") for cc in names}
    non_gold = {k: v for k, v in non_gold.items() if v is not None}
    rows = bank_rows(gold, non_gold, names, cfg.get("targets", []), price_now)
    sc_cfg = cfg.get("scenario", {})
    em = sc_cfg.get("banks", [])
    sc = scenario(rows, em, sc_cfg.get("shares", [0.15, 0.2, 0.3]), price_now, sc_cfg.get("mine_supply_tonnes", 3600))
    sc["names"] = ", ".join(names[b]["plain"].split(" (")[0] for b in sc.get("banks", []))
    buying = total_buying(gold, [b for b in em if b in gold])
    hon = honesty(gold_usd, buying) if len(buying.dropna()) > 60 else {"label": "not enough history", "n": 0}
    em_rows = [r for r in rows if r["bank"] in em and not r.get("missing")]
    em_pace = sum(r["pace_12m"] or 0 for r in em_rows)
    bought_last = [r for r in em_rows if r.get("chg_3m") and r["chg_3m"] > 0.1]

    if hon.get("n"):
        if hon["label"] == "useful":
            hp = (f"Yes, so far: after periods of heavy buying, gold was higher a year later {hon['share_up']:.0%} of the time, "
                  f"against {hon['base_share_up']:.0%} for all months, and the walk-forward test passed.")
        else:
            hp = (f"Not reliably. After periods of heavy buying by these banks, gold was higher a year later "
                  f"{hon['share_up']:.0%} of the time, against {hon['base_share_up']:.0%} for all months since 2008, "
                  f"but that rests on only {hon.get('spells', 0)} separate stretches and did not pass the walk-forward test. "
                  f"Treat it as background, not a timing signal.")
        ht = (f"Condition: 12-month sum of monthly tonnage changes ({', '.join(em)}) above its expanding median (min 36 months). "
              f"Walk-forward from 2008-01, h = 12: Brier {hon.get('brier_setup', float('nan')):.3f} vs base {hon.get('brier_base', float('nan')):.3f}, "
              f"hit {hon.get('hit_setup', float('nan')):.2f} vs {hon.get('hit_base', float('nan')):.2f}, {hon.get('spells')} spells, label {hon['label']}. "
              f"Heavy buying now: {hon.get('heavy_now')}.")
    else:
        hp, ht = "Not enough monthly history loaded yet to test.", "Needs at least 60 months of central bank holdings."
    hon.update({"plain": hp, "tech": ht})

    # who's buying cards
    gcfg = cfg["groups"]
    dates = [d for d in cfg.get("dates", []) if today <= pd.Timestamp(d["date"]) <= today + pd.DateOffset(years=1)]

    def bank_reading(cc, label):
        r = next((x for x in rows if x["bank"] == cc and not x.get("missing")), None)
        if not r or r.get("pace_12m") is None:
            return None
        return {"label": label, "value": ("+" if r["pace_12m"] > 0 else "") + f"{r['pace_12m']:,.0f} t in 12 months",
                "sub": f"holds {r['tonnes']:,.0f} t; to {pd.Period(r['as_of'], 'M').strftime('%b %Y')}",
                "tech": f"IMF IRFCL gold volume, {cc}: 12-month change {r['pace_12m']:+.1f} t; 3-month {r['chg_3m']:+.1f} t"}

    gld = series.get("gld_holdings_m")
    gld_r = None
    if gld is not None and len(gld.dropna()) > 13:
        v, t = _last(gld)
        c3, c12 = _chg(gld, 3), _chg(gld, 12)
        gld_r = {"label": "Largest US gold fund (GLD) holds", "value": _fmt_t(v),
                 "sub": f"{'+' if (c12 or 0) > 0 else ''}{(c12 or 0):,.0f} t on a year ago, {'+' if (c3 or 0) > 0 else ''}{(c3 or 0):,.0f} t in 3 months",
                 "tech": f"SPDR Gold Shares holdings (month-end), {t}: {v:.1f} t; 3-month change {c3}, 12-month change {c12}"}
    spec = series.get("cftc_gold_mm_net_m")
    spec_r = None
    if spec is not None and len(spec.dropna()) > 40:
        v, t = _last(spec)
        pct = float((spec.dropna().iloc[-156:] <= v).mean() * 100)
        spec_r = {"label": "Speculators' net bets on gold (futures)", "value": f"{v:,.0f} contracts",
                  "sub": f"higher than {pct:.0f}% of the last 3 years",
                  "tech": f"CFTC disaggregated, managed money net long, month-end {t}; percentile over 36 months"}

    readings = {
        "central_banks": [x for x in (
            {"label": "Tracked emerging-market banks bought", "value": f"{em_pace:+,.0f} t in 12 months",
             "sub": f"{len(bought_last)} of {len(em_rows)} added gold in the last 3 months",
             "tech": f"Sum of 12-month changes, {', '.join(r['bank'] for r in em_rows)} (IMF IRFCL). Unreported buying not included."} if em_rows else None,
        ) if x],
        "china": [x for x in (bank_reading("CN", "Central bank bought"),
                              _flow(series.get("trade_hk_x_cn"), "Hong Kong shipped to the mainland", "Comtrade HS 7108, HK exports to CN"),
                              _flow(series.get("trade_ch_x_cn"), "Swiss refiners shipped to China", "Comtrade HS 7108, CH exports to CN")) if x],
        "india": [x for x in (_flow(series.get("trade_in_m_total"), "India imported", "Comtrade HS 7108, India imports, world"),
                              _flow(series.get("trade_ch_x_in"), "Swiss refiners shipped to India", "Comtrade HS 7108, CH exports to IN"),
                              bank_reading("IN", "Central bank bought")) if x],
        "usa": [x for x in (gld_r, spec_r, _flow(series.get("trade_ch_x_us"), "Swiss refiners shipped to the US",
                                                 "Comtrade HS 7108, CH exports to US")) if x],
        "europe": [x for x in (_flow(series.get("trade_ch_x_gb"), "Swiss refiners shipped to London",
                                     "Comtrade HS 7108, CH exports to GB (London vaults hold most European fund and bank gold)"),) if x],
        "switzerland": [],
        "turkey_me": [x for x in (bank_reading("TR", "Turkey's central bank bought"),
                                  _flow(series.get("trade_ch_x_tr"), "Swiss refiners shipped to Turkey", "Comtrade HS 7108, CH exports to TR"),
                                  _flow(series.get("trade_ch_x_ae"), "Swiss refiners shipped to the UAE", "Comtrade HS 7108, CH exports to AE")) if x],
    }
    tot = series.get("trade_ch_x_total")
    if tot is not None:
        r = _flow(tot, "Swiss gold exports, all destinations", "Comtrade HS 7108, CH exports to world")
        if r:
            readings["switzerland"].append(r)
            dest = []
            for code, nm in (("cn", "China"), ("hk", "Hong Kong"), ("in", "India"), ("gb", "UK"), ("us", "US"),
                             ("tr", "Turkey"), ("ae", "UAE"), ("sg", "Singapore"), ("th", "Thailand"), ("sa", "Saudi Arabia")):
                f = flow_reading(series.get(f"trade_ch_x_{code}"), nm, "")
                if f and f["sum12_t"]:
                    dest.append((f["sum12_t"], nm))
            t12 = flow_reading(tot, "", "")["sum12_t"]
            if dest and t12:
                dest.sort(reverse=True)
                readings["switzerland"].append({"label": "Where it went (12 months)", "value": ", ".join(f"{n} {v / t12:.0%}" for v, n in dest[:3]),
                                                "sub": None, "tech": "; ".join(f"{n} {v:.0f} t" for v, n in dest)})
    groups = []
    for gid, g in gcfg.items():
        groups.append({"id": gid, "plain": g["plain"], "kind": g["kind"], "kind_plain": KIND_PLAIN.get(g["kind"], g["kind"]),
                       "share_note": g.get("share_note", ""), "watch": g.get("watch", ""), "early": g.get("early", ""),
                       "readings": readings.get(gid, []),
                       "dates": [{"date": d["date"], "plain": d["plain"], "verify": bool(d.get("verify"))} for d in dates if d["group"] == gid]})

    parts = []
    if em_rows:
        parts.append(f"Tracked central banks {'added' if em_pace >= 0 else 'sold'} {abs(em_pace):,.0f} tonnes over the last 12 months")
    if gld_r:
        c12 = _chg(gld, 12) or 0
        parts.append(f"the largest US gold fund {'grew' if c12 > 0 else 'shrank'} by {abs(c12):,.0f} tonnes")
    india = flow_reading(series.get("trade_in_m_total"), "", "")
    if india and india["sum12_t"] and india["prev12_t"]:
        parts.append(f"India's imports were {_vs(india['sum12_t'], india['prev12_t'])}")
    headline = (parts[0] + (", " + ", ".join(parts[1:-1]) if len(parts) > 2 else "") + (" and " + parts[-1] if len(parts) > 1 else "") + ".") if parts \
        else "Figures for who's buying are still loading."
    cb_head = (f"{len(bought_last)} of {len(em_rows)} tracked emerging-market central banks added gold in the last 3 months"
               if em_rows else "Central bank figures are still loading")
    return {"headline": headline, "headline_tech": "Sources: IMF IRFCL (central banks), SPDR (GLD), CFTC, UN Comtrade (trade).",
            "cb_headline": cb_head, "cb_headline_tech": f"EM set: {', '.join(em)}; 3-month change > 0.1 t counts as buying",
            "groups": groups, "banks": rows, "scenario": sc, "honesty": hon, "price_now": price_now}
