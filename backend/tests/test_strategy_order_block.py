"""Unit tests for app.strategy.order_block: order block and breaker
block detection, against a hand-constructed 13-candle series with a
known quiet period, one clearly impulsive move, and (for the breaker
case) a subsequent close-through + retest.
"""

from __future__ import annotations

from app.strategy.order_block import detect_breaker_block, detect_order_block


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def _base_candles() -> list[dict]:
    """9 quiet candles (range ~1) + 1 bearish candle (the order block) +
    1 impulsive bullish candle (range >> 1.5x the rolling average range).
    """
    candles = [candle(100, 101, 100, 100.5, f"t{i}") for i in range(9)]
    candles.append(candle(101, 101, 99, 99, "t9"))  # bearish -> order block candidate
    candles.append(candle(100, 111, 99, 110, "t10"))  # impulsive bullish move
    return candles


def test_detect_order_block_none_when_no_impulsive_move():
    candles = [candle(100, 101, 100, 100.5, f"t{i}") for i in range(11)]
    assert detect_order_block(candles) is None


def test_detect_order_block_finds_bearish_candle_before_bullish_impulse():
    candles = _base_candles()

    result = detect_order_block(candles)

    assert result == {"type": "bullish", "top": 101, "bottom": 99, "index": 9}


def test_detect_breaker_block_none_when_zone_never_closed_through():
    candles = _base_candles()
    assert detect_breaker_block(candles) is None


def test_detect_breaker_block_flips_type_after_close_through_and_retest():
    """After the bullish order block (top=101, bottom=99, index=9) is
    fully closed through (a later close < bottom) and then retested from
    below (a later high wicks back up into the zone), the same zone is
    returned with `type` flipped to bearish.
    """
    candles = _base_candles()
    candles.append(candle(99.4, 99.5, 98.5, 98.6, "t11"))  # closes through bottom (99)
    candles.append(candle(98.6, 99.3, 98.5, 99.2, "t12"))  # retest: high (99.3) >= bottom (99)

    result = detect_breaker_block(candles)

    assert result == {"type": "bearish", "top": 101, "bottom": 99, "index": 9}
