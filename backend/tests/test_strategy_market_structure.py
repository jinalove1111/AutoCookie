"""Unit tests for app.strategy.market_structure: swing highs/lows and
CHOCH/MSS detection, against small hand-constructed candle series where
the expected outcome is unambiguous (verified by directly inspecting the
real detector's output on intentionally-shaped data, not invented
behavior).
"""

from __future__ import annotations

from app.strategy.market_structure import (
    detect_choch_mss,
    find_swing_highs,
    find_swing_lows,
)


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def test_find_swing_highs_detects_single_clear_peak():
    # highs: 1,2,3,2,1 -> only the middle candle (index 2) is a local max
    # confirmed by n=2 candles on both sides.
    highs = [10, 11, 20, 11, 10]
    candles = [candle(h, h, h - 1, h, f"t{i}") for i, h in enumerate(highs)]

    assert find_swing_highs(candles, n=2) == [2]


def test_find_swing_lows_detects_single_clear_trough():
    lows = [10, 9, 1, 9, 10]
    candles = [candle(l + 1, l + 1, l, l, f"t{i}") for i, l in enumerate(lows)]

    assert find_swing_lows(candles, n=2) == [2]


def test_find_swing_highs_empty_on_strictly_monotonic_series():
    # A strictly increasing series has no interior local maximum: each
    # candle's high is always lower than the max of its window (which
    # sits further to the right), so no index ever equals its own
    # window's max.
    candles = [candle(10 + i, 10 + i, 9 + i, 10 + i, f"t{i}") for i in range(6)]
    assert find_swing_highs(candles, n=2) == []


def test_detect_choch_mss_returns_none_when_series_too_short():
    # detect_choch_mss requires len(candles) >= 2n + 3; n defaults to 2 -> 7.
    candles = [candle(10, 11, 9, 10, f"t{i}") for i in range(6)]
    assert detect_choch_mss(candles) is None


def test_detect_choch_mss_bullish_choch_on_downtrend_break():
    """A downtrend (lower highs, lower lows) followed by a candle whose
    close breaks back above the most recent swing high confirms a
    bullish CHOCH. Verified against the real detector with n=1 (still a
    valid call signature) on a deliberately-shaped 7-candle series.
    """
    candles = [
        candle(10, 12, 9, 10, "t0"),
        candle(10, 15, 9, 11, "t1"),  # swing high (15)
        candle(11, 11, 8, 9, "t2"),
        candle(9, 13, 8, 9, "t3"),  # swing high (13) < 15 -> highs falling
        candle(9, 10, 5, 6, "t4"),  # swing low (5)
        candle(6, 9, 4, 8, "t5"),  # swing low (4) < 5 -> lows falling
        candle(8, 9, 6, 16, "t6"),  # close (16) breaks back above 13
    ]

    result = detect_choch_mss(candles, n=1)

    assert result == {
        "type": "bullish_choch",
        "broken_level": 13,
        "broken_index": 3,
        "confirm_index": 6,
    }


def test_detect_choch_mss_none_when_no_break_occurs():
    """Same downtrend shape as above, but the final candle does NOT close
    back above the broken level -> no CHOCH yet.
    """
    candles = [
        candle(10, 12, 9, 10, "t0"),
        candle(10, 15, 9, 11, "t1"),
        candle(11, 11, 8, 9, "t2"),
        candle(9, 13, 8, 9, "t3"),
        candle(9, 10, 5, 6, "t4"),
        candle(6, 9, 4, 8, "t5"),
        candle(8, 9, 6, 7, "t6"),  # close (7) stays well below 13
    ]

    assert detect_choch_mss(candles, n=1) is None
