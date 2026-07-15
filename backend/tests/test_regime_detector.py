"""Tests for app.regime.regime_detector: the Market Regime Detector
(operator directive, 2026-07-15, docs/ADAPTIVE_ARCHITECTURE.md section 2).
"""

from __future__ import annotations

from app.regime.regime_detector import (
    MarketRegime,
    average_directional_index,
    detect_market_regime,
    distance_from_ma,
    equal_level_sweep_count,
    is_breakout,
    is_mean_reversion,
    liquidity_sweep_count,
    realized_volatility,
    simple_moving_average,
    swing_trend_direction,
    volatility_percentile,
    vwap,
)


def candle(open_: float, high: float, low: float, close: float, volume: float = 100.0, ts: str = "t0") -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume, "timestamp": ts}


def _flat_candles(n: int, price: float = 100.0, volume: float = 100.0) -> list[dict]:
    return [candle(price, price + 1, price - 1, price, volume, f"t{i}") for i in range(n)]


def _uptrend_candles(n: int, start: float = 100.0, step: float = 1.0, volume: float = 100.0) -> list[dict]:
    candles = []
    price = start
    for i in range(n):
        candles.append(candle(price, price + step + 0.5, price - 0.5, price + step, volume, f"t{i}"))
        price += step
    return candles


# --- simple_moving_average / distance_from_ma ------------------------------


def test_simple_moving_average_none_below_lookback():
    assert simple_moving_average(_flat_candles(5), lookback=20) is None


def test_simple_moving_average_exact_value():
    candles = [candle(100, 101, 99, 100 + i, ts=f"t{i}") for i in range(5)]  # closes: 100,101,102,103,104
    assert simple_moving_average(candles, lookback=5) == 102.0


def test_distance_from_ma_signed():
    candles = [candle(100, 101, 99, 100, ts=f"t{i}") for i in range(4)]
    candles.append(candle(110, 111, 109, 110, ts="t4"))  # close jumps well above the flat MA
    dist = distance_from_ma(candles, lookback=5)
    assert dist is not None
    assert dist > 0


# --- vwap --------------------------------------------------------------


def test_vwap_none_below_lookback():
    assert vwap(_flat_candles(3), lookback=20) is None


def test_vwap_weights_toward_higher_volume_candle():
    low_vol = candle(100, 101, 99, 100, volume=1.0, ts="t0")
    high_vol = candle(200, 201, 199, 200, volume=1000.0, ts="t1")
    result = vwap([low_vol, high_vol], lookback=2)
    assert result is not None
    assert result > 150  # much closer to the high-volume candle's price than the midpoint


# --- realized_volatility -------------------------------------------------


def test_realized_volatility_zero_for_flat_prices():
    assert realized_volatility(_flat_candles(25), lookback=20) == 0.0


def test_realized_volatility_positive_for_varying_prices():
    candles = [candle(100, 101, 99, 100 + (5 if i % 2 == 0 else -5), ts=f"t{i}") for i in range(25)]
    vol = realized_volatility(candles, lookback=20)
    assert vol is not None
    assert vol > 0


# --- swing_trend_direction -------------------------------------------------


def test_swing_trend_direction_up_for_ascending_swings():
    # Same real, verified-ascending zigzag shape as
    # test_strategy_signal_engine.py's bullish fixture (13 candles --
    # find_swing_highs/find_swing_lows need n=2 confirmation candles on
    # each side, so a short zigzag can't produce 2 confirmed swings of
    # each type).
    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    candles = [candle((h + l) / 2, h, l, (h + l) / 2, ts=f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]
    assert swing_trend_direction(candles) == "up"


def test_swing_trend_direction_none_with_insufficient_swings():
    assert swing_trend_direction(_flat_candles(3)) is None


# --- is_breakout ---------------------------------------------------------


def test_is_breakout_true_on_volume_confirmed_channel_break():
    prior = _flat_candles(20, price=100.0, volume=100.0)
    breakout_candle = candle(100, 130, 99, 125, volume=500.0, ts="t20")  # well above the flat channel, volume spike
    assert is_breakout(prior + [breakout_candle], channel_lookback=20, volume_lookback=20) is True


def test_is_breakout_false_without_volume_confirmation():
    prior = _flat_candles(20, price=100.0, volume=100.0)
    breakout_candle = candle(100, 130, 99, 125, volume=50.0, ts="t20")  # breaks the channel but volume is BELOW average
    assert is_breakout(prior + [breakout_candle], channel_lookback=20, volume_lookback=20) is False


def test_is_breakout_false_when_price_stays_inside_channel():
    prior = _flat_candles(20, price=100.0, volume=100.0)
    inside_candle = candle(100, 100.5, 99.5, 100, volume=500.0, ts="t20")
    assert is_breakout(prior + [inside_candle], channel_lookback=20, volume_lookback=20) is False


# --- liquidity_sweep_count / equal_level_sweep_count ------------------------


def test_liquidity_sweep_count_zero_below_minimum_history():
    assert liquidity_sweep_count(_flat_candles(5), lookback=20) == 0


def test_equal_level_sweep_count_zero_for_a_clean_monotonic_uptrend():
    """A flat, perfectly repeated series is NOT a valid "no equal levels"
    fixture -- every identical swing high trivially matches every other
    within tolerance, which is correct `detect_equal_highs` behavior, not
    a bug. A strictly monotonic uptrend (every swing progressively
    higher, no repeats) is the real "no equal levels" case."""
    assert equal_level_sweep_count(_uptrend_candles(30, step=5.0), lookback=20) == 0


# --- average_directional_index --------------------------------------------


def test_adx_none_below_minimum_history():
    assert average_directional_index(_flat_candles(10), lookback=14) is None


def test_adx_higher_for_a_strong_uptrend_than_flat_chop():
    trending = _uptrend_candles(40, step=2.0)
    flat = _flat_candles(40)
    adx_trend = average_directional_index(trending, lookback=14)
    adx_flat = average_directional_index(flat, lookback=14)
    assert adx_trend is not None
    assert adx_flat is not None
    assert adx_trend > adx_flat


# --- is_mean_reversion ------------------------------------------------------


def test_is_mean_reversion_false_below_minimum_history():
    assert is_mean_reversion(_flat_candles(10), ma_lookback=20) is False


# --- detect_market_regime (integration) -------------------------------------


def test_detect_market_regime_none_below_minimum_history():
    assert detect_market_regime(_flat_candles(10)) is None


def test_detect_market_regime_classifies_a_clear_uptrend_as_not_range():
    candles = _uptrend_candles(150, step=2.0)
    regime = detect_market_regime(candles)
    assert regime is not None
    assert isinstance(regime, MarketRegime)
    assert regime.trend != "range"
    assert "adx" in regime.metrics
    assert "volatility_percentile" in regime.metrics


def test_detect_market_regime_metrics_are_always_populated():
    candles = _uptrend_candles(150, step=1.0)
    regime = detect_market_regime(candles)
    assert regime is not None
    for key in ("adx", "atr", "volatility_percentile", "swing_trend_direction", "distance_from_ma", "vwap"):
        assert key in regime.metrics
