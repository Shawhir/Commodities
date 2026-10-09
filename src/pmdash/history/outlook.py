"""Outlook pieces added after the October 2026 audit. None of them forecasts direction.

- expected_move: the range the options market prices for the next 3, 6 and 12 months (CBOE gold
  volatility index, GVZ), with a check of how often gold actually stayed inside it since 2008;
  5 years uses gold's own long-run volatility. Size of moves is forecastable; direction is not.
- valuation: gold against US consumer prices (its "real" price), against the money supply and
  next to US debt, deficits and mine supply. Long-run context: both earlier record real prices
  (1980, 2011) were followed by long weak stretches, but two episodes cannot be tested.
- scenarios: what gold did over the next 12 months in past periods like each scenario (rate cuts
  with a weaker dollar, sticky inflation, recession, fast-rising real yields, Fed hiking), and
  which of them resemble today.
- silver: the gold/silver ratio, silver's own trend switch, copper (industrial demand) and the
  Silver Institute's market balance when entered.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base_rates import forward_return, rate


def _m_last(s: pd.Series | None) -> pd.Series | None:
    if s is None or not len(s.dropna()):
        return None
    s = s.dropna()
    return s if isinstance(s.index, pd.PeriodIndex) else s.groupby(s.index.to_period("M")).last()


# --- expected move ---------------------------------------------------------------------------------

def calibration(gvz_m: pd.Series, price_m: pd.Series, h: int) -> dict | None:
    """How often gold's move over h months stayed inside the 1- and 2-band range implied at the start."""
    sig = gvz_m / 100 * np.sqrt(h / 12)
    mv = np.log(price_m.shift(-h) / price_m)
    d = pd.DataFrame({"s": sig, "m": mv}).dropna()
    if len(d) < 24:
        return None
    return {"n": int(len(d)), "independent": int(len(d) // h), "first": str(d.index[0]),
            "inside1": float((d.m.abs() <= d.s).mean()), "inside2": float((d.m.abs() <= 2 * d.s).mean()),
            "realised_vs_implied": float(d.m.std() / d.s.mean())}


def expected_move(gvz_daily: pd.Series | None, fut_daily: pd.Series | None, price_usd: float, usdchf: float | None,
                  as_of: pd.Period) -> dict | None:
    if gvz_daily is None or fut_daily is None or not len(gvz_daily.dropna()):
        return None
    g = gvz_daily.dropna()
    vol_now = float(g.iloc[-1])
    gm = _m_last(g)
    pm = _m_last(fut_daily).loc[:as_of]
    r = np.log(pm / pm.shift(1)).dropna()
    realised_long = float(r.std() * np.sqrt(12) * 100)
    realised_3y = float(r.iloc[-36:].std() * np.sqrt(12) * 100)
    vol_pct = float((gm.dropna() < vol_now).mean() * 100)
    rows = []
    for h, src in ((3, "options"), (6, "options"), (12, "options"), (60, "history")):
        v = vol_now if src == "options" else realised_long
        s = v / 100 * np.sqrt(h / 12)
        row = {"months": h, "source": src, "vol": v, "sigma": s,
               "usd": {"lo1": price_usd * np.exp(-s), "hi1": price_usd * np.exp(s),
                       "lo2": price_usd * np.exp(-2 * s), "hi2": price_usd * np.exp(2 * s)}}
        if usdchf:
            row["chf"] = {k: v_ * usdchf for k, v_ in row["usd"].items()}
        if src == "options":
            row["check"] = calibration(gm, pm, h)
        rows.append(row)
    return {"as_of": str(g.index[-1].date()), "vol_now": vol_now, "vol_pct": vol_pct, "vol_since": str(gm.index[0]),
            "realised_long": realised_long, "realised_3y": realised_3y, "price_usd": price_usd, "usdchf": usdchf,
            "rows": rows}


# --- valuation -------------------------------------------------------------------------------------

def valuation(gold_m: pd.Series, cpi_m: pd.Series | None, m2: pd.Series | None, debt_gdp: pd.Series | None,
              deficit_gdp: pd.Series | None, supply: dict | None, since: str = "1975-01") -> dict:
    out = {"supply": supply or {}}
    if cpi_m is not None and len(cpi_m.dropna()):
        cpi = cpi_m.reindex(gold_m.index).ffill(limit=3)
        real = (gold_m * float(cpi.dropna().iloc[-1]) / cpi).dropna().loc[since:]
        now = float(real.iloc[-1])
        pct = float((real < now).mean() * 100)
        peaks = {}
        for lab, a, b in (("1980", "1979-06", "1981-06"), ("2011", "2010-06", "2012-12")):
            seg = real.loc[a:b]
            if len(seg):
                peaks[lab] = {"month": str(seg.idxmax()), "value": float(seg.max())}
        # what followed past months in the top tenth of the real price (known at the time: expanding)
        lr = np.log(real)
        thr = lr.expanding(min_periods=120).quantile(0.9)
        top = (lr >= thr) & thr.notna()
        follow = {}
        for h in (60, 120):
            fwd = forward_return(real, h)
            r_ = rate(real, top, h, "real_top_decile")
            follow[str(h)] = {"median": r_.median, "share_up": r_.share_up, "n_months": r_.n_periods,
                              "n_spells": r_.n_spells, "base_median": r_.base_median,
                              "base_share_up": r_.base_share_up}
        out["real"] = {"now": now, "pct": pct, "since": str(real.index[0]), "peaks": peaks, "after_top_decile": follow,
                       "top_decile_now": bool(top.iloc[-1]),
                       "spark": [round(float(v), 1) for v in real.iloc[::3]], "spark_start": str(real.index[0])}
    if m2 is not None and len(m2.dropna()):
        m = _m_last(m2).reindex(gold_m.index).ffill(limit=3)
        ratio = (gold_m / m).dropna().loc[since:]
        out["m2"] = {"pct": float((ratio < ratio.iloc[-1]).mean() * 100), "since": str(ratio.index[0]),
                     "vs_1980": float(ratio.iloc[-1] / ratio.loc["1979-06":"1981-06"].max()) if len(ratio.loc["1979-06":"1981-06"]) else None,
                     "vs_2011": float(ratio.iloc[-1] / ratio.loc["2010-06":"2012-12"].max()) if len(ratio.loc["2010-06":"2012-12"]) else None,
                     "m2_bn": float(m.dropna().iloc[-1]), "m2_chg_12m": float(m.dropna().iloc[-1] / m.dropna().iloc[-13] - 1)}
    if debt_gdp is not None and len(debt_gdp.dropna()):
        d = debt_gdp.dropna()
        prev = d[d.index <= d.index[-1] - pd.DateOffset(years=5)]
        out["debt"] = {"now": float(d.iloc[-1]), "as_of": str(d.index[-1].date()),
                       "five_years_ago": float(prev.iloc[-1]) if len(prev) else None}
    if deficit_gdp is not None and len(deficit_gdp.dropna()):
        f = deficit_gdp.dropna()
        out["deficit"] = {"now": float(f.iloc[-1]), "year": int(f.index[-1].year),
                          "avg_10y": float(f.iloc[-10:].mean())}
    return out


# --- scenarios -------------------------------------------------------------------------------------

SCENARIOS = [
    ("cuts_weak_dollar", "The Fed cutting and the dollar weakening",
     "Fed direction cutting (6-month change <= -25 bp) and broad dollar down over 6 months"),
    ("sticky_inflation", "Inflation stuck above 3.5%",
     "US CPI y/y > 3.5% (published figure, lagged 1 month)"),
    ("recession", "A US recession",
     "NBER recession months (USREC = 1); dated long after the fact, so today's status is read from the yield curve"),
    ("real_up_fast", "Interest rates after inflation rising fast",
     "Real yield (TIPS from 2003, proxy before) up more than 0.5 pp over 6 months"),
    ("fed_hiking", "The Fed raising rates",
     "Fed direction hiking (6-month change >= +25 bp)"),
]


def scenario_conditions(state: pd.DataFrame, recession: pd.Series | None) -> dict[str, pd.Series]:
    c = {}
    fd = state.get("fed_direction")
    dol = state.get("dollar_chg_6m")
    if fd is not None and dol is not None:
        c["cuts_weak_dollar"] = (fd == "cutting") & (dol < 0)
    if "cpi_yoy" in state:
        c["sticky_inflation"] = state["cpi_yoy"] > 0.035
    if recession is not None and len(recession.dropna()):
        c["recession"] = (_m_last(recession).reindex(state.index) == 1)
    if "real_yield_chg_6m" in state:
        c["real_up_fast"] = state["real_yield_chg_6m"] > 0.5
    if fd is not None:
        c["fed_hiking"] = fd == "hiking"
    return {k: v.fillna(False).astype(bool) for k, v in c.items()}


def scenarios(state: pd.DataFrame, gold_m: pd.Series, recession: pd.Series | None, curve: pd.Series | None,
              price_now: float, since: str = "1975-01", h: int = 12) -> dict:
    conds = scenario_conditions(state.loc[since:], recession)
    p = gold_m.loc[since:]
    rows = []
    curve_m = _m_last(curve)
    warn = None
    if curve_m is not None and len(curve_m) >= 6:
        last6 = curve_m.iloc[-6:]
        warn = {"now": float(curve_m.iloc[-1]), "months_inverted_of_6": int((last6 < 0).sum()), "as_of": str(curve_m.index[-1])}
    for key, plain, tech in SCENARIOS:
        if key not in conds:
            continue
        cond = conds[key]
        r = rate(p, cond.reindex(p.index).fillna(False), h, key)
        if r.n_periods == 0:
            continue
        now = bool(cond.iloc[-1]) if len(cond) else False
        if key == "recession":
            now = bool(warn and warn["months_inverted_of_6"] >= 3)
        rows.append({"key": key, "plain": plain, "tech": tech, "now": now, "n_months": r.n_periods, "n_spells": r.n_spells,
                     "share_up": r.share_up, "median": r.median, "p25": r.p25, "p75": r.p75,
                     "range_usd": [price_now * (1 + r.p25), price_now * (1 + r.p75)]})
    base = rate(p, pd.Series(True, index=p.index), h, "all")
    return {"horizon_months": h, "since": since, "rows": rows, "curve": warn,
            "base": {"share_up": base.share_up, "median": base.median, "p25": base.p25, "p75": base.p75}}


# --- silver --------------------------------------------------------------------------------------------

def silver(gold_fut: pd.Series | None, silver_fut: pd.Series | None, copper_m: pd.Series | None,
           deficit: pd.Series | None, as_of: pd.Period) -> dict | None:
    if gold_fut is None or silver_fut is None or not len(silver_fut.dropna()):
        return None
    from ..indicators.trend import momentum_12_1
    gm, sm = _m_last(gold_fut).loc[:as_of], _m_last(silver_fut).loc[:as_of]
    s_avg = silver_fut.dropna().groupby(silver_fut.dropna().index.to_period("M")).mean().loc[:as_of]
    ratio = (gm / sm).dropna()
    mom = momentum_12_1(s_avg)
    ma = s_avg.rolling(10).mean()
    out = {"ratio": float(ratio.iloc[-1]), "ratio_pct": float((ratio < ratio.iloc[-1]).mean() * 100),
           "ratio_since": str(ratio.index[0]), "ratio_median": float(ratio.median()),
           "price": float(sm.iloc[-1]), "month": str(sm.index[-1]),
           "switch": "In" if mom.iloc[-1] > 0 else "Out", "mom": float(mom.iloc[-1]),
           "light": "In" if s_avg.iloc[-1] > ma.iloc[-1] else "Out", "vs_ma": float(s_avg.iloc[-1] / ma.iloc[-1] - 1),
           "ret_12m": float(sm.iloc[-1] / sm.iloc[-13] - 1) if len(sm) > 13 else None}
    r = np.log(sm / sm.shift(1)).dropna()
    out["vol"] = float(r.std() * np.sqrt(12) * 100)
    c = _m_last(copper_m)
    if c is not None and len(c) > 13:
        out["copper"] = {"price": float(c.iloc[-1]), "month": str(c.index[-1]), "chg_12m": float(c.iloc[-1] / c.iloc[-13] - 1)}
    if deficit is not None and len(deficit.dropna()):
        d = deficit.dropna()
        out["balance"] = {"moz": float(d.iloc[-1]), "year": str(d.index[-1])[:4]}
    return out
