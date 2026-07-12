"""Unit tests for app.strategy.premium_discount: current swing range and
premium/discount/equilibrium classification, against hand-constructed
zigzag candle series with a known range (verified against the actual
find_swing_highs/find_swing_lows output, not hand-derived) and a known
latest close.
"""

from __future__ import annotations

from app.strategy.premium_discount import calculate_premium_discount


def candle(high: float, low: float, close: float | None = None, ts: str = "t") -> dict:
    if close is None:
        close = (high + low) / 2
    return {"open": close, "high": high, "low": low, "close": close, "timestamp": ts}


def _range_candles(last_close: float) -> list[dict]:
    # Verified shape (via find_swing_highs/find_swing_lows directly):
    # swing highs = [2, 10] -> top = 30 (idx10); swing lows = [4] ->
    # bottom = 5 (idx4). Range [5, 30], equilibrium = 17.5.
    highs = [10, 11, 20, 15, 12, 14, 18, 20, 25, 27, 30, 20, 18, 16]
    lows = [8, 9, 15, 11, 5, 9, 14, 16, 20, 22, 22, 15, 13, 12]
    candles = [candle(h, l, ts=f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]
    candles[-1] = candle(highs[-1], lows[-1], close=last_close, ts="t_last")
    return candles


def test_calculate_premium_discount_none_when_no_swings():
    # Fewer than 2n+1 candles: find_swing_highs/find_swing_lows's
    # range(n, len(candles) - n) is empty, so neither can find anything.
    candles = [candle(11, 9) for _ in range(4)]
    assert calculate_premium_discount(candles) is None


def test_calculate_premium_discount_returns_discount_below_equilibrium():
    # Verified range: swing highs [2, 10] -> top=30 (idx10); swing lows
    # [4] -> bottom=5 (idx4). equilibrium = (30 + 5) / 2 = 17.5.
    candles = _range_candles(last_close=10.0)
    result = calculate_premium_discount(candles)

    assert result is not None
    assert result["top"] == 30
    assert result["bottom"] == 5
    assert result["equilibrium"] == 17.5
    assert result["zone"] == "discount"


def test_calculate_premium_discount_returns_premium_above_equilibrium():
    candles = _range_candles(last_close=25.0)
    result = calculate_premium_discount(candles)

    assert result is not None
    assert result["zone"] == "premium"


def test_calculate_premium_discount_returns_equilibrium_at_exact_midpoint():
    candles = _range_candles(last_close=17.5)
    result = calculate_premium_discount(candles)

    assert result is not None
    assert result["zone"] == "equilibrium"


def test_calculate_premium_discount_none_when_range_degenerate():
    # Verified shape: the only swing high (idx2, value 12) is smaller than
    # the most recent swing low (idx9, value 48) -- high[] is strictly
    # increasing after the early hump so no later swing high ever forms,
    # while low[] dips to a genuine local minimum (48) well after the
    # early hump. top (12) <= bottom (48): no coherent current range.
    highs = [10, 11, 12, 11, 9, 100, 105, 110, 115, 120, 125, 130, 135, 140, 145]
    lows = [8, 9, 10, 9, 7, 60, 90, 110, 70, 48, 90, 110, 130, 132, 134]
    candles = [candle(h, l, ts=f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]

    assert calculate_premium_discount(candles) is None
