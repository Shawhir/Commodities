"""Weekly-close lines: judged only on the last daily close of each completed trading week.

Some lines are watched the way traders state them ("a weekly close below $4,000"), so the
monthly engine in lines.py does not fit. Here each completed week's last close goes through the
same state machine, every close marked as a weekly close, so a single close beyond the line
confirms it and a close back above within ``fail_window_weeks`` counts as a failed break.

A week counts as complete once its Friday has passed (``today`` is after it); the daily loader
already drops a bar dated today, so Thursday's close is never mistaken for Friday's.
"""
from __future__ import annotations

import pandas as pd

from .engine import LineSpec, Transition, run_line


def weekly_closes(close: pd.Series, today: pd.Timestamp | str | None = None) -> pd.Series:
    """Last close of each completed Monday-Friday week, indexed by the date of that close."""
    c = close.dropna().sort_index()
    if not len(c):
        return c
    today = pd.Timestamp(today) if today is not None else pd.Timestamp(pd.Timestamp.now(tz="UTC").date())
    wk = c.index.to_period("W-FRI")
    last = c.groupby(wk).tail(1)
    week_end = last.index.to_period("W-FRI").end_time.normalize()          # the Friday
    return last[week_end < today.normalize()]


def _spec(item: dict) -> LineSpec:
    return LineSpec(id=item["id"], direction=item.get("direction", "below"),
                    buffer_pct=item.get("buffer_pct", 0.0), approach_multiple=1.0,
                    fail_window=item.get("fail_window_weeks", 2), severity=item.get("severity", "important"),
                    market="gold", currency="USD",
                    active_from=str(item["active_from"]) if item.get("active_from") else None)


def evaluate(item: dict, daily_close: pd.Series, today=None) -> tuple[list[Transition], dict]:
    """Run one weekly_close line on daily USD closes. Returns (transitions, status for the page)."""
    wc = weekly_closes(daily_close, today)
    line = float(item["value_usd"])
    spec = _spec(item)
    trans = run_line(spec, wc, line, weekly=pd.Series(True, index=wc.index)) if len(wc) else []
    below = item.get("direction", "below") == "below"
    status = {"id": item["id"], "label": item.get("label", item["id"]), "line": line,
              "direction": item.get("direction", "below"), "severity": spec.severity,
              "note": item.get("note", ""), "source": item.get("source", ""),
              "next_lo": item.get("next_lo_usd"), "next_hi": item.get("next_hi_usd"),
              "state": "no data", "triggered": False}
    if not len(wc):
        return trans, status
    since = wc[wc.index >= pd.Timestamp(item["since"])] if item.get("since") else wc
    beyond = (since < line) if below else (since > line)
    last_d, last_c = wc.index[-1], float(wc.iloc[-1])
    now_beyond = last_c < line if below else last_c > line
    hits = since[beyond]
    status.update({
        "week_ending": str(last_d.date()), "close": last_c, "distance": last_c / line - 1,
        "triggered": bool(now_beyond),
        "state": "triggered" if now_beyond else "holding",
        "since": str(since.index[0].date()) if len(since) else None,
        "weeks_checked": int(len(since)),
        "closes_beyond": int(beyond.sum()),
        "last_beyond": str(hits.index[-1].date()) if len(hits) else None,
        "lowest": float(since.min()) if len(since) else None,
        "lowest_week": str(since.idxmin().date()) if len(since) else None,
        "recent": [{"date": str(d.date()), "close": float(v)} for d, v in wc.tail(8).items()],
        "last_daily": float(daily_close.dropna().iloc[-1]),
        "last_daily_date": str(daily_close.dropna().index[-1].date()),
    })
    if trans:
        t = trans[-1]
        status["engine_state"], status["engine_since"] = t.state, str(pd.Timestamp(t.date).date())
    return trans, status


def evaluate_all(levels_cfg: dict, daily_close: pd.Series | None, market: str = "gold",
                 today=None) -> tuple[list[Transition], list[dict]]:
    items = [i for i in levels_cfg.get(market, []) if i.get("type") == "weekly_close"]
    if daily_close is None or not len(daily_close):
        return [], [{"id": i["id"], "label": i.get("label", i["id"]), "line": float(i["value_usd"]),
                     "state": "no data", "triggered": False} for i in items]
    trans, status = [], []
    for item in items:
        t, s = evaluate(item, daily_close, today)
        trans += t
        status.append(s)
    return trans, status


def to_markdown(status: list[dict]) -> str:
    """Short section for the weekly summary."""
    if not status:
        return ""
    out = ["## Weekly-close lines", ""]
    for w in status:
        if w.get("state") == "no data":
            out.append(f"- **{w['label']}**: no daily prices stored yet.")
            continue
        verb = "TRIGGERED" if w["triggered"] else "holding"
        line = (f"- **{w['label']}**: {verb}. Week ending {w['week_ending']} closed at ${w['close']:,.0f} "
                f"({w['distance']:+.1%} from ${w['line']:,.0f}).")
        if w.get("lowest") is not None:
            line += f" Lowest weekly close since {w['since']}: ${w['lowest']:,.0f} ({w['lowest_week']})."
        line += f" Weekly closes beyond the line since then: {w['closes_beyond']}."
        if w.get("next_lo"):
            line += f" Next stop named if it breaks: ${w['next_lo']:,.0f}-{w['next_hi']:,.0f}."
        out.append(line)
    return "\n".join(out) + "\n"
