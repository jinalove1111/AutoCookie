"""Tests for app.strategy.trend_following: the Trend Following Strategy
module (adaptive platform Milestone 9, 2026-07-16 -- see that module's
own docstring for the "disclosed, not tuned" status of every threshold).

Fixtures are entirely synthetic and deterministic (plain arithmetic
sequences -- uptrend/downtrend run, pullback/bounce, resumption bar), no
randomness, so every assertion here is stable across runs.
"""

from __future__ import annotations

from app.strategy.strategy_interface import Strategy
from app.strategy.trend_following import TrendFollowingStrategy


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def _flat_candles(n: int, price: float = 100.0) -> list[dict]:
    return [candle(price, price + 1, price - 1, price, f"t{i}") for i in range(n)]


def _htf_uptrend_candles() -> list[dict]:
    """Same real, verified-ascending zigzag fixture used elsewhere in this
    project (test_strategy_signal_engine.py / test_regime_detector.py /
    test_strategy_interface.py's `_bullish_confluence_candles`) --
    duplicated here rather than importing across test modules, same
    precedent as test_strategy_interface.py's own copy
    (ENGINEERING_DECISIONS.md #27). Verified (regime_detector.swing_trend_direction)
    to produce "up".
    """
    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    return [
        candle((h + l) / 2, h, l, (h + l) / 2, f"h{i}")
        for i, (h, l) in enumerate(zip(highs, lows))
    ]


def _htf_downtrend_candles() -> list[dict]:
    """Vertical mirror of `_htf_uptrend_candles` (reflects each high/low
    pair through a constant), turning the verified ascending zigzag into
    a verified descending one -- same shape, same swing-confirmation
    behavior, opposite direction. Verified to produce "down"."""
    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    mirror = 40
    new_highs = [mirror - l for l in lows]
    new_lows = [mirror - h for h in highs]
    return [
        candle((h + l) / 2, h, l, (h + l) / 2, f"h{i}")
        for i, (h, l) in enumerate(zip(new_highs, new_lows))
    ]


def _ltf_uptrend_pullback_candles() -> list[dict]:
    """30 LTF candles: a 20-bar steady uptrend (strong, consistent
    directional movement -> high ADX), a 9-bar shallow pullback that
    brings price back within 0.5*ATR of the resulting SMA(20), and a
    final bullish (close > open) resumption bar that closes back above
    both the SMA and the pullback low -- exactly the pullback-resumption
    trigger `trend_following._pullback_touched_ma` looks for. Verified
    directly against `TrendFollowingStrategy` (not hand-computed) to
    produce a `direction="long"` signal with `rr == 2.5`.
    """
    ltf: list[dict] = []
    price = 100.0
    for i in range(20):
        open_, close = price, price + 2.0
        ltf.append(candle(open_, max(open_, close) + 0.3, min(open_, close) - 0.3, close, f"t{i}"))
        price = close
    for i in range(9):
        open_, close = price, price - 1.0
        ltf.append(candle(open_, max(open_, close) + 0.3, min(open_, close) - 0.3, close, f"t{20 + i}"))
        price = close
    open_, close = price, price + 2.0
    ltf.append(candle(open_, max(open_, close) + 0.3, min(open_, close) - 0.3, close, "t29"))
    return ltf


def _ltf_downtrend_bounce_candles() -> list[dict]:
    """Mirror-image of `_ltf_uptrend_pullback_candles`: a 20-bar steady
    downtrend, a 9-bar shallow bounce back toward the SMA(20), and a
    final bearish (close < open) resumption bar. Verified directly
    against `TrendFollowingStrategy` to produce a `direction="short"`
    signal with `rr == 2.5`.
    """
    ltf: list[dict] = []
    price = 200.0
    for i in range(20):
        open_, close = price, price - 2.0
        ltf.append(candle(open_, max(open_, close) + 0.3, min(open_, close) - 0.3, close, f"t{i}"))
        price = close
    for i in range(9):
        open_, close = price, price + 1.0
        ltf.append(candle(open_, max(open_, close) + 0.3, min(open_, close) - 0.3, close, f"t{20 + i}"))
        price = close
    open_, close = price, price - 2.0
    ltf.append(candle(open_, max(open_, close) + 0.3, min(open_, close) - 0.3, close, "t29"))
    return ltf


def test_long_signal_in_clean_uptrend_pullback():
    strategy = TrendFollowingStrategy()
    signal = strategy.generate_signal(
        "BTCUSDT", _ltf_uptrend_pullback_candles(), _htf_uptrend_candles()
    )

    assert signal is not None
    assert signal.symbol == "BTCUSDT"
    assert signal.direction == "long"
    assert signal.htf_bias == "bullish"
    assert signal.status == "pending"
    assert signal.stop_loss < signal.entry_price
    assert signal.take_profit > signal.entry_price
    assert signal.rr == 2.5
    assert signal.sweep_type is None
    assert signal.choch_detected is False
    assert signal.fvg_zone is None


def test_short_signal_in_clean_downtrend_bounce():
    strategy = TrendFollowingStrategy()
    signal = strategy.generate_signal(
        "BTCUSDT", _ltf_downtrend_bounce_candles(), _htf_downtrend_candles()
    )

    assert signal is not None
    assert signal.direction == "short"
    assert signal.htf_bias == "bearish"
    assert signal.status == "pending"
    assert signal.stop_loss > signal.entry_price
    assert signal.take_profit < signal.entry_price
    assert signal.rr == 2.5


def test_no_signal_when_adx_filter_fails_on_flat_data():
    strategy = TrendFollowingStrategy()
    signal = strategy.generate_signal("BTCUSDT", _flat_candles(35), _flat_candles(20))
    assert signal is None


def test_no_signal_on_insufficient_history():
    strategy = TrendFollowingStrategy()
    signal = strategy.generate_signal("BTCUSDT", _flat_candles(5), _flat_candles(5))
    assert signal is None


def test_no_signal_on_empty_candles():
    strategy = TrendFollowingStrategy()
    assert strategy.generate_signal("BTCUSDT", [], []) is None
    assert strategy.generate_signal("BTCUSDT", _ltf_uptrend_pullback_candles(), []) is None


def test_trend_following_strategy_satisfies_the_protocol():
    assert isinstance(TrendFollowingStrategy(), Strategy)


def test_trend_following_strategy_name_and_version():
    strategy = TrendFollowingStrategy()
    assert strategy.name == "trend_following"
    assert strategy.version == "1.0"
