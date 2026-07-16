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

from app.portfolio.rolling_regime_performance import LIVE_SOURCE, SHADOW_SOURCE, RegimeCellEvidence
from app.portfolio.shadow_status import market_regime_bucket
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


# --- RollingPerformanceSelector (Milestone 16, 2026-07-16) ---------------
#
# The regime-conditioned, evidence-gated selector named as the evolution
# path in this module's own docstring (top of file) and
# `docs/ADAPTIVE_ARCHITECTURE.md` section 4.3 since Milestone 4. Ships as
# CODE + TESTS + a read-only dry-run CLI (`scripts/selector_dry_run.py`)
# ONLY -- `scripts/run_paper.py` is untouched and keeps running
# `ConfigurableFallbackSelector` exclusively (see that class's own
# docstring above). Wiring this class into production is an explicit,
# evidence-gated future operator decision, not something building it does.

# Disclosed-not-tuned floor (Milestone 16). Same value/meaning as
# `rolling_regime_performance.MIN_TRADES_FOR_CONFIDENCE` /
# `shadow_status.MIN_TRADES_FOR_CONFIDENCE` / `experiment_runner.
# MIN_TRADES_FOR_CONFIDENCE` -- this project's one real evidence floor,
# re-declared locally rather than imported, the same "one floor, re-
# declared per module crossing" convention every one of those siblings
# already documents (see `rolling_regime_performance.py`'s own module
# docstring for the full rationale, including the backend/scripts
# one-way dependency boundary). NOT a statistical-significance threshold
# -- see the class docstring below.
DEFAULT_MIN_SAMPLES = 20


def select_for_bucket(
    bucket: str,
    evidence: dict[tuple[str, str, str], RegimeCellEvidence],
    available: dict[str, Strategy],
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> tuple[Strategy, str, str | None]:
    """Delegation seam: the actual selection rule, keyed on a plain
    `bucket` string (`"{trend}/{volatility}"`, or `"untagged"` --
    `rolling_regime_performance`/`shadow_status`'s own convention)
    instead of a real `MarketRegime` instance.

    `RollingPerformanceSelector.select_with_reason` below computes
    `bucket` from a real `MarketRegime` and calls straight through to
    this function. `scripts/selector_dry_run.py` calls it directly, once
    per candidate bucket (all 9 trend/volatility combinations plus
    "untagged"), WITHOUT ever constructing a `MarketRegime` -- a
    read-only audit of "what would every bucket resolve to today" has no
    live regime to build, only bucket labels, so this seam exists
    precisely so that CLI never needs to fabricate fake `MarketRegime`
    instances just to reach the selection rule.

    `min_samples` is accepted here for documentation/observability
    (recorded in `fallback_reason` on the baseline-unmeasured path) --
    the actual sufficiency gate applied is each `RegimeCellEvidence.
    sufficient` flag already carries, computed by whatever floor
    `collect_regime_evidence` was called with; this function never
    recomputes sufficiency itself.

    Returns `(strategy, selection_reason, fallback_reason)`.

    Selection rule (see `RollingPerformanceSelector`'s class docstring
    for the full regime-to-bucket step; this is the bucket-only core):

      1. Legacy baseline: `("legacy", bucket, "live")` must be a
         present, sufficient cell in `evidence`, or this immediately
         falls back to legacy ("fallback_legacy_baseline_unmeasured") --
         a challenger can never be judged against an unmeasured
         baseline. This is also what makes an EMPTY `evidence` dict
         resolve safely: no cell can ever be present in it.
      2. Every OTHER strategy in `available`: its `("live")` cell if
         sufficient, else its `("shadow")` cell if sufficient (live
         precedence -- a sufficient live cell is used even when a
         shadow cell for the same strategy looks better; shadow is
         never cherry-picked over an available live cell). No
         sufficient cell in either source -> not a candidate at all.
      3. A candidate QUALIFIES only if its cell's `expectancy_r` is
         BOTH `> 0` AND strictly `>` legacy's own cell `expectancy_r`
         (the `>0` gate: a challenger merely "less negative" than a
         losing legacy cell still does not qualify).
      4. Winner = the single qualifying candidate with the highest
         `expectancy_r`. Zero qualifying candidates, or a tie at the
         max, both fall back to legacy
         ("fallback_legacy_no_qualifying_challenger" /
         "fallback_legacy_tied_challengers" respectively) -- strict
         inequality only, no "close enough" tie-break.
      5. A winner selected on its SHADOW cell (not live) is still
         returned as the winner -- shadow evidence is real evidence,
         just optimistic (see `rolling_regime_performance`'s own
         shadow-is-optimistic caveat: simulated fills, no fees, no
         slippage) -- but `selection_reason` says so explicitly
         (`"rolling_performance_argmax_shadow_evidence_optimistic"`)
         rather than presenting it identically to a live-backed win.
    """
    legacy = available["legacy"]
    legacy_cell = evidence.get(("legacy", bucket, LIVE_SOURCE))
    if legacy_cell is None or not legacy_cell.sufficient:
        observed_n = legacy_cell.n if legacy_cell is not None else 0
        return (
            legacy,
            "fallback_legacy_baseline_unmeasured",
            (
                f"bucket={bucket!r}: legacy has no sufficient live evidence "
                f"cell (n={observed_n}, floor={min_samples}) -- a challenger "
                "cannot be judged against an unmeasured baseline"
            ),
        )

    qualifying: list[tuple[str, Strategy, RegimeCellEvidence, str]] = []
    insufficient_names: list[str] = []
    for name, strategy in available.items():
        if name == "legacy":
            continue
        live_cell = evidence.get((name, bucket, LIVE_SOURCE))
        if live_cell is not None and live_cell.sufficient:
            candidate_cell, source = live_cell, LIVE_SOURCE
        else:
            shadow_cell = evidence.get((name, bucket, SHADOW_SOURCE))
            if shadow_cell is not None and shadow_cell.sufficient:
                candidate_cell, source = shadow_cell, SHADOW_SOURCE
            else:
                insufficient_names.append(name)
                continue
        if candidate_cell.expectancy_r > 0 and candidate_cell.expectancy_r > legacy_cell.expectancy_r:
            qualifying.append((name, strategy, candidate_cell, source))

    if not qualifying:
        return (
            legacy,
            "fallback_legacy_no_qualifying_challenger",
            (
                f"bucket={bucket!r}: legacy live cell n={legacy_cell.n} "
                f"expectancy_r={legacy_cell.expectancy_r:.4f}; no other "
                "strategy had a sufficient (live-precedence) cell with "
                "expectancy_r > 0 AND strictly beating legacy's "
                f"(insufficient-evidence strategies this bucket: "
                f"{insufficient_names or 'none'})"
            ),
        )

    best_expectancy = max(cell.expectancy_r for _, _, cell, _ in qualifying)
    winners = [q for q in qualifying if q[2].expectancy_r == best_expectancy]
    if len(winners) != 1:
        tied = [name for name, _, _, _ in winners]
        return (
            legacy,
            "fallback_legacy_tied_challengers",
            (
                f"bucket={bucket!r}: {len(winners)} qualifying strategies "
                f"tied at expectancy_r={best_expectancy:.4f} ({tied}) -- no "
                "single argmax winner, legacy fallback absolute rule applies"
            ),
        )

    name, strategy, cell, source = winners[0]
    selection_reason = "rolling_performance_argmax"
    if source == SHADOW_SOURCE:
        selection_reason += "_shadow_evidence_optimistic"
    return strategy, selection_reason, None


class RollingPerformanceSelector:
    """Regime-conditioned, evidence-gated Strategy Selector -- the
    `RollingPerformanceSelector` named as the evolution path in this
    module's own docstring and `docs/ADAPTIVE_ARCHITECTURE.md` section
    4.3 since Milestone 4 (Milestone 16, 2026-07-16). Picks `argmax`
    strategy by rolling expectancy WITHIN a regime bucket, gated by a
    real sample-size floor on BOTH sides of every comparison, with an
    ABSOLUTE fallback to `legacy` on any missing/insufficient/ambiguous
    evidence (see module-level `select_for_bucket` above for the full
    step-by-step rule this class applies).

    NOT WIRED INTO PRODUCTION as of this milestone: `scripts/run_paper.py`
    still runs `ConfigurableFallbackSelector` exclusively (see that
    class's own docstring above) -- turning automatic regime-based
    switching on is an explicit, evidence-gated future operator decision,
    not something building this class does. This class ships as code +
    tests + a read-only dry-run CLI (`scripts/selector_dry_run.py`) only.

    Constructor takes `evidence` (a `collect_regime_evidence(...)` return
    value, `dict[(strategy_name, bucket, source), RegimeCellEvidence]`)
    as a caller-computed plain argument -- same "caller-computed inputs,
    no settings/DB reads inside the class" discipline
    `ConfigurableFallbackSelector` already established
    (ENGINEERING_DECISIONS.md #49): this class never opens a DB session
    or reads `settings` itself. A caller (a future `run_paper.py` wiring,
    or `scripts/selector_dry_run.py` today) is responsible for calling
    `collect_regime_evidence` against a real session and passing the
    resulting dict in.

    Selection rule, per regime:
      a. `regime is None` -> legacy ("no regime classification" -- a
         selector cannot bucket what it cannot classify).
      b. Otherwise `bucket = market_regime_bucket({"trend": regime.trend,
         "volatility": regime.volatility})` -- `"{trend}/{volatility}"`,
         the SAME convention `rolling_regime_performance`/`shadow_status`
         already established, applied to the same (trend, volatility)
         pair a real `MarketRegime` always carries (so this path never
         itself produces `"untagged"` -- only a genuinely missing
         `regime`, case (a), does; `"untagged"` is reachable through
         `select_for_bucket` directly, e.g. from the dry-run CLI).
      c. Legacy baseline cell: prefer (and require) `("legacy", bucket,
         "live")`; a challenger cannot win against an unmeasured
         baseline -- if legacy has NO sufficient cell in this bucket,
         legacy is selected (reason: baseline unmeasured).
      d. For every OTHER strategy in `available`: candidate cell = its
         `("live")` cell if sufficient, else its `("shadow")` cell if
         sufficient (live precedence -- real fills beat simulated); no
         sufficient cell -> not a candidate.
      e. Winner = argmax `expectancy_r` among candidates whose
         `expectancy_r` is BOTH `> 0` AND strictly `>` legacy's own cell
         `expectancy_r`. Ties, or no qualifying candidate, -> legacy.

    Honesty disclosures (do not remove/soften):
      - The `min_samples` floor (default 20, `DEFAULT_MIN_SAMPLES`, this
        project's one established evidence floor -- see
        `rolling_regime_performance.MIN_TRADES_FOR_CONFIDENCE`) plus this
        class's strict-inequality argmax is a DISCLOSED FLOOR, NOT a
        statistical-significance test: there is no t-test, confidence
        interval, or multiple-comparison correction anywhere in this
        class. 20 samples clearing a strict-inequality comparison is a
        much weaker claim than "statistically significant," and this
        class makes no stronger claim than that -- a real significance
        test is explicitly DEFERRED, not silently assumed to exist.
      - A winner selected on SHADOW evidence is real evidence, but
        `ShadowSignal` outcomes are simulated fills (no fees, no
        slippage -- an optimistic upper bound; see
        `rolling_regime_performance`'s own module docstring).
        `selection_reason` says so explicitly
        (`"..._shadow_evidence_optimistic"`) whenever it applies, rather
        than presenting a shadow-backed win identically to a live-backed
        one.
      - This class is NOT wired into production anywhere as of this
        milestone (see above).
    """

    def __init__(
        self,
        evidence: dict[tuple[str, str, str], RegimeCellEvidence],
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ):
        self._evidence = evidence
        self._min_samples = min_samples

    def select(self, regime: "MarketRegime | None", available: dict[str, Strategy]) -> Strategy:
        """`StrategySelector` Protocol conformance -- delegates to
        `select_with_reason` and returns only the chosen `Strategy`."""
        return self.select_with_reason(regime, available).strategy

    def select_with_reason(
        self, regime: "MarketRegime | None", available: dict[str, Strategy]
    ) -> SelectionDecision:
        legacy = available["legacy"]
        if regime is None:
            return SelectionDecision(
                strategy=legacy,
                selection_reason="fallback_legacy_no_regime",
                fallback_reason="no regime classification available for this pass",
                regime=None,
                strategy_version=legacy.version,
            )

        bucket = market_regime_bucket({"trend": regime.trend, "volatility": regime.volatility})
        strategy, selection_reason, fallback_reason = select_for_bucket(
            bucket, self._evidence, available, self._min_samples
        )
        return SelectionDecision(
            strategy=strategy,
            selection_reason=selection_reason,
            fallback_reason=fallback_reason,
            regime=regime,
            strategy_version=strategy.version,
        )
