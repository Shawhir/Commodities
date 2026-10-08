"""Release calendar: when each report is due, and whether it has arrived.

Status of a release:
  upcoming   window has not opened
  due        window is open, not received
  late       window closed less than poll_days ago, not received
  overdue    window closed more than poll_days ago, not received
  received   a feed series holds data for the period
  happened   an event (meeting) date has passed and its feed shows a value on or after it
  enter      figures come from a report entered by hand and the window is open or past
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


@dataclass
class Release:
    report_id: str
    name: str
    period: str
    period_start: date
    window_start: date
    window_end: date
    status: str = "upcoming"
    detail: str = ""

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _period_bounds(cadence: str, start: date) -> tuple[date, date, str]:
    p = pd.Timestamp(start)
    if cadence == "monthly":
        return p.date(), (p + pd.offsets.MonthEnd(0)).date(), p.strftime("%Y-%m")
    if cadence == "quarterly":
        return p.date(), (p + pd.offsets.QuarterEnd(0)).date(), f"{p.year}-Q{p.quarter}"
    if cadence == "annual":
        return p.date(), (p + pd.offsets.YearEnd(0)).date(), str(p.year)
    raise ValueError(cadence)


def _snap_weekday(start: date, end: date, weekday: str | None) -> tuple[date, date]:
    if not weekday:
        return start, end
    wd = WEEKDAYS[weekday]
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    hits = [d for d in days if d.weekday() == wd]
    return (hits[0], hits[-1]) if hits else (start, end)


def releases(report_id: str, spec: dict, start: date, end: date) -> list[Release]:
    """All releases whose window overlaps [start, end]."""
    out: list[Release] = []
    name = spec["name"]
    if "dates" in spec:
        for d in spec["dates"]:
            d = pd.Timestamp(d).date()
            if start <= d <= end:
                out.append(Release(report_id, name, str(d), d, d, d))
        return out
    a, b = spec["window_days"]
    cadence = spec["cadence"]
    if cadence == "weekly":
        anchor = WEEKDAYS[spec.get("anchor", "Tue")]
        d = start - timedelta(days=b + 7)
        d += timedelta(days=(anchor - d.weekday()) % 7)
        while d <= end:
            ws, we = d + timedelta(days=a), d + timedelta(days=b)
            if we >= start and ws <= end:
                out.append(Release(report_id, name, str(d), d, ws, we))
            d += timedelta(days=7)
        return out
    freq = {"monthly": "MS", "quarterly": "QS", "annual": "YS"}[cadence]
    for p in pd.date_range(pd.Timestamp(start) - pd.DateOffset(years=2), end, freq=freq):
        ps, pe, label = _period_bounds(cadence, p.date())
        ws, we = _snap_weekday(pe + timedelta(days=a), pe + timedelta(days=b), spec.get("weekday"))
        if we >= start and ws <= end:
            out.append(Release(report_id, name, label, ps, ws, we))
    return out


def _has_period(con, series_ids: list[str], rel: Release, spec: dict) -> bool:
    for sid in series_ids:
        if "dates" in spec or spec.get("cadence") == "weekly":
            row = con.execute("SELECT count(*) FROM observations WHERE series_id = ? AND ref_date >= ?",
                              [sid, rel.period_start]).fetchone()
        else:
            row = con.execute("SELECT count(*) FROM observations WHERE series_id = ? AND ref_date = ?",
                              [sid, rel.period_start]).fetchone()
        if row[0]:
            return True
    return False


def _ingested(con, series_ids: list[str]) -> bool:
    if not series_ids:
        return False
    q = "SELECT count(*) FROM observations WHERE series_id IN (" + ",".join("?" * len(series_ids)) + ")"
    return con.execute(q, series_ids).fetchone()[0] > 0


def status(con, rel: Release, spec: dict, today: date) -> Release:
    feeds = spec.get("feeds", [])
    if feeds and _has_period(con, feeds, rel, spec):
        rel.status = "happened" if spec.get("kind") == "event" else "received"
        return rel
    if rel.window_start > today:
        rel.status = "upcoming"
        return rel
    if spec.get("manual"):
        rel.status = "enter"
        rel.detail = "Enter figures by hand (data/manual/)" if feeds else "Check the publisher's release"
        return rel
    if rel.window_end >= today:
        rel.status = "due"
    elif (today - rel.window_end).days <= spec.get("poll_days", 3):
        rel.status = "late"
    else:
        rel.status = "overdue"
    if feeds and not _ingested(con, feeds):
        rel.detail = "Source not ingested yet (needs a run where the official source is reachable)"
    return rel


def calendar(con, reports_cfg: dict, today: date, back_days: int = 45, ahead_days: int = 60) -> list[Release]:
    rows = []
    for rid, spec in reports_cfg["reports"].items():
        for r in releases(rid, spec, today - timedelta(days=back_days), today + timedelta(days=ahead_days)):
            rows.append(status(con, r, spec, today))
    # A source never ingested, or a report entered by hand, would otherwise list every missed
    # period; keep only the latest such row per report.
    latest: dict[str, Release] = {}
    keep = []
    for r in rows:
        collapsible = r.status == "enter" or (r.status in ("due", "late", "overdue") and "not ingested" in r.detail)
        if collapsible:
            if r.report_id not in latest or r.window_start > latest[r.report_id].window_start:
                latest[r.report_id] = r
        else:
            keep.append(r)
    rows = keep + list(latest.values())
    rows.sort(key=lambda r: (r.window_start, r.report_id))
    return rows
