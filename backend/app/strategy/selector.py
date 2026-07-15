"""Strategy Selection Engine (operator directive, 2026-07-15):
docs/ADAPTIVE_ARCHITECTURE.md section 4. Sits between the Market Regime
Detector (`app.regime.regime_detector`) and the Strategy registry
(`AVAILABLE_STRATEGIES` in `strategy_interface.py`) -- picks which
`Strategy` to invoke for a given `MarketRegime`.

`DefaultToLegacySelector` is deliberately the least interesting possible
implementation: it selects `legacy` unconditionally, regardless of
regime. This project's "evidence over assumption" discipline
(ENGINEERING_DECISIONS.md, applied throughout the profitability sprint
and continuous research phases) forbids inventing regime->strategy
mappings with zero supporting data -- no regime-tagged trade history
exists yet (that's what the Performance Database extensions, section 6,
start collecting). Turning this selector on changes NOTHING about
production behavior today; it only gives every downstream stage (Risk
Engine, Execution, Performance Evaluation, Continuous Learning) a real
Strategy Selection stage to integrate with ahead of having real evidence
to route on.

Evolution path (not built yet, sequenced after real regime-tagged data
exists -- section 4.3): a `RollingPerformanceSelector` that picks
`argmax` strategy by rolling expectancy within each regime, requiring a
real sample-size floor (this project's established 20+ trades,
`experiment_runner.MIN_TRADES_FOR_CONFIDENCE`) before trusting any
regime/strategy cell, falling back to `legacy` otherwise.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.regime.regime_detector import MarketRegime

from .strategy_interface import Strategy


@runtime_checkable
class StrategySelector(Protocol):
    def select(self, regime: "MarketRegime | None", available: dict[str, Strategy]) -> Strategy: ...


class DefaultToLegacySelector:
    """Selects `legacy` unconditionally. See module docstring."""

    def select(self, regime: "MarketRegime | None", available: dict[str, Strategy]) -> Strategy:
        return available["legacy"]
