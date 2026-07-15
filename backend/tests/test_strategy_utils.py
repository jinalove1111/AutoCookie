"""Unit tests for app.strategy.utils.is_zone_mitigated: the zone-
mitigation check added to fix duplicate signal generation on a zone price
has already retested (see test_strategy_signal_engine.py for the
end-to-end regression proof; these are direct, isolated proofs of the
boundary rule itself).
"""

from __future__ import annotations

from app.strategy.utils import average_true_range, is_zone_mitigated


def candle(high: float, low: float, ts: str) -> dict:
    return {"open": (high + low) / 2, "high": high, "low": low, "close": (high + low) / 2, "timestamp": ts}


def test_is_zone_mitigated_true_when_an_earlier_candle_overlaps():
    candles = [
        candle(10, 8, "t0"),  # zone-forming candle, irrelevant here
        candle(35, 25, "t1"),  # overlaps zone [20, 30] (range [25, 35])
        candle(50, 45, "t2"),  # "now" -- excluded from the check
    ]
    assert is_zone_mitigated(candles, start_index=1, top=30, bottom=20) is True


def test_is_zone_mitigated_false_when_no_earlier_candle_overlaps():
    candles = [
        candle(10, 8, "t0"),
        candle(15, 12, "t1"),  # nowhere near [20, 30]
        candle(50, 45, "t2"),
    ]
    assert is_zone_mitigated(candles, start_index=1, top=30, bottom=20) is False


def test_is_zone_mitigated_excludes_the_last_candle():
    """The LAST candle in the series is always "now" -- it touching the
    zone as part of triggering the signal (e.g. a sweep wick that taps
    straight into a nearby FVG in the same candle) is the setup itself,
    not a disqualifying prior retest.
    """
    candles = [
        candle(10, 8, "t0"),
        candle(15, 12, "t1"),  # doesn't overlap
        candle(28, 22, "t2"),  # overlaps [20, 30] -- but this IS the last candle
    ]
    assert is_zone_mitigated(candles, start_index=1, top=30, bottom=20) is False


def test_is_zone_mitigated_false_for_single_candle_list():
    assert is_zone_mitigated([candle(28, 22, "t0")], start_index=0, top=30, bottom=20) is False


def test_is_zone_mitigated_false_when_start_index_beyond_available_candles():
    candles = [candle(10, 8, "t0"), candle(50, 45, "t1")]
    assert is_zone_mitigated(candles, start_index=5, top=30, bottom=20) is False


def test_is_zone_mitigated_boundary_touch_counts_as_overlap():
    """A candle whose high exactly equals the zone's bottom (a wick that
    just grazes the edge) counts as an overlap -- the check is inclusive
    on both ends, not requiring the candle to fully cross into the zone.
    """
    candles = [
        candle(10, 8, "t0"),
        candle(20, 15, "t1"),  # high == zone bottom (20) exactly
        candle(50, 45, "t2"),
    ]
    assert is_zone_mitigated(candles, start_index=1, top=30, bottom=20) is True


def _ohlc(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def test_average_true_range_none_below_minimum_history():
    """Needs lookback + 1 candles (each True Range needs a previous
    close) -- returns None rather than a misleading partial average."""
    candles = [_ohlc(100, 105, 95, 100, f"t{i}") for i in range(5)]
    assert average_true_range(candles, lookback=14) is None


def test_average_true_range_simple_no_gaps():
    """With no gaps between candles (close == next open, ranges don't
    exceed the prior close), True Range reduces to plain high-low, so ATR
    is just the average high-low range -- a simple, independently
    verifiable case."""
    candles = [
        _ohlc(100, 102, 98, 100, "t0"),
        _ohlc(100, 104, 96, 100, "t1"),  # range 8
        _ohlc(100, 103, 97, 100, "t2"),  # range 6
    ]
    # lookback=2 -> uses t1, t2 (each needs its own prior close, both 100,
    # no gap) -> true ranges [8, 6] -> ATR = 7.0
    assert average_true_range(candles, lookback=2) == 7.0


def test_average_true_range_captures_gap_up():
    """A gap up (low of the new candle above the previous close) must
    still be captured by True Range even though high-low alone would
    understate the real range."""
    candles = [
        _ohlc(100, 101, 99, 100, "t0"),
        _ohlc(120, 122, 119, 121, "t1"),  # gapped up from close=100; high-low=3, but |high-prev_close|=22
    ]
    assert average_true_range(candles, lookback=1) == 22.0
