"""Unit tests for app.strategy.fvg: 3-candle imbalance (fair value gap)
detection, against hand-constructed candle triples with a known,
unambiguous gap (or overlap, for the no-gap case).
"""

from __future__ import annotations

from app.strategy.fvg import detect_fair_value_gap


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def test_detect_fair_value_gap_bullish_clear_gap():
    # candle[0].high (11) < candle[2].low (13) -> a bullish FVG zone
    # bounded by [11, 13], attributed to the middle (impulse) candle.
    candles = [
        candle(10, 11, 9, 10, "t0"),
        candle(10, 15, 10, 14, "t1"),
        candle(14, 16, 13, 15, "t2"),
    ]

    zones = detect_fair_value_gap(candles)

    assert zones == [{"type": "bullish", "top": 13, "bottom": 11, "index": 1}]


def test_detect_fair_value_gap_bearish_clear_gap():
    # candle[0].low (14) > candle[2].high (11) -> a bearish FVG zone
    # bounded by [11, 14].
    candles = [
        candle(15, 16, 14, 15, "t0"),
        candle(15, 15, 9, 10, "t1"),
        candle(10, 11, 9, 9.5, "t2"),
    ]

    zones = detect_fair_value_gap(candles)

    assert zones == [{"type": "bearish", "top": 14, "bottom": 11, "index": 1}]


def test_detect_fair_value_gap_none_on_overlapping_ranges():
    candles = [candle(10, 11, 9, 10, f"t{i}") for i in range(3)]
    assert detect_fair_value_gap(candles) == []


def test_detect_fair_value_gap_returns_all_zones_found():
    # Two independent impulsive legs back-to-back should each register
    # their own zone.
    candles = [
        candle(10, 11, 9, 10, "t0"),
        candle(10, 15, 10, 14, "t1"),  # bullish gap vs t0/t2
        candle(14, 16, 13, 15, "t2"),
        candle(15, 15, 9, 10, "t3"),  # bearish gap vs t2/t4
        candle(10, 11, 9, 9.5, "t4"),
    ]

    zones = detect_fair_value_gap(candles)

    assert zones == [
        {"type": "bullish", "top": 13, "bottom": 11, "index": 1},
        {"type": "bearish", "top": 13, "bottom": 11, "index": 3},
    ]
