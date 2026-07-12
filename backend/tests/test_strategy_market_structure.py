"""Unit tests for app.strategy.market_structure: swing highs/lows and
CHOCH/MSS detection, against small hand-constructed candle series where
the expected outcome is unambiguous (verified by directly inspecting the
real detector's output on intentionally-shaped data, not invented
behavior).
"""

from __future__ import annotations

from app.strategy.market_structure import (
    detect_choch_mss,
    find_previous_swing_high,
    find_previous_swing_low,
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


def test_find_previous_swing_high_returns_most_recent_confirmed_high():
    # Two peaks: index 2 (20) and index 6 (15) -- "previous" must be the
    # LATTER one (most recently confirmed), not the first swing high found.
    highs = [10, 11, 20, 11, 10, 11, 15, 11, 10]
    candles = [candle(h, h, h - 1, h, f"t{i}") for i, h in enumerate(highs)]

    assert find_previous_swing_high(candles, n=2) == {"price": 15, "index": 6}


def test_find_previous_swing_low_returns_most_recent_confirmed_low():
    lows = [10, 9, 1, 9, 10, 9, 5, 9, 10]
    candles = [candle(l + 1, l + 1, l, l, f"t{i}") for i, l in enumerate(lows)]

    assert find_previous_swing_low(candles, n=2) == {"price": 5, "index": 6}


def test_find_previous_swing_high_none_on_strictly_monotonic_series():
    candles = [candle(10 + i, 10 + i, 9 + i, 10 + i, f"t{i}") for i in range(6)]
    assert find_previous_swing_high(candles, n=2) is None


def test_find_previous_swing_low_none_on_strictly_monotonic_series():
    candles = [candle(10 + i, 10 + i, 9 + i, 10 + i, f"t{i}") for i in range(6)]
    assert find_previous_swing_low(candles, n=2) is None


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


# --- Regression tests: `swept_index` gating (new causal link to the
# specific liquidity sweep that preceded the CHOCH, per
# docs/strategy_spec.md section 3) ---


def test_detect_choch_mss_swept_index_none_is_unchanged_from_before():
    """`swept_index=None` (the default) must behave byte-for-byte like
    calling without the parameter at all -- this is the exact fixture from
    `test_detect_choch_mss_bullish_choch_on_downtrend_break` above, just
    asserted again with the parameter passed explicitly as None.
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

    assert detect_choch_mss(candles, n=1, swept_index=None) == {
        "type": "bullish_choch",
        "broken_level": 13,
        "broken_index": 3,
        "confirm_index": 6,
    }


def test_detect_choch_mss_excludes_earlier_unrelated_swing_break_before_swept_index():
    """Same downtrend fixture as
    `test_detect_choch_mss_bullish_choch_on_downtrend_break`: WITHOUT the
    `swept_index` constraint, the function reports a bullish CHOCH whose
    broken level is the swing high at index 3 (value 13) -- the only
    swing high available, formed well before any sweep. If the liquidity
    sweep that actually preceded this reversal happened later (e.g. at
    index 4, a swept swing low), that index-3 swing high is an earlier,
    unrelated structural point relative to the real sweep -- referencing
    it would be exactly the correctness gap described in
    docs/strategy_spec.md section 3.

    Passing `swept_index=4` (a point strictly after the index-3 break)
    must exclude that swing high from consideration. With no other swing
    high at or after index 4 in this short series, the function correctly
    returns None instead of the stale, sweep-unrelated CHOCH it would
    have returned unconstrained.
    """
    candles = [
        candle(10, 12, 9, 10, "t0"),
        candle(10, 15, 9, 11, "t1"),  # swing high (15)
        candle(11, 11, 8, 9, "t2"),
        candle(9, 13, 8, 9, "t3"),  # swing high (13) -- the "earlier, unrelated" break
        candle(9, 10, 5, 6, "t4"),  # swing low (5)
        candle(6, 9, 4, 8, "t5"),  # swing low (4)
        candle(8, 9, 6, 16, "t6"),  # close (16) breaks back above 13
    ]

    # Without the constraint: detected, using the index-3 swing high.
    unconstrained = detect_choch_mss(candles, n=1)
    assert unconstrained is not None
    assert unconstrained["broken_index"] == 3

    # With swept_index pointing after that early break: correctly excluded.
    assert detect_choch_mss(candles, n=1, swept_index=4) is None
