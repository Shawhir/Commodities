"""Forecast scorecard: record what the page publishes, score it when the outcome is known.

Backtests flatter; a live record does not. Once a month (the first build after a new month of
prices) the page's forward-looking numbers are appended to data/scorecard/forecasts.csv:

- expected_move   3, 6, 12 months: the options-implied 1-band range around the futures price
                  (should hold about 68% of the time)
- odds_12m        the shown odds and gold's normal odds for rising / sideways / falling
                  (scored with the Brier score; lower is better)
- range_12m       the "price ranges from history" middle half for 1 year (should hold ~50%)
- main_switch     the main switch's state, scored by gold's next-month return while ON vs OFF

Rows are never edited after they are written; scoring is recomputed from prices each build.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["made", "kind", "months", "price", "lo", "hi", "p_rising", "p_sideways", "p_falling",
           "n_rising", "n_sideways", "n_falling", "state", "up", "down"]


def load(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, dtype={"made": str, "kind": str, "state": str})
    return pd.DataFrame(columns=COLUMNS)


def record(path: Path, made: str, payload: dict) -> int:
    """Append this month's published numbers once. ``made`` is the latest price month (YYYY-MM)."""
    log = load(path)
    if len(log) and (log["made"] == made).any():
        return 0
    rows = []
    em = payload.get("expected")
    if em:
        for r in em["rows"]:
            if r["source"] == "options":
                rows.append({"made": made, "kind": "expected_move", "months": r["months"], "price": em["price_usd"],
                             "lo": r["usd"]["lo1"], "hi": r["usd"]["hi1"]})
    od = (payload.get("odds") or {}).get("currencies", {}).get("USD")
    if od:
        n = od["normal_odds"]
        skill = (od.get("track") or {}).get("skill")
        o = od["odds"] if isinstance(skill, (int, float)) and skill > 0 else n     # what the page shows
        rows.append({"made": made, "kind": "odds_12m", "months": 12, "price": None,
                     "p_rising": o["rising"], "p_sideways": o["sideways"], "p_falling": o["falling"],
                     "n_rising": n["rising"], "n_sideways": n["sideways"], "n_falling": n["falling"],
                     "up": payload["odds"].get("up"), "down": payload["odds"].get("down")})
    gu = (payload.get("guess") or {}).get("currencies", {}).get("USD")
    if gu:
        one = next((r for r in gu.get("rows", []) if r.get("years") == 1), None)
        lt = (one or {}).get("like_today") or {}
        if lt.get("price_lo") is not None:
            rows.append({"made": made, "kind": "range_12m", "months": 12, "price": gu.get("now"),
                         "lo": lt["price_lo"], "hi": lt["price_hi"]})
    rules = (payload.get("brief") or {}).get("rules", {}).get("USD")
    if rules:
        rows.append({"made": made, "kind": "main_switch", "months": 1, "state": rules["momentum"]["state"]})
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    new = pd.concat([log, pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True) if len(log) else pd.DataFrame(rows, columns=COLUMNS)
    new.to_csv(path, index=False, float_format="%.6g")
    return len(rows)


def _brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(((p - np.eye(3)[y]) ** 2).sum(axis=1).mean())


def score(log: pd.DataFrame, gold_avg_m: pd.Series, fut_m: pd.Series | None) -> dict:
    """Score every row whose horizon has passed. ``gold_avg_m``: monthly average price (the odds,
    ranges and rules use it); ``fut_m``: month-end futures close (the expected move uses it)."""
    out = {"recorded": int(len(log)), "first": None if not len(log) else str(log["made"].min()), "kinds": {}}
    if not len(log):
        return out
    last_avg = gold_avg_m.index[-1]
    for kind, part in log.groupby("kind"):
        res = {"recorded": int(len(part)), "scored": 0}
        hits, b_model, b_norm, ys, on_ret, off_ret = [], [], [], [], [], []
        for _, r in part.iterrows():
            made = pd.Period(r["made"], "M")
            tgt = made + int(r["months"])
            if kind == "expected_move":
                if fut_m is None or tgt not in fut_m.index:
                    continue
                v = float(fut_m[tgt])
                hits.append(r["lo"] <= v <= r["hi"])
            elif kind == "range_12m":
                if tgt > last_avg:
                    continue
                v = float(gold_avg_m[tgt])
                hits.append(r["lo"] <= v <= r["hi"])
            elif kind == "odds_12m":
                if tgt > last_avg or made not in gold_avg_m.index:
                    continue
                ret = gold_avg_m[tgt] / gold_avg_m[made] - 1
                y = 0 if ret >= r["up"] else 2 if ret <= r["down"] else 1
                ys.append(y)
                b_model.append([r["p_rising"], r["p_sideways"], r["p_falling"]])
                b_norm.append([r["n_rising"], r["n_sideways"], r["n_falling"]])
            elif kind == "main_switch":
                if tgt > last_avg or made not in gold_avg_m.index:
                    continue
                ret = float(gold_avg_m[tgt] / gold_avg_m[made] - 1)
                (on_ret if r["state"] == "In" else off_ret).append(ret)
        if kind in ("expected_move", "range_12m"):
            res["scored"] = len(hits)
            res["hit_rate"] = float(np.mean(hits)) if hits else None
            res["target"] = 0.68 if kind == "expected_move" else 0.50
            if kind == "expected_move":
                res["by_months"] = {}
                for m, sub in part.groupby("months"):
                    hs = []
                    for _, r in sub.iterrows():
                        tgt = pd.Period(r["made"], "M") + int(m)
                        if fut_m is not None and tgt in fut_m.index:
                            hs.append(r["lo"] <= float(fut_m[tgt]) <= r["hi"])
                    res["by_months"][str(int(m))] = {"scored": len(hs), "hit_rate": float(np.mean(hs)) if hs else None}
        elif kind == "odds_12m":
            res["scored"] = len(ys)
            if ys:
                y = np.array(ys)
                res["brier_model"] = _brier(np.array(b_model), y)
                res["brier_normal"] = _brier(np.array(b_norm), y)
        elif kind == "main_switch":
            res["scored"] = len(on_ret) + len(off_ret)
            res["avg_next_month_on"] = float(np.mean(on_ret)) if on_ret else None
            res["avg_next_month_off"] = float(np.mean(off_ret)) if off_ret else None
            res["n_on"], res["n_off"] = len(on_ret), len(off_ret)
        # when the first result of this kind arrives
        months = part["months"].astype(int).min()
        res["first_due"] = str(pd.Period(part["made"].min(), "M") + int(months))
        out["kinds"][kind] = res
    return out
