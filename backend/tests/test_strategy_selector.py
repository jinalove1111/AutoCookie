"""Tests for app.strategy.selector: the Strategy Selection Engine
(operator directive, 2026-07-15, docs/ADAPTIVE_ARCHITECTURE.md section 4).
"""

from __future__ import annotations

from app.regime.regime_detector import MarketRegime
from app.strategy.selector import DefaultToLegacySelector, StrategySelector
from app.strategy.strategy_interface import AVAILABLE_STRATEGIES, JadeStrategy, LegacyStrategy


def _regime(trend: str = "strong_trend") -> MarketRegime:
    return MarketRegime(
        trend=trend,
        volatility="normal_volatility",
        breakout=False,
        mean_reversion=False,
        liquidity_sweep_environment=False,
        metrics={},
    )


def test_default_to_legacy_selector_conforms_to_protocol():
    assert isinstance(DefaultToLegacySelector(), StrategySelector)


def test_default_to_legacy_selector_returns_legacy_for_any_regime():
    selector = DefaultToLegacySelector()
    for trend in ("strong_trend", "weak_trend", "range"):
        chosen = selector.select(_regime(trend), AVAILABLE_STRATEGIES)
        assert chosen is AVAILABLE_STRATEGIES["legacy"]
        assert isinstance(chosen, LegacyStrategy)


def test_default_to_legacy_selector_returns_legacy_when_regime_is_none():
    selector = DefaultToLegacySelector()
    chosen = selector.select(None, AVAILABLE_STRATEGIES)
    assert chosen is AVAILABLE_STRATEGIES["legacy"]


def test_default_to_legacy_selector_ignores_which_strategies_are_available():
    selector = DefaultToLegacySelector()
    available = {"legacy": AVAILABLE_STRATEGIES["legacy"], "jade": AVAILABLE_STRATEGIES["jade"]}
    chosen = selector.select(_regime(), available)
    assert isinstance(chosen, LegacyStrategy)
    assert not isinstance(chosen, JadeStrategy)
