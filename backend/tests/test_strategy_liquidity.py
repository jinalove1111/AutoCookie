"""Unit tests for app.strategy.liquidity: sweep-then-reverse detection on
the most recently closed candle, against hand-constructed candle series
with a known swing level that gets wicked through and then reclaimed.
"""

from __future__ import annotations

from app.strategy.liquidity import detect_equal_highs, detect_equal_lows, detect_liquidity_sweep


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


# --- detect_equal_highs / detect_equal_lows (docs/ROADMAP.md "Core Rule MVP
# completion" item #5) -----------------------------------------------------


def test_detect_equal_highs_none_when_no_swing_highs():
    candles = [candle(9, 10 + i, 9, 9.5, f"t{i}") for i in range(6)]  # strictly rising highs
    assert detect_equal_highs(candles, n=1) == []


def test_detect_equal_highs_detects_pair_within_default_tolerance():
    """Two confirmed swing highs (15.00, 15.01) 0.067% apart -- within the
    default 0.1% tolerance -- must be reported as one equal-highs zone,
    `level` set to the HIGHER of the two.
    """
    candles = [
        candle(9, 10, 9, 9.5, "t0"),
        candle(9, 15.00, 9, 9.5, "t1"),  # swing high #1
        candle(9, 10, 9, 9.5, "t2"),
        candle(9, 10, 9, 9.5, "t3"),
        candle(9, 15.01, 9, 9.5, "t4"),  # swing high #2, within tolerance of #1
        candle(9, 10, 9, 9.5, "t5"),
    ]

    result = detect_equal_highs(candles, n=1)

    assert result == [
        {"type": "equal_highs", "level": 15.01, "first_index": 1, "second_index": 4}
    ]


def test_detect_equal_highs_ignores_pair_outside_tolerance():
    """Two confirmed swing highs (15.00, 15.20) 1.33% apart -- outside the
    default 0.1% tolerance -- must NOT be reported.
    """
    candles = [
        candle(9, 10, 9, 9.5, "t0"),
        candle(9, 15.00, 9, 9.5, "t1"),
        candle(9, 10, 9, 9.5, "t2"),
        candle(9, 10, 9, 9.5, "t3"),
        candle(9, 15.20, 9, 9.5, "t4"),
        candle(9, 10, 9, 9.5, "t5"),
    ]

    assert detect_equal_highs(candles, n=1) == []


def test_detect_equal_highs_only_compares_adjacent_swing_highs():
    """Three confirmed swing highs: 15.00, 30.00, 15.01 -- the first and
    third are within tolerance of EACH OTHER, but a genuinely different
    swing high (30.00) sits between them. Only ADJACENT pairs in the
    swing-high sequence are compared ((15.00, 30.00) and (30.00, 15.01),
    both far outside tolerance), so this must report nothing -- proving
    non-adjacent swing highs are never cross-checked.
    """
    candles = [
        candle(9, 10, 9, 9.5, "t0"),
        candle(9, 15.00, 9, 9.5, "t1"),
        candle(9, 10, 9, 9.5, "t2"),
        candle(9, 30.00, 9, 9.5, "t3"),
        candle(9, 10, 9, 9.5, "t4"),
        candle(9, 15.01, 9, 9.5, "t5"),
        candle(9, 10, 9, 9.5, "t6"),
    ]

    assert detect_equal_highs(candles, n=1) == []


def test_detect_equal_highs_custom_tolerance_parameter():
    """The same 0.067%-apart pair accepted under the default 0.1%
    tolerance (see test_detect_equal_highs_detects_pair_within_default_
    tolerance) must be rejected under a tighter, explicitly-passed
    tolerance (0.01%).
    """
    candles = [
        candle(9, 10, 9, 9.5, "t0"),
        candle(9, 15.00, 9, 9.5, "t1"),
        candle(9, 10, 9, 9.5, "t2"),
        candle(9, 10, 9, 9.5, "t3"),
        candle(9, 15.01, 9, 9.5, "t4"),
        candle(9, 10, 9, 9.5, "t5"),
    ]

    assert detect_equal_highs(candles, n=1, tolerance=0.0001) == []


def test_detect_equal_lows_none_when_no_swing_lows():
    candles = [candle(9, 10, 9 - i, 9.5, f"t{i}") for i in range(6)]  # strictly falling lows
    assert detect_equal_lows(candles, n=1) == []


def test_detect_equal_lows_detects_pair_within_default_tolerance():
    """Mirror of the equal-highs case: two confirmed swing lows (5.00,
    5.003) within tolerance must be reported, `level` set to the LOWER of
    the two.
    """
    candles = [
        candle(9, 10, 9, 9.5, "t0"),
        candle(9, 10, 5.00, 9.5, "t1"),  # swing low #1
        candle(9, 10, 9, 9.5, "t2"),
        candle(9, 10, 9, 9.5, "t3"),
        candle(9, 10, 5.003, 9.5, "t4"),  # swing low #2, within tolerance of #1
        candle(9, 10, 9, 9.5, "t5"),
    ]

    result = detect_equal_lows(candles, n=1)

    assert result == [
        {"type": "equal_lows", "level": 5.00, "first_index": 1, "second_index": 4}
    ]


def test_detect_equal_lows_ignores_pair_outside_tolerance():
    candles = [
        candle(9, 10, 9, 9.5, "t0"),
        candle(9, 10, 5.00, 9.5, "t1"),
        candle(9, 10, 9, 9.5, "t2"),
        candle(9, 10, 9, 9.5, "t3"),
        candle(9, 10, 4.80, 9.5, "t4"),
        candle(9, 10, 9, 9.5, "t5"),
    ]

    assert detect_equal_lows(candles, n=1) == []
