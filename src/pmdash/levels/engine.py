"""Key-level state machine (section 9.12). Judged on closes only, never touches.

States: intact -> approaching -> broken -> confirmed -> (failed | intact)

- ``approaching``: close within ``approach_multiple`` x buffer of the line, on the intact side,
  or beyond the line but not yet beyond the buffer.
- ``broken``: close beyond the line by more than the buffer.
- ``confirmed``: a second consecutive close beyond the buffer, or a weekly (or monthly) close beyond it.
- ``failed``: after a break, a close back on the intact side of the line within
  ``fail_window`` closes of the break.

Direction ``below`` watches for breaks under the line, ``above`` over it.
``both`` watches the side opposite to where price currently sits; after a
confirmed break that survives the fail window, the watched side flips.

Only ``confirmed`` and ``failed`` transitions are alerts.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import pandas as pd

INTACT, APPROACHING, BROKEN, CONFIRMED, FAILED = "intact", "approaching", "broken", "confirmed", "failed"
ALERT_STATES = {CONFIRMED, FAILED}


@dataclass
class LineSpec:
    id: str
    direction: str = "below"            # below | above | both
    buffer_pct: float | None = 1.0      # percent of the line value
    buffer_abs: float | None = None     # absolute buffer (for signals around zero)
    approach_multiple: float = 2.0
    fail_window: int = 10               # closes
    severity: str = "info"
    market: str | None = None
    currency: str | None = None
    active_from: str | None = None      # closes before this date are ignored (line did not exist)

    def buffer(self, line_value: float) -> float:
        if self.buffer_abs is not None:
            return self.buffer_abs
        return abs(line_value) * (self.buffer_pct or 0.0) / 100.0


@dataclass
class Transition:
    line_id: str
    date: pd.Timestamp
    prev_state: str
    state: str
    close: float
    line_value: float
    severity: str
    alert: bool
    weekly_close: bool = False
    monthly_close: bool = False
    market: str | None = None
    currency: str | None = None
    watching: str | None = None         # side a break would go to after this transition

    @property
    def trigger_id(self) -> str:
        cur = f":{self.currency}" if self.currency else ""
        return f"{self.line_id}{cur}:{self.state}:{pd.Timestamp(self.date).date()}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["trigger_id"] = self.trigger_id
        return d


@dataclass
class _State:
    state: str = INTACT
    watch: str | None = None            # 'below' or 'above': side a break would go to
    closes_beyond: int = 0
    closes_since_break: int = 0
    history: list = field(default_factory=list)


def _beyond(close: float, line: float, buf: float, watch: str) -> bool:
    return close < line - buf if watch == "below" else close > line + buf


def _past_line(close: float, line: float, watch: str) -> bool:
    return close < line if watch == "below" else close > line


def _near(close: float, line: float, buf: float, mult: float, watch: str) -> bool:
    return close <= line + mult * buf if watch == "below" else close >= line - mult * buf


def run_line(spec: LineSpec, closes: pd.Series, line: pd.Series | float,
             weekly: pd.Series | None = None, monthly: pd.Series | None = None) -> list[Transition]:
    """Run the state machine over a close series. Returns transitions only.

    ``weekly``/``monthly`` are boolean Series marking closes that end a week/month.
    """
    line_s = line.reindex(closes.index) if isinstance(line, pd.Series) else pd.Series(float(line), index=closes.index)
    weekly = weekly.reindex(closes.index).fillna(False) if weekly is not None else pd.Series(False, index=closes.index)
    monthly = monthly.reindex(closes.index).fillna(False) if monthly is not None else pd.Series(False, index=closes.index)
    st = _State(watch=None if spec.direction == "both" else spec.direction)
    out: list[Transition] = []

    def emit(t, new, c, lv, wk, mo):
        st_prev, st.state = st.state, new
        out.append(Transition(spec.id, t, st_prev, new, float(c), float(lv), spec.severity,
                              new in ALERT_STATES, bool(wk), bool(mo), spec.market, spec.currency, st.watch))

    if spec.active_from is not None:
        closes = closes[closes.index >= pd.Timestamp(spec.active_from)]
    for t, c in closes.items():
        lv = line_s.get(t)
        if pd.isna(c) or pd.isna(lv):
            continue
        wk, mo = bool(weekly[t]) or bool(monthly[t]), bool(monthly[t])
        if st.watch is None:            # 'both': watch the side opposite to where price sits
            st.watch = "below" if c >= lv else "above"
        buf = spec.buffer(lv)
        beyond = _beyond(c, lv, buf, st.watch)

        if st.state in (INTACT, APPROACHING, FAILED):
            if beyond:
                emit(t, BROKEN, c, lv, wk, mo)
                st.closes_beyond, st.closes_since_break = 1, 0
                if wk:
                    emit(t, CONFIRMED, c, lv, wk, mo)
            else:
                near = _past_line(c, lv, st.watch) or _near(c, lv, buf, spec.approach_multiple, st.watch)
                new = APPROACHING if near else INTACT
                if new != st.state:
                    emit(t, new, c, lv, wk, mo)
            continue

        # BROKEN or CONFIRMED
        st.closes_since_break += 1
        back_inside = not _past_line(c, lv, st.watch)
        if back_inside:
            within = st.closes_since_break <= spec.fail_window
            emit(t, FAILED if within else INTACT, c, lv, wk, mo)
            st.closes_beyond = 0
            continue
        st.closes_beyond = st.closes_beyond + 1 if beyond else 0   # consecutive closes beyond
        if beyond:
            if st.state == BROKEN and (st.closes_beyond >= 2 or wk):
                emit(t, CONFIRMED, c, lv, wk, mo)
        if (st.state == CONFIRMED and spec.direction == "both"
                and st.closes_since_break > spec.fail_window):
            # Break has held: the line is now intact from the other side.
            st.watch = "below" if st.watch == "above" else "above"
            emit(t, INTACT, c, lv, wk, mo)
            st.closes_beyond = 0
    return out


def current_state(transitions: list[Transition]) -> str:
    return transitions[-1].state if transitions else INTACT
