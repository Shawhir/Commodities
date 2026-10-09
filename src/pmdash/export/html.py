"""Static HTML export of the dashboard: one self-contained file, no server.

The page template (``template.html``) holds layout, styling and drawing code
only. Every number reaches it through one JSON payload built here from the
same modules the CLI and Streamlit app use.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pandas as pd

from .. import config
from ..analogues import finder, state
from ..analogues.state import LABELS
from ..digest import brief as decision_brief
from ..digest.summary import build as build_summary
from ..regime.labeller import label_from_config
from ..testing.seed_study import month_end_closes, realistic, run_study

TEMPLATE = Path(__file__).with_name("template.html")

SOURCE_PLAIN = {
    "gold_usd_monthly": "Gold price, monthly", "usdchf_monthly": "Francs per dollar, monthly",
    "us_cpi_mirror": "US inflation (copy)", "us_10y_yield_monthly": "US 10-year interest rate",
    "vix_daily_mirror": "Stock market fear gauge (copy)", "brent_monthly": "Oil price (Brent)",
    "wti_monthly": "Oil price (US)", "usdchf_daily": "Francs per dollar, daily (copy)",
    "real_yield_10y": "Interest rates after inflation", "breakeven_10y": "Expected inflation",
    "dollar_broad": "US dollar index", "vix_fred": "Stock market fear gauge", "gold_vol": "Gold price swings gauge",
    "fed_funds_eff": "US overnight interest rate", "fed_target_upper": "Fed's target interest rate",
    "us_cpi_fred": "US inflation", "us_core_cpi": "US inflation without food and energy", "us_payrolls": "US jobs",
    "us_unemployment": "US unemployment", "usdchf_fred": "Francs per dollar, daily", "usdchf_yahoo_daily": "Francs per dollar, daily (fresher copy)",
    "cftc_cot": "Speculators' positions", "gpr_monthly": "War and political risk, monthly",
    "gpr_daily": "War and political risk, daily", "manual_reports": "Figures typed in by hand",
}
PENDING = [
    {"text": "A faster weekly mood reading needs daily prices, which aren't connected yet.",
     "tech": "Weekly-close regime reading: needs daily prices (phase 2)."},
    {"text": "Silver, gold fund holdings, exchange warehouse stocks and other market-plumbing data aren't in yet.",
     "tech": "Silver, ETF holdings, COMEX registered stocks, stress indicators, curve/carry: phase 2."},
    {"text": "Tracking of world events by theme, and a written weekly analysis, aren't built yet.",
     "tech": "Theme register and agent weekly read: phases 6 and 7."},
]

STRETCH_LABELS = {
    "dist_10m_avg": "Distance from 10-month average",
    "dist_3y_avg": "Distance from 3-year average",
    "dist_10y_avg": "Distance from 10-year average",
    "return_3y": "3-year return",
    "fall_from_24m_high": "Fall from 24-month high",
}


def _pct_mark(p: str) -> str:
    return {"50": ": halfway mark of history", "90": ": top-10% mark of history"}.get(p, f": {p}% mark of history")


def _clean(x):
    """JSON-safe: NaN/inf -> None, numpy/pandas scalars -> Python."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, date) and not isinstance(x, pd.Timestamp):
        return x.isoformat()
    if isinstance(x, (pd.Period, pd.Timestamp)):
        return str(x.date()) if isinstance(x, pd.Timestamp) else str(x)
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        try:
            x = x.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


def _series(s: pd.Series, index) -> list:
    return [None if pd.isna(v) else round(float(v), 6) for v in s.reindex(index)]


def _oos(st, gold, groups, kw) -> list[dict]:
    rows = []
    price = {"price_shape": groups["price_shape"]}
    others = [g for g in groups if g != "price_shape"]
    macro_only = {g: ms for g, ms in groups.items() if g in ("rates_money", "inflation", "risk")}
    variants = [("Price shape only", price), ("Price + " + ", ".join(o.replace("_", " ") for o in others), groups)]
    if macro_only:
        variants.append(("Macro only (" + ", ".join(g.replace("_", " ") for g in macro_only) + ")", macro_only))
    plain = {"Price shape only": "Price pattern only"}
    for name, g in variants:
        df = finder.out_of_sample(st, gold, g, start="2000-01", **kw)
        rows.append({"groups": name, **finder.oos_summary(df)})
    return rows


def backdrop(macro: dict, fx_daily: pd.Series | None, as_of: pd.Period, since: str) -> list[dict]:
    """Macro readings at the latest month, with 12-month change and percentile since the float."""
    rows = []

    def add(label, s, unit, source, note=""):
        s = s.dropna()
        s = s[s.index <= as_of]
        if s.empty:
            return
        hist = s[since:]
        last = s.iloc[-1]
        prev = s.get(s.index[-1] - 12)
        rows.append({"label": label, "value": float(last), "unit": unit, "month": str(s.index[-1]),
                     "chg_12m": None if prev is None or pd.isna(prev) else float(last - prev),
                     "pct": float((hist < last).mean() * 100) if len(hist) > 1 else None,
                     "n": int(len(hist)), "since": str(hist.index[0]) if len(hist) else None,
                     "source": source, "note": note,
                     "spark": [None if pd.isna(v) else round(float(v), 4) for v in s.iloc[-60:]]})

    if "cpi" in macro:
        c = macro["cpi"]
        add("US inflation (CPI, y/y)", (c / c.shift(12) - 1) * 100, "%", "BLS CPI-U via datasets/cpi-us")
        if "yield_10y" in macro:
            ry = macro["yield_10y"] - ((c / c.shift(12) - 1) * 100).reindex(macro["yield_10y"].index)
            add("Real yield proxy (10y minus CPI)", ry, "pp", "10y Treasury minus CPI y/y",
                "Proxy: TIPS start 1997. Not the market real yield.")
    if "yield_10y" in macro:
        add("US 10-year yield", macro["yield_10y"], "%", "FRED GS10 via datasets/bond-yields-us-10y")
    if "real_yield_tips" in macro:
        add("10-year TIPS real yield", macro["real_yield_tips"], "%", "FRED DFII10")
    if "vix" in macro:
        add("VIX (monthly average)", macro["vix"], "", "CBOE via datasets/finance-vix")
    if "brent" in macro:
        add("Brent crude", macro["brent"], "$", "EIA via datasets/oil-prices")
    if fx_daily is not None and len(fx_daily):
        m = fx_daily.groupby(fx_daily.index.to_period("M")).mean()
        add("USD/CHF (francs per dollar)", m, "", "Fed H.10 via datasets/exchange-rates")
    if "gpr" in macro:
        add("Geopolitical risk index", macro["gpr"], "", "Caldara and Iacoviello")
    return rows


def price_strip(daily: dict | None, fx_daily: pd.Series | None) -> list[dict]:
    """Latest daily close of each metal in dollars and francs, with the day's and the year's change.
    Francs = dollars x francs-per-dollar on the same day (or the latest rate before it, dated)."""
    out = []
    fx = fx_daily.dropna().sort_index() if fx_daily is not None else pd.Series(dtype=float)
    for metal, (df_, src_) in (daily or {}).items():
        if df_ is None or df_.empty:
            continue
        c = df_["close"].dropna()
        if len(c) < 2:
            continue
        d, p = c.index[-1], float(c.iloc[-1])
        yr = c.loc[:d - pd.DateOffset(years=1)]
        row = {"metal": metal, "date": str(d.date()), "source": src_,
               "USD": {"price": p, "chg_1d": p / float(c.iloc[-2]) - 1,
                       "chg_1y": p / float(yr.iloc[-1]) - 1 if len(yr) else None}}
        if len(fx):
            fxc = fx.reindex(c.index, method="ffill")
            chf = (c * fxc).dropna()
            f_at = fx.loc[:d]
            if len(chf) >= 2 and len(f_at):
                cy = chf.loc[:d - pd.DateOffset(years=1)]
                q = float(chf.iloc[-1])
                row["CHF"] = {"price": q, "chg_1d": q / float(chf.iloc[-2]) - 1,
                              "chg_1y": q / float(cy.iloc[-1]) - 1 if len(cy) else None}
                row["fx"] = {"rate": float(f_at.iloc[-1]), "date": str(f_at.index[-1].date())}
        out.append(row)
    return out


def build_payload(gold: pd.Series, fx: pd.Series, health: pd.DataFrame | None = None, macro: dict | None = None,
                  include_oos: bool = True, reports: list[dict] | None = None,
                  fx_daily: pd.Series | None = None, daily: dict | None = None,
                  fx_fresh: pd.Series | None = None, cash: dict | None = None,
                  buyers_series: dict | None = None) -> dict:
    th = config.load("thresholds")
    mk = config.load("markets")
    levels_cfg = config.load("levels")
    float_start = mk["markets"]["gold"]["float_start"]
    s = build_summary(gold, fx, health, macro)
    chf = (gold * fx).dropna()
    as_of = gold.index[-1]

    # --- monthly series since the float -------------------------------------------------
    idx = gold.loc[float_start:].index
    reg_usd = label_from_config(gold, th)["regime"]
    reg_chf = label_from_config(chf, th)["regime"]
    series = {
        "months": [str(m) for m in idx],
        "USD": _series(gold, idx), "CHF": _series(chf, idx), "usdchf": _series(fx, idx),
        "ma10_USD": _series(gold.rolling(10).mean(), idx), "ma10_CHF": _series(chf.rolling(10).mean(), idx),
        "regime_USD": [r if isinstance(r, str) else None for r in reg_usd.reindex(idx)],
        "regime_CHF": [r if isinstance(r, str) else None for r in reg_chf.reindex(idx)],
    }

    # --- key lines ------------------------------------------------------------------------
    meta = {item["id"]: item for item in levels_cfg.get("gold", [])}
    manual = [{"id": i["id"], "label": i.get("label", i["id"]), "value_usd": i["value_usd"], "note": i.get("note", ""),
               "severity": i.get("severity"), "active_from": str(i.get("active_from") or "")}
              for i in levels_cfg.get("gold", []) if i["type"] == "manual_price"]
    lines = []
    ls = s["level_states"]
    for (lid, cur), r in ls.iterrows():
        base = lid.rsplit("_p", 1)[0] if lid.startswith("gold_stretch") else lid
        m = meta.get(base, {})
        dist = None
        if m.get("type") in ("manual_price", "derived_ma") and r.line_value:
            dist = r.close / r.line_value - 1
        lines.append({
            "id": lid, "currency": cur if isinstance(cur, str) else None, "type": m.get("type"),
            "state": r.state, "prev_state": r.prev_state, "watching": r.watching if isinstance(r.watching, str) else None,
            "since": str(pd.Timestamp(r.date).date()), "close": r.close, "line_value": r.line_value,
            "distance": dist, "severity": r.severity, "note": m.get("note", ""),
            "label": m.get("label", lid) + (_pct_mark(lid.rsplit('_p', 1)[1]) if base != lid else ""),
        })
    # Lines that never changed state have no transition yet: add them as intact with today's gap.
    have = {(d["id"], d["currency"]) for d in lines}
    for item in levels_cfg.get("gold", []):
        if item["type"] not in ("manual_price", "derived_ma"):
            continue
        if item.get("active_from") and pd.Period(str(item["active_from"])[:7], "M") > as_of:
            continue
        for cur, p in (("USD", gold), ("CHF", chf)):
            if (item["id"], cur) in have or (item.get("currencies") and cur not in item["currencies"]):
                continue
            if item["type"] == "manual_price":
                lv = float(item["value_usd"]) * (1.0 if cur == "USD" else float(fx.loc[as_of]))
            else:
                lv = float(p.rolling(item["window_months"]).mean().iloc[-1])
            close = float(p.iloc[-1])
            lines.append({"id": item["id"], "currency": cur, "type": item["type"], "state": "intact",
                          "prev_state": None, "watching": item.get("direction"), "since": None, "close": close,
                          "line_value": lv, "distance": close / lv - 1, "severity": item.get("severity"),
                          "note": item.get("note", ""), "label": item.get("label", item["id"])})
    # The last transition's close can be old; show today's reading for every line.
    from ..indicators.trend import momentum_12_1 as _mom
    stretch_now = {}
    for cur_, t_ in s["stretch"].items():
        stretch_now[cur_] = float(t_.loc["dist_10y_avg", "pct_since_float"]) if "dist_10y_avg" in t_.index else None
    for d in lines:
        cur_ = d.get("currency")
        if cur_ not in ("USD", "CHF"):
            continue
        p_ = gold if cur_ == "USD" else chf
        item = meta.get(d["id"].rsplit("_p", 1)[0] if d["id"].startswith("gold_stretch") else d["id"], {})
        typ = item.get("type")
        if typ == "manual_price":
            d["line_value"] = float(item["value_usd"]) * (1.0 if cur_ == "USD" else float(fx.loc[as_of]))
            d["close"] = float(p_.iloc[-1])
        elif typ == "derived_ma":
            d["line_value"] = float(p_.rolling(item["window_months"]).mean().iloc[-1])
            d["close"] = float(p_.iloc[-1])
        elif typ == "signal_zero_cross":
            d["close"] = float(_mom(p_).iloc[-1])
        elif typ == "stretch_percentile" and stretch_now.get(cur_) is not None:
            d["close"] = stretch_now[cur_]
        if typ in ("manual_price", "derived_ma") and d.get("line_value"):
            d["distance"] = d["close"] / d["line_value"] - 1
    sev_rank = {"important": 0, "watch": 1, "info": 2}
    lines.sort(key=lambda d: (sev_rank.get(d["severity"], 3), d["id"], d["currency"] or ""))
    cutoff = as_of.to_timestamp() - pd.DateOffset(months=12)
    trig = [t.to_dict() for t in s["transitions"] if pd.Timestamp(t.date) > cutoff]
    trig.sort(key=lambda d: (pd.Timestamp(d["date"]), d["line_id"]), reverse=True)
    for d in trig:
        d["date"] = str(pd.Timestamp(d["date"]).date())
        base = d["line_id"].rsplit("_p", 1)[0] if d["line_id"].startswith("gold_stretch") else d["line_id"]
        d["label"] = meta.get(base, {}).get("label", d["line_id"])
        if base != d["line_id"]:
            d["label"] += _pct_mark(d["line_id"].rsplit("_p", 1)[1])

    # --- stretch ----------------------------------------------------------------------------
    stretch = {}
    for cur, t in s["stretch"].items():
        stretch[cur] = [{"measure": m, "label": STRETCH_LABELS.get(m, m), "value": r.value,
                         "pct_since": r.pct_since_float, "n_since": int(r.n_since_float),
                         "pct_10y": r.pct_10y, "n_10y": int(r.n_10y), "pct_5y": r.pct_5y, "n_5y": int(r.n_5y)}
                        for m, r in t.iterrows()]

    # --- analogues --------------------------------------------------------------------------
    res = s["analogues"]
    st = state.build(gold, fx, macro)
    now = st.loc[as_of]
    an = {
        "target": str(res.target), "summary": res.summary(), "spread": res.spread, "baseline": res.baseline,
        "disagreement": res.disagreement, "used": [LABELS.get(m, m) for m in res.used_measures],
        "used_tech": res.used_measures, "dropped_plain": [LABELS.get(m, m.replace("_", " ")) for m in res.dropped_measures],
        "dropped": res.dropped_measures, "key_moments": res.key_moments[:5],
        "now": {LABELS.get(m, m): now[m] for m in res.used_measures},
        "matches": [{"month": str(m.month), "distance": m.distance, "group_distance": m.group_distance,
                     "key_moment": m.key_moment, "differences": m.differences, "differences_tech": m.differences_tech,
                     "outcomes": m.outcomes,
                     "then": {LABELS.get(c, c): st.loc[m.month, c] for c in res.used_measures}}
                    for m in res.matches],
    }
    base_chf = finder.forward_outcomes(chf)["fwd_12m"].loc[pd.Period(float_start, "M"):res.target - th["analogues"]["exclude_recent_months"]].dropna()
    an["baseline_chf"] = {"n": int(len(base_chf)), "median": float(base_chf.median()),
                          "share_positive": float((base_chf > 0).mean())}
    if include_oos:
        a = th["analogues"]
        kw = dict(weights=a["group_weights"], candidate_start=a["candidate_start"],
                  exclude_recent=a["exclude_recent_months"], collapse=a["collapse_months"], top_n=a["top_n"],
                  categorical_penalty=a["categorical_penalty"], standardise=a["standardise"])
        an["oos"] = _oos(st, gold, {g: ms for g, ms in a["groups"].items() if any(m in st.columns for m in ms)}, kw)

    # --- section 8 study ----------------------------------------------------------------------
    study = run_study(gold, fx, dict(th, float_start=float_start), cash=cash)
    # the realistic test: real month-end closes, cash rates, costs by how the gold is held
    real = None
    g_daily = (daily or {}).get("gold", (None, None))[0]
    fx_for_closes = fx_fresh if fx_fresh is not None else fx_daily
    if g_daily is not None and fx_for_closes is not None:
        cu = month_end_closes(g_daily["close"], as_of)
        cc = (cu * month_end_closes(fx_for_closes, as_of)).dropna()
        if len(cc) > 36:
            real = realistic(gold, cu, cc, th, cash)
    summ = study["summary"].reset_index().to_dict("records")
    per = study["per_regime"].reset_index().to_dict("records")
    eps = study["sideways_episodes"].to_dict("records")

    regime = s["regime"].to_dict("records")
    stretch_pct = {cur: next((r["pct_since"] for r in rows if r["measure"] == "dist_10y_avg"), None)
                   for cur, rows in stretch.items()}
    brief = decision_brief.build(gold, fx, st, macro or {}, lines, reports or [], stretch_pct, th,
                                 allocation=config.load("allocation"), journal_open=None)
    bad = decision_brief.check_language(brief)
    if bad:
        raise ValueError(f"decision brief contains instruction language: {bad}")
    # what happened after setups like this (monthly) and the daily technical picture
    from ..history import base_rates
    from ..indicators.stretch import measures as _measures
    from ..indicators.trend import ma_signal as _ma_sig, momentum_signal as _mom_sig
    history = base_rates.build_monthly(gold, reg_usd, _mom_sig(gold), _ma_sig(gold),
                                       _measures(gold.loc[float_start:])["dist_10y_avg"])
    guess = base_rates.build_guess(gold, chf, reg_usd, _mom_sig(gold), _ma_sig(gold),
                                   _measures(gold.loc[float_start:])["dist_10y_avg"])
    from ..history import odds as _odds
    weighed = _odds.build(st, gold, chf, up=th["regime"]["up_return_min"], down=th["regime"]["down_return_max"])
    technical = {}
    for metal, (df_, src_) in (daily or {}).items():
        if df_ is not None:
            technical[metal] = base_rates.build_technical(df_, src_)
    prices = price_strip(daily, fx_fresh if fx_fresh is not None else fx_daily)
    buyers_sec = None
    if buyers_series:
        from ..history import buyers as _buyers
        g_now = next((r["USD"]["price"] for r in prices if r["metal"] == "gold"), float(gold.iloc[-1]))
        buyers_sec = _buyers.build(buyers_series, gold, g_now, config.load("buyers"))
    return _clean({
        "prices": prices, "buyers": buyers_sec,
        "history": history, "technical": technical, "guess": guess, "odds": weighed,
        "brief": brief,
        "as_of": str(as_of), "built": str(date.today()), "disclaimer": s["disclaimer"],
        "regime": regime, "series": series, "manual_lines": manual, "lines": lines,
        "line_notes": s["level_notes"], "triggers": trig, "stretch": stretch, "analogues": an,
        "study": {"realistic": real, "main_rule": th["backtest"].get("main_rule", "momentum_12_1"), "cash": {k: v is not None and len(v) > 0 for k, v in (cash or {}).items()},
                  "summary": summ, "per_regime": per, "episodes": eps, "window": list(study["window"]),
                  "shares": study["regime_shares_since_float"].to_dict()},
        "backdrop": backdrop(macro or {}, fx_daily, as_of, float_start),
        "reports": reports or [],
        "health": [] if health is None or health.empty else [
            {"source": r.source_id, "plain": SOURCE_PLAIN.get(r.source_id, r.source_id),
             "latest": str(pd.Timestamp(r.latest_ref_date).date()) if not pd.isna(r.latest_ref_date) else None,
             "status": r.status, "error": None if pd.isna(r.last_error) else r.last_error} for r in health.itertuples()],
        "pending": PENDING + ([{"text": "Alerts based on the wider economy (a jump in interest rates after inflation; "
                                        "how many Fed rate rises markets expect) aren't switched on yet.",
                                "tech": " ".join(s["level_notes"])}] if s["level_notes"] else []),
    })


def render(payload: dict, fragment: bool = False) -> str:
    """Fill the template. ``fragment`` omits the document wrapper (for hosts that add their own)."""
    body = TEMPLATE.read_text()
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    body = body.replace("__PMDASH_DATA__", data)
    if fragment:
        return body
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            "</head>\n<body>\n" + body + "\n</body>\n</html>\n")
