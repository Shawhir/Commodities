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
from ..digest.summary import build as build_summary
from ..regime.labeller import label_from_config
from ..testing.seed_study import run_study

TEMPLATE = Path(__file__).with_name("template.html")

STRETCH_LABELS = {
    "dist_10m_avg": "Distance from 10-month average",
    "dist_3y_avg": "Distance from 3-year average",
    "dist_10y_avg": "Distance from 10-year average",
    "return_3y": "3-year return",
    "fall_from_24m_high": "Fall from 24-month high",
}


def _clean(x):
    """JSON-safe: NaN/inf -> None, numpy/pandas scalars -> Python."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
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
    for name, g in (("Price shape only", price), ("Price shape + CHF", groups)):
        df = finder.out_of_sample(st, gold, g, start="2000-01", **kw)
        rows.append({"groups": name, **finder.oos_summary(df)})
    return rows


def build_payload(gold: pd.Series, fx: pd.Series, health: pd.DataFrame | None = None,
                  include_oos: bool = True) -> dict:
    th = config.load("thresholds")
    mk = config.load("markets")
    levels_cfg = config.load("levels")
    float_start = mk["markets"]["gold"]["float_start"]
    s = build_summary(gold, fx, health)
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
            "label": m.get("label", lid) + (f" ({lid.rsplit('_p', 1)[1]}th percentile)" if base != lid else ""),
        })
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
            d["label"] += f" ({d['line_id'].rsplit('_p', 1)[1]}th percentile)"

    # --- stretch ----------------------------------------------------------------------------
    stretch = {}
    for cur, t in s["stretch"].items():
        stretch[cur] = [{"measure": m, "label": STRETCH_LABELS.get(m, m), "value": r.value,
                         "pct_since": r.pct_since_float, "n_since": int(r.n_since_float),
                         "pct_10y": r.pct_10y, "n_10y": int(r.n_10y), "pct_5y": r.pct_5y, "n_5y": int(r.n_5y)}
                        for m, r in t.iterrows()]

    # --- analogues --------------------------------------------------------------------------
    res = s["analogues"]
    st = state.build(gold, fx)
    now = st.loc[as_of]
    an = {
        "target": str(res.target), "summary": res.summary(), "spread": res.spread, "baseline": res.baseline,
        "disagreement": res.disagreement, "used": [LABELS.get(m, m) for m in res.used_measures],
        "dropped": res.dropped_measures, "key_moments": res.key_moments[:5],
        "now": {LABELS.get(m, m): now[m] for m in res.used_measures},
        "matches": [{"month": str(m.month), "distance": m.distance, "group_distance": m.group_distance,
                     "key_moment": m.key_moment, "differences": m.differences, "outcomes": m.outcomes,
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
    study = run_study(gold, fx, dict(th, float_start=float_start))
    summ = study["summary"].reset_index().to_dict("records")
    per = study["per_regime"].reset_index().to_dict("records")
    eps = study["sideways_episodes"].to_dict("records")

    regime = s["regime"].to_dict("records")
    return _clean({
        "as_of": str(as_of), "built": str(date.today()), "disclaimer": s["disclaimer"],
        "regime": regime, "series": series, "manual_lines": manual, "lines": lines,
        "line_notes": s["level_notes"], "triggers": trig, "stretch": stretch, "analogues": an,
        "study": {"summary": summ, "per_regime": per, "episodes": eps, "window": list(study["window"]),
                  "shares": study["regime_shares_since_float"].to_dict()},
        "health": [] if health is None or health.empty else [
            {"source": r.source_id, "latest": str(pd.Timestamp(r.latest_ref_date).date())
             if not pd.isna(r.latest_ref_date) else None, "status": r.status} for r in health.itertuples()],
        "pending": s["pending"],
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
