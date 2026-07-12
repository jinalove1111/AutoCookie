"""Unit tests for app.strategy.session_bias: directional bias printed by
the most recently completed Asian/London session. Real datetime
timestamps throughout (this module needs them, same as
session_liquidity.py -- see ENGINEERING_DECISIONS.md #27/#30).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.strategy.session_bias import (
    asian_session_bias,
    london_session_bias,
    session_bias_agreement,
)


def candle(open_: float, high: float, low: float, close: float, ts: datetime) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def _dt(day: int, hour: int, month: int = 1) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=timezone.utc)


def test_asian_session_bias_none_without_a_completed_session():
    assert asian_session_bias([]) is None


def test_asian_session_bias_bullish_when_session_closes_above_its_open():
    candles = [
        candle(100, 105, 98, 102, _dt(14, 1)),
        candle(102, 108, 101, 106, _dt(14, 4)),
        candle(106, 112, 105, 110, _dt(14, 7)),
        candle(110, 115, 109, 112, _dt(14, 12)),  # "now": after Asian (00:00-08:00) ended
    ]
    assert asian_session_bias(candles) == "bullish"


def test_asian_session_bias_bearish_when_session_closes_below_its_open():
    candles = [
        candle(110, 112, 98, 106, _dt(14, 1)),
        candle(106, 108, 95, 101, _dt(14, 4)),
        candle(101, 103, 90, 95, _dt(14, 7)),
        candle(95, 97, 90, 93, _dt(14, 12)),
    ]
    assert asian_session_bias(candles) == "bearish"


def test_asian_session_bias_neutral_when_session_closes_at_its_open():
    candles = [
        candle(100, 105, 98, 102, _dt(14, 1)),
        candle(102, 108, 95, 100, _dt(14, 7)),  # closes exactly at 100 (the session's open)
        candle(100, 101, 99, 100, _dt(14, 12)),
    ]
    assert asian_session_bias(candles) == "neutral"


def test_asian_session_bias_uses_yesterdays_session_when_todays_still_forming():
    candles = [
        candle(100, 110, 95, 108, _dt(13, 2)),  # yesterday's completed Asian session: bullish
        candle(90, 95, 80, 82, _dt(14, 2)),     # "now": inside TODAY's still-forming Asian session
    ]
    assert asian_session_bias(candles) == "bullish"


def test_london_session_bias_mirrors_asian():
    candles = [
        candle(100, 105, 98, 102, _dt(14, 9)),
        candle(102, 108, 101, 106, _dt(14, 12)),
        candle(106, 112, 105, 110, _dt(14, 15)),
        candle(110, 115, 109, 112, _dt(14, 18)),  # "now": after London (08:00-16:00) ended
    ]
    assert london_session_bias(candles) == "bullish"


def test_session_bias_agreement_true_when_both_bullish():
    candles = [
        candle(100, 105, 98, 105, _dt(14, 1)),   # Asian: bullish (100 -> 105)
        candle(105, 110, 104, 105, _dt(14, 7)),
        candle(105, 112, 104, 112, _dt(14, 9)),  # London: bullish (105 -> 112)
        candle(112, 118, 111, 118, _dt(14, 15)),
        candle(118, 119, 117, 118, _dt(14, 18)),  # "now": after London ended
    ]
    result = session_bias_agreement(candles)
    assert result == {"asian_bias": "bullish", "london_bias": "bullish", "agrees": True}


def test_session_bias_agreement_false_when_sessions_disagree():
    candles = [
        candle(100, 105, 98, 105, _dt(14, 1)),   # Asian: bullish
        candle(105, 110, 104, 105, _dt(14, 7)),
        candle(105, 106, 95, 95, _dt(14, 9)),    # London: bearish (105 -> 95)
        candle(95, 96, 90, 92, _dt(14, 15)),
        candle(92, 93, 90, 91, _dt(14, 18)),
    ]
    result = session_bias_agreement(candles)
    assert result["asian_bias"] == "bullish"
    assert result["london_bias"] == "bearish"
    assert result["agrees"] is False


def test_session_bias_agreement_false_when_either_session_missing():
    candles = [
        candle(100, 105, 98, 102, _dt(14, 1)),
        candle(102, 108, 101, 106, _dt(14, 7)),
    ]
    result = session_bias_agreement(candles)
    assert result["london_bias"] is None
    assert result["agrees"] is False
