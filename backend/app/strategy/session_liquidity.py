"""Jade Session & Weekly/Daily Liquidity.

Closes the 5 liquidity sources deferred as explicit `TODO`s in
`entry_point_engine.py`'s Liquidity Raid model (ENGINEERING_DECISIONS.md
#23): Previous Weekly High/Low, Previous Daily High/Low, Previous
Session High/Low, Asian High/Low, London High/Low. These were deferred
specifically because they need real session/day/week TIMEZONE-BOUNDARY
definitions -- unlike every other detector in this package, which only
cares about candle ORDER (index), these genuinely need to parse
`cf(candle, "timestamp")` as a real UTC `datetime`
(`app.data.data_normalizer.normalize_candle` produces exactly that for
real production candles; every OTHER detector in this package never
reads the field at all, so this module is the first that requires it).

No spec document defines Jade's exact session windows; per operator
instruction (2026-07-12: "if any ambiguity exists, implement the most
reasonable ICT/Jade interpretation and document it in
ENGINEERING_DECISIONS.md instead of waiting for approval"), the Asian/
London windows below are the commonly-cited ICT convention, disclosed
as a default rather than backtest-tuned -- see ENGINEERING_DECISIONS.md
#27 for the full rationale, including why the day/week boundary math is
REIMPLEMENTED here rather than imported from
`app.backtesting.backtest_engine` (which already has equivalent
`_day_bounds`/`_week_bounds` helpers).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from .utils import cf

# Disclosed ICT convention, not backtest-tuned -- see ENGINEERING_DECISIONS.md #27.
_ASIAN_SESSION = (time(0, 0), time(8, 0))  # 00:00-08:00 UTC
_LONDON_SESSION = (time(8, 0), time(16, 0))  # 08:00-16:00 UTC


def _day_bounds(ts: datetime) -> tuple[datetime, datetime]:
    """UTC calendar day `[00:00:00, 23:59:59.999999]` containing `ts`.
    Same convention as `app.backtesting.backtest_engine._day_bounds`/
    `TradeJournal.generate_daily_report` (docs/risk_rules.md).
    """
    day = ts.date()
    return (
        datetime.combine(day, time.min, tzinfo=timezone.utc),
        datetime.combine(day, time.max, tzinfo=timezone.utc),
    )


def _week_bounds(ts: datetime) -> tuple[datetime, datetime]:
    """ISO calendar week (Monday through Sunday, UTC) containing `ts`.
    Same convention as `app.backtesting.backtest_engine._week_bounds`.
    """
    monday = ts.date() - timedelta(days=ts.weekday())
    sunday = monday + timedelta(days=6)
    return (
        datetime.combine(monday, time.min, tzinfo=timezone.utc),
        datetime.combine(sunday, time.max, tzinfo=timezone.utc),
    )


def _high_low_in_window(candles: list, start: datetime, end: datetime) -> dict | None:
    window = [c for c in candles if start <= cf(c, "timestamp") <= end]
    if not window:
        return None
    return {
        "high": max(cf(c, "high") for c in window),
        "low": min(cf(c, "low") for c in window),
        "window_start": start,
        "window_end": end,
    }


def previous_daily_high_low(candles: list) -> dict | None:
    """High/low of the UTC calendar day immediately BEFORE the day the
    last candle falls in -- a fully completed day, never the
    still-forming current one.
    """
    if not candles:
        return None
    today_start, _ = _day_bounds(cf(candles[-1], "timestamp"))
    prev_day_start, prev_day_end = _day_bounds(today_start - timedelta(microseconds=1))
    return _high_low_in_window(candles, prev_day_start, prev_day_end)


def previous_weekly_high_low(candles: list) -> dict | None:
    """High/low of the ISO calendar week immediately BEFORE the week the
    last candle falls in -- mirrors `previous_daily_high_low`.
    """
    if not candles:
        return None
    this_week_start, _ = _week_bounds(cf(candles[-1], "timestamp"))
    prev_week_start, prev_week_end = _week_bounds(this_week_start - timedelta(microseconds=1))
    return _high_low_in_window(candles, prev_week_start, prev_week_end)


def _most_recent_completed_session(last_ts: datetime, session: tuple[time, time]) -> tuple[datetime, datetime]:
    """The most recently COMPLETED occurrence of `session` (a
    `(start_time, end_time)` UTC pair) as of `last_ts` -- today's
    occurrence if it has already ended, otherwise yesterday's (a
    still-forming or not-yet-started session isn't a completed
    liquidity pool yet).
    """
    day = last_ts.date()
    start_t, end_t = session
    start = datetime.combine(day, start_t, tzinfo=timezone.utc)
    end = datetime.combine(day, end_t, tzinfo=timezone.utc)
    if last_ts < end:
        day = day - timedelta(days=1)
        start = datetime.combine(day, start_t, tzinfo=timezone.utc)
        end = datetime.combine(day, end_t, tzinfo=timezone.utc)
    return start, end


def asian_session_high_low(candles: list) -> dict | None:
    """High/low of the most recently completed Asian session (00:00-08:00 UTC)."""
    if not candles:
        return None
    start, end = _most_recent_completed_session(cf(candles[-1], "timestamp"), _ASIAN_SESSION)
    return _high_low_in_window(candles, start, end)


def london_session_high_low(candles: list) -> dict | None:
    """High/low of the most recently completed London session (08:00-16:00 UTC)."""
    if not candles:
        return None
    start, end = _most_recent_completed_session(cf(candles[-1], "timestamp"), _LONDON_SESSION)
    return _high_low_in_window(candles, start, end)


def previous_session_high_low(candles: list) -> dict | None:
    """High/low of whichever of Asian/London most recently completed --
    "the previous session" without naming a specific one.
    """
    if not candles:
        return None
    last_ts = cf(candles[-1], "timestamp")
    asian_start, asian_end = _most_recent_completed_session(last_ts, _ASIAN_SESSION)
    london_start, london_end = _most_recent_completed_session(last_ts, _LONDON_SESSION)
    start, end = (london_start, london_end) if london_end > asian_end else (asian_start, asian_end)
    return _high_low_in_window(candles, start, end)
