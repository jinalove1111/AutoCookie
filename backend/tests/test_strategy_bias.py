"""Unit tests for app.strategy.bias: HTF bias detection from swing
highs/lows, against hand-constructed zigzag candle series with a known
higher-highs/higher-lows (bullish) or lower-highs/lower-lows (bearish)
shape.
"""

from __future__ import annotations

from app.strategy.bias import detect_htf_bias


def candle(high: float, low: float, ts: str) -> dict:
    mid = (high + low) / 2
    return {"open": mid, "high": high, "low": low, "close": mid, "timestamp": ts}


def test_detect_htf_bias_neutral_when_too_few_candles():
    candles = [candle(11, 9, f"t{i}") for i in range(9)]
    assert detect_htf_bias(candles) == "neutral"


def test_detect_htf_bias_bullish_on_higher_highs_higher_lows():
    # Zigzag with 3 rising peaks (20 -> 25 -> 30) and 2 rising troughs (5 -> 8).
    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    candles = [candle(h, l, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]

    assert detect_htf_bias(candles) == "bullish"


def test_detect_htf_bias_bearish_on_lower_highs_lower_lows():
    # Mirror of the bullish shape: 3 falling peaks (30 -> 25 -> 20) and
    # 2 falling troughs (6 -> 3).
    highs = [10, 11, 30, 11, 9, 11, 25, 11, 9, 11, 20, 11, 9]
    lows = [8, 9, 15, 9, 6, 9, 18, 9, 3, 9, 22, 11, 12]
    candles = [candle(h, l, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]

    assert detect_htf_bias(candles) == "bearish"


def test_detect_htf_bias_neutral_on_flat_series():
    candles = [candle(11, 9, f"t{i}") for i in range(15)]
    assert detect_htf_bias(candles) == "neutral"
