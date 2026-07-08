"""Integration test for app.strategy.signal_engine.SignalEngine: ties
bias/liquidity/structure/FVG/order-block detectors together into a real
TradeSignal, using an actual (uncensored) call through every real
sub-detector -- nothing here is mocked.
"""

from __future__ import annotations

from app.strategy.signal_engine import SignalEngine, TradeSignal


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def _bullish_confluence_candles() -> list[dict]:
    """A zigzag series with higher-highs/higher-lows (bullish HTF bias,
    verified in test_strategy_bias.py) plus a final candle that wicks
    below a recent swing low and closes back above it (a real sell-side
    liquidity sweep, the kind of reversal signal that pairs with a
    bullish bias), and several bullish FVGs formed along the way by the
    zigzag's impulsive legs.
    """
    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    candles = [candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]
    # wicks below the swing low at index 8 (value 8) but closes back above it.
    candles.append(candle(9, 10, 6, 9.5, "t13"))
    return candles


def test_signal_engine_generates_long_signal_on_real_confluence():
    engine = SignalEngine()
    signal = engine.generate_signal("BTCUSDT", _bullish_confluence_candles())

    assert isinstance(signal, TradeSignal)
    assert signal.symbol == "BTCUSDT"
    assert signal.direction == "long"
    assert signal.htf_bias == "bullish"
    assert signal.sweep_type == "sell_side"
    assert signal.rr == 2.0
    assert signal.status == "pending"
    assert signal.stop_loss < signal.entry_price < signal.take_profit
    assert signal.fvg_zone is not None


def test_signal_engine_returns_none_on_empty_candles():
    assert SignalEngine().generate_signal("BTCUSDT", []) is None


def test_signal_engine_returns_none_when_no_confluence():
    # A flat, featureless series: no bias, no sweep/choch, no zones.
    candles = [candle(10, 11, 9, 10, f"t{i}") for i in range(20)]
    assert SignalEngine().generate_signal("BTCUSDT", candles) is None
