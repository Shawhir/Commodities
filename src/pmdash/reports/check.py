"""`pmdash reports check`: fetch what is due, record releases, describe what changed.

There is no consensus-forecast feed, so a "surprise" here is measured against the prior
release and the trailing 12-month average, and is labelled as such.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from ..ingest.runner import fetch_all
from ..storage import db
from .calendar import calendar


def revisions(con, series_id: str, since: date) -> pd.DataFrame:
    """Values revised by a vintage first seen on or after ``since`` (old vs new)."""
    df = con.execute(
        """
        SELECT ref_date, available_date, value,
               lag(value) OVER (PARTITION BY ref_date ORDER BY available_date, fetched_at) AS prev
        FROM observations WHERE series_id = ?
        """, [series_id]).df()
    df = df[df["prev"].notna() & (pd.to_datetime(df["available_date"]) >= pd.Timestamp(since))]
    df = df.assign(change=df["value"] - df["prev"])
    return df[["ref_date", "available_date", "prev", "value", "change"]].sort_values("ref_date")


def revision_streak(con, series_id: str) -> tuple[int, str]:
    """Consecutive vintages (newest first) whose net revision has the same sign."""
    df = con.execute(
        """
        SELECT available_date, sum(value - prev) AS net FROM (
            SELECT available_date, value,
                   lag(value) OVER (PARTITION BY ref_date ORDER BY available_date, fetched_at) AS prev
            FROM observations WHERE series_id = ?
        ) WHERE prev IS NOT NULL GROUP BY available_date ORDER BY available_date DESC
        """, [series_id]).df()
    if df.empty:
        return 0, "none"
    sign = df["net"].iloc[0] > 0
    n = 0
    for v in df["net"]:
        if (v > 0) != sign or v == 0:
            break
        n += 1
    return n, "up" if sign else "down"


def _period_end(spec: dict, period_start: date) -> pd.Timestamp:
    p = pd.Timestamp(period_start)
    return {"monthly": p + pd.offsets.MonthEnd(0), "quarterly": p + pd.offsets.QuarterEnd(0),
            "annual": p + pd.offsets.YearEnd(0)}.get(spec.get("cadence"), p)


def headline(con, spec: dict, period_start: date) -> str:
    h = spec.get("headline")
    if not h:
        return ""
    sid, kind = h["series"], h.get("change", "diff")
    s = db.get_series(con, sid)
    if s.empty:
        return ""
    if kind == "event_bp":
        before = s[s.index < pd.Timestamp(period_start)]
        after = s[s.index >= pd.Timestamp(period_start)]
        if before.empty or after.empty:
            return ""
        b, a = before.iloc[-1], after.iloc[0]
        return f"{sid}: {b:.2f}% to {a:.2f}% ({(a - b) * 100:+.0f} bp)"
    s = s[s.index <= _period_end(spec, period_start)]
    if len(s) < 2:
        return ""
    last, prev = s.iloc[-1], s.iloc[-2]
    trail = s.iloc[-13:-1].mean() if len(s) > 13 else float("nan")
    txt = f"{sid} {s.index[-1]:%Y-%m-%d}: {last:,.2f}"
    if kind == "yoy_pct" and len(s) > 12:
        yoy = last / s.iloc[-13] - 1
        prev_yoy = prev / s.iloc[-14] - 1 if len(s) > 13 else float("nan")
        txt += f", {yoy:+.1%} y/y (prior {prev_yoy:+.1%})"
    else:
        txt += f", change vs prior {last - prev:+,.2f}"
        if trail == trail:
            txt += f", vs 12-period average {last - trail:+,.2f}"
    return txt + " (no consensus feed: compared with prior and trend only)"


def check(con, reports_cfg: dict, today: date | None = None, fetch: bool = True) -> list[dict]:
    today = today or date.today()
    rows = calendar(con, reports_cfg, today, back_days=60, ahead_days=0)
    pending = [r for r in rows if r.status in ("due", "late")]
    to_fetch = {s for r in pending for s in reports_cfg["reports"][r.report_id].get("fetch", [])}
    fetched = {}
    if fetch and to_fetch:
        fetched = fetch_all(con, ids=to_fetch)
    out = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for r in calendar(con, reports_cfg, today, back_days=60, ahead_days=0):
        spec = reports_cfg["reports"][r.report_id]
        if r.status == "upcoming":
            continue
        detail = r.detail
        if r.status in ("received", "happened"):
            detail = headline(con, spec, r.period_start) or detail
            revs = []
            for sid in spec.get("feeds", []):
                n = len(revisions(con, sid, today))
                if n:
                    revs.append(f"{sid}: {n} earlier values revised")
            if revs:
                detail += "; " + "; ".join(revs)
        prior = con.execute("SELECT status, received_at FROM releases WHERE report_id = ? AND period = ?",
                            [r.report_id, r.period]).fetchone()
        new_arrival = r.status in ("received", "happened") and (prior is None or prior[0] not in ("received", "happened"))
        received_at = now if new_arrival else (prior[1] if prior else None)
        con.execute("INSERT OR REPLACE INTO releases VALUES (?,?,?,?,?,?,?)",
                    [r.report_id, r.period, r.window_start, r.window_end, received_at, r.status, detail[:500]])
        out.append({**r.as_dict(), "detail": detail, "new": new_arrival})
    for sid, msg in fetched.items():
        if msg.startswith("FAILED"):
            out.append({"report_id": "-", "name": f"fetch {sid}", "period": "", "status": "fetch failed",
                        "detail": msg[:300], "new": False, "window_start": today, "window_end": today})
    return out


def to_markdown(rows: list[dict], upcoming: list) -> str:
    lines = ["## Reports", ""]
    new = [r for r in rows if r.get("new")]
    if new:
        lines += ["**New since last check**", ""] + [f"- {r['name']} ({r['period']}): {r['detail']}" for r in new] + [""]
    waiting = [r for r in rows if r["status"] in ("due", "late", "overdue", "enter", "fetch failed")]
    if waiting:
        lines += ["**Waiting**", "", "| Report | Period | Window | Status | Note |", "|---|---|---|---|---|"]
        for r in waiting:
            lines.append(f"| {r['name']} | {r['period']} | {r['window_start']} to {r['window_end']} | {r['status']} | {r['detail']} |")
        lines.append("")
    if upcoming:
        lines += ["**Next 30 days**", "", "| Report | Period | Expected |", "|---|---|---|"]
        for r in upcoming:
            when = str(r.window_start) if r.window_start == r.window_end else f"{r.window_start} to {r.window_end}"
            lines.append(f"| {r.name} | {r.period} | {when} |")
    return "\n".join(lines) + "\n"
