"""Tests for app.strategy.selector: the Strategy Selection Engine
(operator directive, 2026-07-15, docs/ADAPTIVE_ARCHITECTURE.md section 4).
"""

from __future__ import annotations

from app.regime.regime_detector import MarketRegime
from app.strategy.selector import (
    ConfigurableFallbackSelector,
    DefaultToLegacySelector,
    SelectionDecision,
    StrategySelector,
)
from app.strategy.signal_engine import SignalEngine
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


# --- ConfigurableFallbackSelector (adaptive platform milestone 7b, ------
# operator directive 2026-07-16) -------------------------------------------


def test_configurable_fallback_selector_conforms_to_protocol():
    assert isinstance(ConfigurableFallbackSelector(), StrategySelector)


def test_configurable_fallback_selector_defaults_to_legacy_without_override():
    selector = ConfigurableFallbackSelector(use_jade_engine=False)
    chosen = selector.select(_regime(), AVAILABLE_STRATEGIES)
    assert isinstance(chosen, LegacyStrategy)


def test_configurable_fallback_selector_honors_use_jade_engine_override():
    selector = ConfigurableFallbackSelector(use_jade_engine=True)
    chosen = selector.select(_regime(), AVAILABLE_STRATEGIES)
    assert isinstance(chosen, JadeStrategy)


def test_configurable_fallback_selector_ignores_regime_for_the_final_choice():
    """Hard requirement (2026-07-16): no automatic regime-based switching
    yet -- every trend/volatility combination must produce the SAME
    selected strategy for a fixed use_jade_engine value."""
    selector_default = ConfigurableFallbackSelector(use_jade_engine=False)
    selector_override = ConfigurableFallbackSelector(use_jade_engine=True)

    for trend in ("strong_trend", "weak_trend", "range"):
        regime = _regime(trend)
        assert isinstance(selector_default.select(regime, AVAILABLE_STRATEGIES), LegacyStrategy)
        assert isinstance(selector_override.select(regime, AVAILABLE_STRATEGIES), JadeStrategy)

    # None (no regime available) must behave identically to a real regime.
    assert isinstance(selector_default.select(None, AVAILABLE_STRATEGIES), LegacyStrategy)
    assert isinstance(selector_override.select(None, AVAILABLE_STRATEGIES), JadeStrategy)


def test_configurable_fallback_selector_falls_back_to_jade_missing_defaults_legacy():
    """If "jade" isn't even in the available registry, an override request
    must still resolve deterministically to legacy, not raise a KeyError."""
    selector = ConfigurableFallbackSelector(use_jade_engine=True)
    chosen = selector.select(_regime(), {"legacy": AVAILABLE_STRATEGIES["legacy"]})
    assert isinstance(chosen, LegacyStrategy)


def test_select_with_reason_returns_full_decision_for_operator_override():
    selector = ConfigurableFallbackSelector(use_jade_engine=True)
    regime = _regime("strong_trend")

    decision = selector.select_with_reason(regime, AVAILABLE_STRATEGIES)

    assert isinstance(decision, SelectionDecision)
    assert isinstance(decision.strategy, JadeStrategy)
    assert decision.selection_reason == "operator_override_use_jade_engine"
    assert decision.fallback_reason is None
    assert decision.regime is regime
    assert decision.strategy_version == "1.0"


def test_select_with_reason_returns_full_decision_for_default_fallback():
    selector = ConfigurableFallbackSelector(use_jade_engine=False)
    regime = _regime("range")

    decision = selector.select_with_reason(regime, AVAILABLE_STRATEGIES)

    assert isinstance(decision.strategy, LegacyStrategy)
    assert decision.selection_reason == "default_legacy_no_operator_override"
    assert decision.fallback_reason is not None
    assert "regime-based" in decision.fallback_reason
    assert decision.regime is regime
    assert decision.strategy_version == "1.0"


def test_select_with_reason_records_regime_purely_for_observability():
    """The SAME strategy must be chosen regardless of regime, but the
    regime passed in must still be recorded verbatim on the decision --
    proving it's observed, not silently dropped, even though it never
    influences the choice."""
    selector = ConfigurableFallbackSelector(use_jade_engine=False)
    regime = _regime("strong_trend")

    decision = selector.select_with_reason(regime, AVAILABLE_STRATEGIES)

    assert decision.regime is regime
    assert isinstance(decision.strategy, LegacyStrategy)


def test_select_delegates_to_select_with_reason():
    selector = ConfigurableFallbackSelector(use_jade_engine=True)
    regime = _regime()

    via_select = selector.select(regime, AVAILABLE_STRATEGIES)
    via_select_with_reason = selector.select_with_reason(regime, AVAILABLE_STRATEGIES).strategy

    assert via_select is via_select_with_reason


# --- Regression: default configuration reproduces Legacy exactly --------
# (operator hard requirements 8/9, 2026-07-16: "The default configuration
# must reproduce the existing Legacy paper-trading behavior exactly" /
# "regression tests proving byte-for-byte equivalent signals, position
# sizing, and trade decisions under the default configuration.")
#
# Scope note: scripts/run_paper.py itself has no dedicated test file (true
# before this milestone too -- see conftest.py's module docstring and every
# prior adaptive-platform milestone's ENGINEERING_DECISIONS.md entry; it's
# exercised via real paper-trading runs, not pytest). The strongest
# feasible regression proof at this codebase's actual test-architecture
# level is: settings.USE_STRATEGY_SELECTOR defaults to False (so
# run_paper.py's untouched `else` branch is what actually executes by
# default -- verified by reading that branch, unchanged from before this
# milestone), AND the selector's own default output (use_jade_engine=False,
# the setting's own default) is byte-identical to calling SignalEngine
# directly with use_jade_engine=False -- the exact equivalence
# test_strategy_interface.py already established for LegacyStrategy itself,
# extended one layer out through the selector. Position sizing and risk
# evaluation are UNTOUCHED by this milestone (calculate_position_size/
# RiskManager.evaluate are not called anywhere in app.strategy.selector),
# so no new sizing/risk-decision regression tests are needed here --
# milestone 7's existing test_risk_drawdown_and_sizing.py/test_risk_manager.py
# coverage remains the regression guard for those, unchanged by this work.


def test_settings_use_strategy_selector_defaults_to_false():
    from app.config import Settings

    assert Settings().USE_STRATEGY_SELECTOR is False


def test_configurable_fallback_selector_default_config_matches_signal_engine_directly():
    """The selector's own default (use_jade_engine=False, matching
    settings.USE_JADE_ENGINE's default) must produce EXACTLY the signal
    SignalEngine().generate_signal(..., use_jade_engine=False) produces --
    proving the selector path introduces zero drift from Legacy's existing
    behavior, for the exact configuration every current paper-trading
    deployment runs under."""

    def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
        return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}

    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    candles = [candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]
    candles.append(candle(31, 32, 29, 31, "t13"))
    candles.append(candle(31, 40, 30, 39, "t14"))
    candles.append(candle(39, 42, 35, 41, "t15"))
    candles.append(candle(9, 10, 6, 9.5, "t16"))
    ltf = candles
    htf = candles

    selector = ConfigurableFallbackSelector(use_jade_engine=False)  # Settings() default
    decision = selector.select_with_reason(None, AVAILABLE_STRATEGIES)
    via_selector_path = decision.strategy.generate_signal("BTCUSDT", ltf, htf)
    via_direct_call = SignalEngine().generate_signal("BTCUSDT", ltf, htf, use_jade_engine=False)

    assert via_selector_path is not None
    assert via_selector_path == via_direct_call
    assert isinstance(decision.strategy, LegacyStrategy)
