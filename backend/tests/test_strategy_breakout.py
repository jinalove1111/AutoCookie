"""Tests for app.strategy.breakout.BreakoutStrategy: Donchian-channel
breakout with ATR/volume confirmation (adaptive platform Milestone 9,
2026-07-16 -- see the module's own docstring for the full
"disclosed-not-tuned" disclosure, docs/ADAPTIVE_ARCHITECTURE.md section 7
milestone 8).

Fixtures build a flat 20-candle "prior" window (constant high/low/volume)
so the Donchian channel and average volume are trivially known, then
append one more "current" candle that either breaks the channel with/
without confirmation, or stays inside it.
"""

from __future__ import annotations

import pytest

from app.strategy.breakout import BreakoutStrategy
from app.strategy.signal_engine import TradeSignal
from app.strategy.strategy_interface import Strategy
from app.strategy.utils import average_true_range


def candle(open_: float, high: float, low: float, close: float, volume: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume, "timestamp": ts}


def _flat_prior_candles(n: int = 20) -> list[dict]:
    """20 identical candles: high=110, low=90, open=close=100, volume=100.
    Channel high/low and average volume are then exactly 110/90/100."""
    return [candle(100, 110, 90, 100, 100, f"t{i}") for i in range(n)]


def _htf_candles() -> list[dict]:
    """HTF candles too short to produce a bias -- BreakoutStrategy does
    not gate on HTF bias, it only records it (detect_htf_bias returns
    "neutral" below 10 candles), so this is deliberately minimal."""
    return [candle(100, 101, 99, 100, 100, f"h{i}") for i in range(3)]


def test_confirmed_long_breakout_signal():
    candles = _flat_prior_candles() + [candle(100, 125, 99, 124, 100, "t20")]
    atr = average_true_range(candles, lookback=14)

    signal = BreakoutStrategy().generate_signal("BTCUSDT", candles, _htf_candles())

    assert signal is not None
    assert isinstance(signal, TradeSignal)
    assert signal.direction == "long"
    assert signal.status == "pending"
    assert signal.entry_price == 124
    expected_stop = 110 - 0.5 * atr
    expected_tp = 124 + 2.5 * (124 - expected_stop)
    assert signal.stop_loss == pytest.approx(expected_stop)
    assert signal.take_profit == pytest.approx(expected_tp)
    assert signal.rr == pytest.approx(2.5)


def test_confirmed_short_breakdown_signal():
    candles = _flat_prior_candles() + [candle(100, 101, 75, 76, 100, "t20")]
    atr = average_true_range(candles, lookback=14)

    signal = BreakoutStrategy().generate_signal("BTCUSDT", candles, _htf_candles())

    assert signal is not None
    assert isinstance(signal, TradeSignal)
    assert signal.direction == "short"
    assert signal.status == "pending"
    assert signal.entry_price == 76
    expected_stop = 90 + 0.5 * atr
    expected_tp = 76 - 2.5 * (expected_stop - 76)
    assert signal.stop_loss == pytest.approx(expected_stop)
    assert signal.take_profit == pytest.approx(expected_tp)
    assert signal.rr == pytest.approx(2.5)


def test_close_above_channel_without_confirmation_returns_none():
    """Closes beyond the channel high but with a tiny body AND volume at
    (not above) the channel average -- neither confirmation condition is
    met, so this must not signal."""
    candles = _flat_prior_candles() + [candle(111, 112, 110.5, 111.5, 100, "t20")]

    signal = BreakoutStrategy().generate_signal("BTCUSDT", candles, _htf_candles())

    assert signal is None


def test_inside_channel_close_returns_none():
    candles = _flat_prior_candles() + [candle(100, 106, 99, 105, 100, "t20")]

    signal = BreakoutStrategy().generate_signal("BTCUSDT", candles, _htf_candles())

    assert signal is None


def test_insufficient_history_returns_none():
    candles = _flat_prior_candles(n=20)  # 20 total, need 21

    signal = BreakoutStrategy().generate_signal("BTCUSDT", candles, _htf_candles())

    assert signal is None


def test_breakout_strategy_satisfies_the_protocol():
    assert isinstance(BreakoutStrategy(), Strategy)
    assert BreakoutStrategy().name == "breakout"
    assert BreakoutStrategy().version == "1.0"
