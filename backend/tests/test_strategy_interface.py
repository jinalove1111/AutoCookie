"""Tests for app.strategy.strategy_interface: the common Strategy
Protocol and its two adapters (LegacyStrategy, JadeStrategy), operator
directive 2026-07-15 ("Strategies are modules... every strategy must
implement the same interface").

Adapters are thin wrappers around SignalEngine.generate_signal -- these
tests prove DELEGATION (same result as calling SignalEngine directly with
the matching use_jade_engine value), not new detection logic, matching
the module's own "adds no new trading logic" docstring claim.
"""

from __future__ import annotations

from app.strategy.signal_engine import SignalEngine, TradeSignal
from app.strategy.strategy_interface import (
    AVAILABLE_STRATEGIES,
    JadeStrategy,
    LegacyStrategy,
    Strategy,
)


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def _bullish_confluence_candles() -> list[dict]:
    """Same real, known-to-signal fixture as
    test_strategy_signal_engine.py's `_bullish_confluence_candles` --
    duplicated here (small, disclosed, same precedent as
    session_liquidity.py's day/week math, ENGINEERING_DECISIONS.md #27)
    rather than importing across test modules.
    """
    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    candles = [candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]
    candles.append(candle(31, 32, 29, 31, "t13"))
    candles.append(candle(31, 40, 30, 39, "t14"))
    candles.append(candle(39, 42, 35, 41, "t15"))
    candles.append(candle(9, 10, 6, 9.5, "t16"))
    return candles


def test_legacy_strategy_satisfies_the_protocol():
    assert isinstance(LegacyStrategy(), Strategy)


def test_jade_strategy_satisfies_the_protocol():
    assert isinstance(JadeStrategy(), Strategy)


def test_legacy_strategy_name():
    assert LegacyStrategy().name == "legacy"


def test_jade_strategy_name():
    assert JadeStrategy().name == "jade"


def test_legacy_strategy_delegates_to_signal_engine_use_jade_engine_false():
    """LegacyStrategy must produce the EXACT same signal SignalEngine
    itself produces with use_jade_engine=False -- proving delegation, not
    reimplementation."""
    ltf = _bullish_confluence_candles()
    htf = _bullish_confluence_candles()

    via_adapter = LegacyStrategy().generate_signal("BTCUSDT", ltf, htf)
    via_engine = SignalEngine().generate_signal("BTCUSDT", ltf, htf, use_jade_engine=False)

    assert via_adapter is not None
    assert isinstance(via_adapter, TradeSignal)
    assert via_adapter == via_engine


def test_jade_strategy_delegates_to_signal_engine_use_jade_engine_true():
    """JadeStrategy must produce the EXACT same result SignalEngine
    itself produces with use_jade_engine=True (None or a TradeSignal --
    either is fine, this proves delegation not a specific business
    outcome, matching this fixture's own known behavior: Jade's models
    have stricter same-bar retracement requirements than Legacy's, see
    ENGINEERING_DECISIONS.md #36, so this real fixture is not guaranteed
    to signal on the Jade path even though it does on the Legacy path)."""
    ltf = _bullish_confluence_candles()
    htf = _bullish_confluence_candles()

    via_adapter = JadeStrategy().generate_signal("BTCUSDT", ltf, htf)
    via_engine = SignalEngine().generate_signal("BTCUSDT", ltf, htf, use_jade_engine=True)

    assert via_adapter == via_engine


def test_available_strategies_registry_contains_both_conforming_modules():
    assert set(AVAILABLE_STRATEGIES) == {"legacy", "jade"}
    for name, strategy in AVAILABLE_STRATEGIES.items():
        assert isinstance(strategy, Strategy)
        assert strategy.name == name


def test_legacy_strategy_version():
    assert LegacyStrategy().version == "1.0"


def test_jade_strategy_version():
    assert JadeStrategy().version == "1.0"
