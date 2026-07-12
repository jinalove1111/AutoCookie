"""Unit tests for app.strategy.crt: Candle Range Theory manipulation +
distribution detection.
"""

from __future__ import annotations

from app.strategy.crt import detect_crt, detect_crt_from_previous_candle


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def test_detect_crt_none_on_empty_candles():
    assert detect_crt(candle(100, 110, 100, 105, "range"), []) is None


def test_detect_crt_bullish_wick_below_close_back_above():
    range_candle = candle(105, 110, 100, 108, "range")
    candles = [candle(99, 100, 95, 101, "t0")]  # wicks below 100, closes back above

    result = detect_crt(range_candle, candles)

    assert result == {
        "type": "bullish_crt",
        "range_high": 110,
        "range_low": 100,
        "target_reference": 110,
    }


def test_detect_crt_bearish_wick_above_close_back_below():
    range_candle = candle(105, 110, 100, 102, "range")
    candles = [candle(111, 115, 108, 109, "t0")]  # wicks above 110, closes back below

    result = detect_crt(range_candle, candles)

    assert result == {
        "type": "bearish_crt",
        "range_high": 110,
        "range_low": 100,
        "target_reference": 100,
    }


def test_detect_crt_none_on_sweep_without_close_back_inside():
    """A manipulation wick with NO distribution back inside the range --
    same "sweep alone is never a signal" discipline as Liquidity Raid --
    must not produce a result.
    """
    range_candle = candle(105, 110, 100, 108, "range")
    candles = [candle(99, 100, 95, 96, "t0")]  # wicks below 100, closes even LOWER (no reclaim)

    assert detect_crt(range_candle, candles) is None


def test_detect_crt_none_when_price_stays_inside_the_range():
    range_candle = candle(105, 110, 100, 108, "range")
    candles = [candle(103, 107, 102, 105, "t0")]  # comfortably inside [100, 110]

    assert detect_crt(range_candle, candles) is None


def test_detect_crt_supports_cross_timeframe_usage():
    """`range_candle` and `candles` can come from genuinely different
    series -- a real HTF candle as the range, an LTF series as the
    manipulation/distribution check -- proving the two are independent
    inputs, not required to share a source.
    """
    htf_range_candle = candle(4000, 4100, 3900, 4050, "htf_daily")
    ltf_candles = [
        candle(3950, 3960, 3880, 3980, "ltf_t0"),  # sweeps below 3900, closes back above
    ]

    result = detect_crt(htf_range_candle, ltf_candles)

    assert result["type"] == "bullish_crt"
    assert result["range_low"] == 3900


def test_detect_crt_from_previous_candle_none_with_fewer_than_two_candles():
    assert detect_crt_from_previous_candle([candle(100, 110, 100, 105, "t0")]) is None
    assert detect_crt_from_previous_candle([]) is None


def test_detect_crt_from_previous_candle_uses_second_to_last_as_the_range():
    candles = [
        candle(105, 110, 100, 108, "t0"),  # the range candle
        candle(99, 100, 95, 101, "t1"),    # wicks below 100, closes back above
    ]

    result = detect_crt_from_previous_candle(candles)

    assert result == detect_crt(candles[0], candles)
    assert result["type"] == "bullish_crt"
