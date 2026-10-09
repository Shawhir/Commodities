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
