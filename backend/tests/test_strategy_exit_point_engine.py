"""Unit tests for app.strategy.exit_point_engine: Jade take-profit target
selection. Real detector calls throughout (nothing mocked), same
discipline as entry_point_engine's own tests.
"""

from __future__ import annotations

import pytest

from app.strategy.exit_point_engine import find_exit_targets


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def _flat_candles(n: int = 20) -> list[dict]:
    return [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(n)]


def test_find_exit_targets_invalid_direction_raises():
    with pytest.raises(ValueError):
        find_exit_targets(_flat_candles(), "up", entry_price=100)


def test_find_exit_targets_empty_when_no_candidates():
    # Gently rising, heavily overlapping ranges: no swing highs/lows ever
    # confirm (strictly increasing), so none of the 4 target sources find
    # anything -- see the identical pattern/rationale in
    # test_strategy_entry_point_engine.py's "nothing matches" fixture.
    candles = [
        candle(100 + i * 0.1, 100 + i * 0.1 + 1, 100 + i * 0.1 - 1, 100 + i * 0.1 + 0.5, f"t{i}")
        for i in range(20)
    ]
    result = find_exit_targets(candles, "long", entry_price=100)
    assert result["targets"] == []
    assert result["direction"] == "long"
    assert result["entry_price"] == 100


def _multi_target_long_candles() -> list[dict]:
    """3 confirmed swing highs: two near-equal ones at ~15 (indices 2, 7
    -- a real equal-highs pool via detect_equal_highs), then a larger,
    more recent one at 25 (index 11, also the current premium/discount
    range top and previous swing high). Equilibrium computes to 16.5,
    sitting between the equal-highs pool and the range extreme --
    3 genuinely distinct target levels for ranking.
    """
    highs = [10, 10, 15.00, 10, 10, 10, 10, 15.01, 10, 10, 10, 25, 10, 9]
    lows = [8, 8, 8, 8, 5, 8, 8, 8, 8, 8, 8, 8, 9, 9]
    return [candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]


def test_find_exit_targets_long_ranks_nearest_to_farthest():
    candles = _multi_target_long_candles()

    result = find_exit_targets(candles, "long", entry_price=6)
    targets = result["targets"]

    assert [t["source"] for t in targets] == [
        "equal_highs", "equilibrium", "previous_swing_high", "range_extreme",
    ]
    assert [t["label"] for t in targets] == ["TP1", "TP2", "TP3", "TP4"]
    # strictly ascending raw levels (nearest to farthest for a long).
    raw_levels = [t["raw_level"] for t in targets]
    assert raw_levels == sorted(raw_levels)
    assert raw_levels[0] == 15.01  # equal highs pool
    assert raw_levels[1] == 16.5   # equilibrium
    assert raw_levels[2] == raw_levels[3] == 25  # previous swing high == range extreme


def test_find_exit_targets_buffer_applied_inward_for_long():
    """Every target's buffered `level` must sit strictly short of its
    `raw_level` for a long (never past it) -- standard ICT practice of
    not requiring price to fully reach the raw liquidity level.
    """
    candles = _multi_target_long_candles()
    result = find_exit_targets(candles, "long", entry_price=6)

    for target in result["targets"]:
        assert target["level"] < target["raw_level"]


def test_find_exit_targets_excludes_targets_behind_entry_price():
    """With entry_price ABOVE the equal-highs pool (15.01) but still
    below the range top, that pool must no longer appear as a target --
    it's already behind price, not a usable forward target.
    """
    candles = _multi_target_long_candles()
    result = find_exit_targets(candles, "long", entry_price=20)

    sources = [t["source"] for t in result["targets"]]
    assert "equal_highs" not in sources
    assert "equilibrium" not in sources  # equilibrium (16.5) also behind entry
    assert "previous_swing_high" in sources


def _multi_target_short_candles() -> list[dict]:
    """Structural mirror of `_multi_target_long_candles` (transform
    `mirrored = 40 - original`, roles of highs/lows swapped) -- an
    equal-lows pool (~25), a lower equilibrium (23.5), and a further,
    more recent previous swing low / range bottom (15), all verified
    directly via the real detectors above.
    """
    orig_highs = [10, 10, 15.00, 10, 10, 10, 10, 15.01, 10, 10, 10, 25, 10, 9]
    orig_lows = [8, 8, 8, 8, 5, 8, 8, 8, 8, 8, 8, 8, 9, 9]
    lows = [40 - h for h in orig_highs]
    highs = [40 - l for l in orig_lows]
    return [candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]


def test_find_exit_targets_short_ranks_nearest_to_farthest():
    candles = _multi_target_short_candles()

    result = find_exit_targets(candles, "short", entry_price=34)
    targets = result["targets"]

    assert [t["source"] for t in targets] == [
        "equal_lows", "equilibrium", "previous_swing_low", "range_extreme",
    ]
    assert [t["label"] for t in targets] == ["TP1", "TP2", "TP3", "TP4"]
    raw_levels = [t["raw_level"] for t in targets]
    assert raw_levels == sorted(raw_levels, reverse=True)
    assert raw_levels[2] == raw_levels[3] == 15


def test_find_exit_targets_buffer_applied_inward_for_short():
    candles = _multi_target_short_candles()
    result = find_exit_targets(candles, "short", entry_price=34)

    for target in result["targets"]:
        assert target["level"] > target["raw_level"]
