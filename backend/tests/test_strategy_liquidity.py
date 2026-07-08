"""Unit tests for app.strategy.liquidity: sweep-then-reverse detection on
the most recently closed candle, against hand-constructed candle series
with a known swing level that gets wicked through and then reclaimed.
"""

from __future__ import annotations

from app.strategy.liquidity import detect_liquidity_sweep


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def test_detect_liquidity_sweep_none_when_series_too_short():
    # detect_liquidity_sweep requires len(candles) >= 2n + 2; n defaults to 2 -> 6.
    candles = [candle(10, 11, 9, 10, f"t{i}") for i in range(5)]
    assert detect_liquidity_sweep(candles) is None


def test_detect_liquidity_sweep_buy_side_wick_above_then_close_below():
    """A prior swing high (15) gets wicked through (last high 16) but the
    last candle closes back below it (12 < 15) -> buy-side liquidity
    sweep.
    """
    candles = [
        candle(10, 12, 9, 10, "t0"),
        candle(10, 15, 9, 11, "t1"),  # swing high (15)
        candle(11, 11, 8, 9, "t2"),
        candle(9, 10, 8, 9, "t3"),
        candle(9, 16, 8, 12, "t4"),  # wicks above 15, closes back below at 12
    ]

    result = detect_liquidity_sweep(candles, n=1)

    assert result == {
        "type": "buy_side",
        "level": 15,
        "swept_index": 1,
        "sweep_index": 4,
    }


def test_detect_liquidity_sweep_sell_side_wick_below_then_close_above():
    """A prior swing low (5) gets wicked through (last low 3) but the
    last candle closes back above it (6 > 5) -> sell-side liquidity
    sweep. Highs are monotonic so no swing high exists to interfere.
    """
    candles = [
        candle(9, 10, 9, 9, "t0"),
        candle(9, 11, 5, 9, "t1"),  # swing low (5)
        candle(8, 12, 8, 9, "t2"),
        candle(8, 13, 8, 9, "t3"),
        candle(7, 14, 3, 6, "t4"),  # wicks below 5, closes back above at 6
    ]

    result = detect_liquidity_sweep(candles, n=1)

    assert result == {
        "type": "sell_side",
        "level": 5,
        "swept_index": 1,
        "sweep_index": 4,
    }


def test_detect_liquidity_sweep_none_on_flat_series():
    candles = [candle(9 + i * 0.1, 10, 9, 9.5, f"t{i}") for i in range(6)]
    assert detect_liquidity_sweep(candles, n=1) is None
