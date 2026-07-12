"""Unit tests for app.strategy.session_liquidity: previous day/week/
session high-low. Uses real `datetime` timestamps (the only strategy
detector that needs them) -- 2026-01-14 is a Wednesday, same reference
date test_backtest_engine.py's own day/week bounds tests use, so the
ISO week (Mon 2026-01-12 - Sun 2026-01-18) is independently verified
there too.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.strategy.session_liquidity import (
    asian_session_high_low,
    london_session_high_low,
    previous_daily_high_low,
    previous_session_high_low,
    previous_weekly_high_low,
)


def candle(high: float, low: float, ts: datetime) -> dict:
    mid = (high + low) / 2
    return {"open": mid, "high": high, "low": low, "close": mid, "timestamp": ts}


def _dt(day: int, hour: int, minute: int = 0, month: int = 1) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


def test_previous_daily_high_low_returns_none_on_empty_candles():
    assert previous_daily_high_low([]) is None


def test_previous_daily_high_low_uses_the_immediately_preceding_day():
    candles = [
        candle(100, 90, _dt(12, 10)),   # Jan 12: two days before "now"
        candle(200, 5, _dt(12, 14)),    # would be picked WRONGLY if this leaked in
        candle(120, 95, _dt(13, 9)),    # Jan 13: the immediately preceding day
        candle(130, 98, _dt(13, 15)),
        candle(110, 100, _dt(14, 3)),   # Jan 14: "now" (still-forming, must be excluded)
    ]

    result = previous_daily_high_low(candles)

    assert result["high"] == 130  # from Jan 13 candles only
    assert result["low"] == 95


def test_previous_weekly_high_low_uses_the_immediately_preceding_iso_week():
    candles = [
        # Week of Jan 5-11 (two weeks before "now"): must be excluded.
        candle(500, 1, _dt(6, 12)),
        # Week of Jan 12-18 (the immediately preceding week).
        candle(150, 80, _dt(12, 9)),
        candle(160, 85, _dt(15, 12)),
        # "Now", inside the week of Jan 19-25 -- still-forming, excluded.
        candle(140, 90, _dt(20, 3)),
    ]

    result = previous_weekly_high_low(candles)

    assert result["high"] == 160
    assert result["low"] == 80


# --- Asian / London session high-low ---------------------------------------


def test_asian_session_high_low_uses_todays_session_once_it_has_ended():
    candles = [
        candle(50, 40, _dt(14, 3)),   # inside today's Asian window (00:00-08:00)
        candle(60, 35, _dt(14, 6)),   # still inside today's Asian window
        candle(20, 10, _dt(14, 12)),  # "now": AFTER today's Asian session ended
    ]

    result = asian_session_high_low(candles)

    assert result["high"] == 60
    assert result["low"] == 35


def test_asian_session_high_low_uses_yesterdays_session_when_still_forming():
    """"Now" sits INSIDE today's Asian window -- that session isn't
    complete yet, so the pool must come from YESTERDAY's Asian session.
    """
    candles = [
        candle(90, 70, _dt(13, 3)),   # yesterday's Asian session (completed)
        candle(20, 10, _dt(14, 2)),   # "now": inside TODAY's still-forming Asian session
    ]

    result = asian_session_high_low(candles)

    assert result["high"] == 90
    assert result["low"] == 70


def test_london_session_high_low_uses_todays_session_once_it_has_ended():
    candles = [
        candle(150, 120, _dt(14, 9)),   # inside today's London window (08:00-16:00)
        candle(160, 110, _dt(14, 15)),  # still inside
        candle(140, 130, _dt(14, 18)),  # "now": after today's London session ended
    ]

    result = london_session_high_low(candles)

    assert result["high"] == 160
    assert result["low"] == 110


def test_previous_session_high_low_picks_whichever_ended_more_recently():
    """"Now" sits right after today's London session ends -- London ended
    more recently than today's (already-completed) Asian session, so
    London's high/low must win, not Asian's.
    """
    candles = [
        candle(50, 40, _dt(14, 3)),      # today's Asian session
        candle(150, 120, _dt(14, 10)),   # today's London session
        candle(999, 999, _dt(14, 16, 1)),  # "now": right after London ends
    ]

    result = previous_session_high_low(candles)

    assert result["high"] == 150
    assert result["low"] == 120


def test_previous_session_high_low_returns_none_on_empty_candles():
    assert previous_session_high_low([]) is None
