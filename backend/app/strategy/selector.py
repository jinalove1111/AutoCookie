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

from dataclasses import dataclass
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


@dataclass
class SelectionDecision:
    """Full observability record for one Strategy Selection Engine
    decision (adaptive platform milestone 7b, operator directive
    2026-07-16, ENGINEERING_DECISIONS.md #50). Richer than the plain
    `Strategy` `StrategySelector.select()` returns -- callers that want
    the reasoning behind a decision (e.g. `scripts/run_paper.py`, for
    logging/persistence) use `ConfigurableFallbackSelector.
    select_with_reason()` below instead of the bare Protocol method.
    """

    strategy: Strategy
    selection_reason: str
    fallback_reason: str | None
    regime: "MarketRegime | None"
    strategy_version: str


class ConfigurableFallbackSelector:
    """Deterministic selector with exactly one operator-controlled lever
    (`use_jade_engine`) and one hard-coded, unconditional fallback
    (`legacy`) -- built to satisfy an explicit operator requirement set
    (2026-07-16) for wiring the Strategy Selection Engine into paper
    trading WITHOUT silently disabling the existing `settings.
    USE_JADE_ENGINE` toggle or enabling any automatic regime-based
    switching:

    1. If `use_jade_engine` is `True` (an EXPLICIT operator override,
       read from `settings.USE_JADE_ENGINE` by the caller and passed in
       at construction -- never read from `settings` inside this class,
       same "caller-computed plain value" pattern decision #49 already
       established for `app.risk`), selects `jade`.
    2. Otherwise, ALWAYS selects `legacy` -- deterministically, with no
       regime-conditioned branching whatsoever. `regime` is accepted and
       recorded on the returned `SelectionDecision` for observability
       ONLY; it never influences which strategy is chosen. This is not a
       simplification to be improved later in the same class -- it is
       the explicit requirement ("do not enable automatic regime-based
       switching in production yet"). The real regime-conditioned
       selector is the DIFFERENT, not-yet-built `RollingPerformanceSelector`
       named in this module's docstring (section 4.3), which requires
       real validated evidence this selector deliberately does not
       assume exists.
    """

    def __init__(self, use_jade_engine: bool = False):
        self._use_jade_engine = use_jade_engine

    def select(self, regime: "MarketRegime | None", available: dict[str, Strategy]) -> Strategy:
        """`StrategySelector` Protocol conformance -- delegates to
        `select_with_reason` and returns only the chosen `Strategy`."""
        return self.select_with_reason(regime, available).strategy

    def select_with_reason(
        self, regime: "MarketRegime | None", available: dict[str, Strategy]
    ) -> SelectionDecision:
        if self._use_jade_engine and "jade" in available:
            jade = available["jade"]
            return SelectionDecision(
                strategy=jade,
                selection_reason="operator_override_use_jade_engine",
                fallback_reason=None,
                regime=regime,
                strategy_version=jade.version,
            )

        legacy = available["legacy"]
        return SelectionDecision(
            strategy=legacy,
            selection_reason="default_legacy_no_operator_override",
            fallback_reason=(
                "automatic regime-based strategy switching is disabled in "
                "production (operator instruction, 2026-07-16); no "
                "regime-conditioned strategy has validated rolling-performance "
                "evidence yet even if switching were enabled"
            ),
            regime=regime,
            strategy_version=legacy.version,
        )
