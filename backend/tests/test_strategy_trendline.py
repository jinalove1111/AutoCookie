"""Unit tests for app.strategy.trendline: 2-point trendline construction,
break detection, and trendline-liquidity sweep detection. Real detector
calls throughout (nothing mocked), same discipline as every other
strategy test in this package.
"""

from __future__ import annotations

import pytest

from app.strategy.trendline import (
    detect_trendline,
    detect_trendline_break,
    detect_trendline_liquidity_sweep,
    trendline_price_at,
)


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def test_detect_trendline_invalid_direction_raises():
    with pytest.raises(ValueError):
        detect_trendline([], "up")


def test_detect_trendline_none_without_two_swing_points():
    # Gently rising, heavily overlapping ranges: no swing highs/lows ever
    # confirm (strictly increasing) -- see the identical pattern used in
    # test_strategy_entry_point_engine.py's "nothing matches" fixture.
    candles = [
        candle(100 + i * 0.1, 100 + i * 0.1 + 1, 100 + i * 0.1 - 1, 100 + i * 0.1 + 0.5, f"t{i}")
        for i in range(10)
    ]
    assert detect_trendline(candles, "support") is None
    assert detect_trendline(candles, "resistance") is None


# --- Support trendline (ascending, connects swing lows) --------------------


def _ascending_zigzag_candles() -> list[dict]:
    """Verified shape: 2 confirmed swing lows at (index 4, price 8) and
    (index 8, price 12) -- an ascending line, slope 1.0, intercept 4.0,
    projecting to 17.0 at index 13.
    """
    highs = [20, 22, 25, 21, 19, 22, 28, 23, 21, 24, 32, 25, 22]
    lows = [10, 12, 18, 13, 8, 13, 20, 14, 12, 15, 24, 16, 15]
    return [candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]


def test_detect_trendline_support_line_math():
    candles = _ascending_zigzag_candles()

    trendline = detect_trendline(candles, "support")

    assert trendline == {
        "type": "support",
        "point1": {"index": 4, "price": 8},
        "point2": {"index": 8, "price": 12},
        "slope": 1.0,
        "intercept": 4.0,
    }
    assert trendline_price_at(trendline, 12) == 16.0
    assert trendline_price_at(trendline, 16) == 20.0


def test_detect_trendline_break_support_on_close_below_the_line():
    candles = _ascending_zigzag_candles()
    trendline = detect_trendline(candles, "support")
    # line projects to 17.0 at index 13; this candle closes at 15 (below).
    candles_with_break = candles + [candle(18, 19, 16, 15, "t13")]

    result = detect_trendline_break(candles_with_break, trendline)

    assert result == {
        "type": "support_break",
        "trendline_price_at_break": 17.0,
        "break_index": 13,
    }


def test_detect_trendline_liquidity_sweep_support_wick_below_close_back_above():
    candles = _ascending_zigzag_candles()
    trendline = detect_trendline(candles, "support")
    # wicks to 15 (below the 17.0 line) but closes back above it at 18.
    candles_with_sweep = candles + [candle(18, 19, 15, 18, "t13")]

    result = detect_trendline_liquidity_sweep(candles_with_sweep, trendline)

    assert result == {
        "type": "trendline_sweep_support",
        "level": 17.0,
        "sweep_index": 13,
    }


def test_detect_trendline_neither_break_nor_sweep_when_price_stays_above():
    candles = _ascending_zigzag_candles()
    trendline = detect_trendline(candles, "support")
    candles_neutral = candles + [candle(19, 21, 18, 20, "t13")]  # comfortably above 17.0

    assert detect_trendline_break(candles_neutral, trendline) is None
    assert detect_trendline_liquidity_sweep(candles_neutral, trendline) is None


# --- Resistance trendline (descending, connects swing highs) ---------------


def _descending_zigzag_candles() -> list[dict]:
    """Verified shape: 2 confirmed swing highs at (index 4, price 32) and
    (index 8, price 27) -- a descending line, slope -1.25, intercept
    37.0, projecting to 20.75 at index 13.
    """
    highs = [30, 28, 22, 27, 32, 27, 20, 25, 27, 24, 16, 23, 26]
    lows = [20, 18, 15, 17, 22, 17, 12, 15, 17, 14, 8, 14, 17]
    return [candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]


def test_detect_trendline_resistance_line_math():
    candles = _descending_zigzag_candles()

    trendline = detect_trendline(candles, "resistance")

    assert trendline == {
        "type": "resistance",
        "point1": {"index": 4, "price": 32},
        "point2": {"index": 8, "price": 27},
        "slope": -1.25,
        "intercept": 37.0,
    }
    assert trendline_price_at(trendline, 13) == 20.75


def test_detect_trendline_break_resistance_on_close_above_the_line():
    candles = _descending_zigzag_candles()
    trendline = detect_trendline(candles, "resistance")
    candles_with_break = candles + [candle(19.75, 22.75, 18.75, 21.75, "t13")]  # closes above 20.75

    result = detect_trendline_break(candles_with_break, trendline)

    assert result == {
        "type": "resistance_break",
        "trendline_price_at_break": 20.75,
        "break_index": 13,
    }


def test_detect_trendline_liquidity_sweep_resistance_wick_above_close_back_below():
    candles = _descending_zigzag_candles()
    trendline = detect_trendline(candles, "resistance")
    candles_with_sweep = candles + [candle(19.75, 22.75, 18.75, 19.75, "t13")]  # wicks to 22.75, closes at 19.75

    result = detect_trendline_liquidity_sweep(candles_with_sweep, trendline)

    assert result == {
        "type": "trendline_sweep_resistance",
        "level": 20.75,
        "sweep_index": 13,
    }
