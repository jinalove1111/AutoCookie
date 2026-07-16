"""Tests for `app.strategy.selector.RollingPerformanceSelector` (Milestone
16, 2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md section 4.3).

All evidence is synthetic -- `RegimeCellEvidence` instances built by hand,
no database involved (this class takes evidence as a caller-computed plain
argument, per ENGINEERING_DECISIONS.md #49 -- see the class docstring), so
these tests exercise the selection rule in complete isolation against
hand-picked expectancy/n combinations, matching this project's established
"computation tested against hand-built fixtures" discipline
(`test_rolling_regime_performance.py`'s own docstring, `regime_analysis`'s
tests, `shadow_status`'s tests).

Legacy fallback is the ABSOLUTE default (Hard Rule #1 of this milestone's
scope): every test that is not the single "challenger legitimately wins"
case asserts the selection stays legacy.
"""

from __future__ import annotations

from app.portfolio.rolling_regime_performance import RegimeCellEvidence
from app.regime.regime_detector import MarketRegime
from app.strategy.selector import RollingPerformanceSelector, SelectionDecision, StrategySelector
from app.strategy.strategy_interface import LegacyStrategy, Strategy

BUCKET = "weak_trend/normal_volatility"
WINDOW_DAYS = 30


class _FakeStrategy:
    """A minimal `Strategy` Protocol conformer for a synthetic challenger
    -- structurally identical shape to `LegacyStrategy`/`JadeStrategy`
    (name + version + generate_signal), but standing in for a strategy
    name not present in the real `AVAILABLE_STRATEGIES` registry, since
    these tests need to name whichever cells they build by hand."""

    def __init__(self, name: str, version: str = "1.0"):
        self.name = name
        self.version = version

    def generate_signal(self, symbol, ltf_candles, htf_candles):
        return None


def _available(*names: str) -> dict[str, Strategy]:
    reg: dict[str, Strategy] = {"legacy": LegacyStrategy()}
    for name in names:
        reg[name] = _FakeStrategy(name)
    return reg


def _cell(
    strategy_name: str,
    bucket: str,
    source: str,
    n: int,
    expectancy_r: float,
    win_rate: float = 0.5,
    min_samples: int = 20,
) -> RegimeCellEvidence:
    return RegimeCellEvidence(
        strategy_name=strategy_name,
        bucket=bucket,
        source=source,
        n=n,
        win_rate=win_rate,
        expectancy_r=expectancy_r,
        n_excluded=0,
        sufficient=n >= min_samples,
        window_days=WINDOW_DAYS,
    )


def _regime(trend: str = "weak_trend", volatility: str = "normal_volatility") -> MarketRegime:
    return MarketRegime(
        trend=trend,
        volatility=volatility,
        breakout=False,
        mean_reversion=False,
        liquidity_sweep_environment=False,
        metrics={},
    )


# --------------------------------------------------------------------
# Protocol conformance
# --------------------------------------------------------------------


def test_rolling_performance_selector_conforms_to_protocol():
    assert isinstance(RollingPerformanceSelector(evidence={}), StrategySelector)


# --------------------------------------------------------------------
# regime is None
# --------------------------------------------------------------------


def test_regime_none_returns_legacy():
    available = _available("challenger")
    evidence = {
        ("legacy", BUCKET, "live"): _cell("legacy", BUCKET, "live", 50, 0.30),
        ("challenger", BUCKET, "live"): _cell("challenger", BUCKET, "live", 50, 5.0),
    }
    selector = RollingPerformanceSelector(evidence=evidence)

    decision = selector.select_with_reason(None, available)

    assert isinstance(decision, SelectionDecision)
    assert isinstance(decision.strategy, LegacyStrategy)
    assert decision.regime is None
    assert decision.selection_reason == "fallback_legacy_no_regime"
    assert decision.fallback_reason is not None
    via_select = selector.select(None, available)
    assert isinstance(via_select, LegacyStrategy)


# --------------------------------------------------------------------
# empty evidence
# --------------------------------------------------------------------


def test_empty_evidence_returns_legacy():
    available = _available("challenger")
    selector = RollingPerformanceSelector(evidence={})

    decision = selector.select_with_reason(_regime(), available)

    assert isinstance(decision.strategy, LegacyStrategy)
    assert decision.selection_reason == "fallback_legacy_baseline_unmeasured"
    assert decision.fallback_reason is not None
    assert BUCKET in decision.fallback_reason


# --------------------------------------------------------------------
# legacy baseline unmeasured, even against a strong challenger
# --------------------------------------------------------------------


def test_legacy_unmeasured_stays_legacy_even_with_strong_challenger():
    available = _available("challenger")
    evidence = {
        # legacy live cell is BELOW the floor -> insufficient
        ("legacy", BUCKET, "live"): _cell("legacy", BUCKET, "live", 5, 0.10),
        ("challenger", BUCKET, "live"): _cell("challenger", BUCKET, "live", 100, 10.0),
    }
    selector = RollingPerformanceSelector(evidence=evidence)

    decision = selector.select_with_reason(_regime(), available)

    assert isinstance(decision.strategy, LegacyStrategy)
    assert decision.selection_reason == "fallback_legacy_baseline_unmeasured"


# --------------------------------------------------------------------
# a sufficient challenger strictly beating a sufficient legacy wins
# --------------------------------------------------------------------


def test_sufficient_challenger_strictly_beating_legacy_wins():
    available = _available("challenger")
    evidence = {
        ("legacy", BUCKET, "live"): _cell("legacy", BUCKET, "live", 30, 0.30),
        ("challenger", BUCKET, "live"): _cell("challenger", BUCKET, "live", 40, 0.80),
    }
    selector = RollingPerformanceSelector(evidence=evidence)

    decision = selector.select_with_reason(_regime(), available)

    assert decision.strategy.name == "challenger"
    assert decision.selection_reason == "rolling_performance_argmax"
    assert decision.fallback_reason is None
    assert decision.strategy_version == "1.0"
    via_select = selector.select(_regime(), available)
    assert via_select.name == "challenger"


# --------------------------------------------------------------------
# challenger equal to legacy -> legacy (strict inequality)
# --------------------------------------------------------------------


def test_challenger_equal_to_legacy_stays_legacy():
    available = _available("challenger")
    evidence = {
        ("legacy", BUCKET, "live"): _cell("legacy", BUCKET, "live", 30, 0.50),
        ("challenger", BUCKET, "live"): _cell("challenger", BUCKET, "live", 40, 0.50),
    }
    selector = RollingPerformanceSelector(evidence=evidence)

    decision = selector.select_with_reason(_regime(), available)

    assert isinstance(decision.strategy, LegacyStrategy)
    assert decision.selection_reason == "fallback_legacy_no_qualifying_challenger"


# --------------------------------------------------------------------
# challenger positive but below legacy -> legacy
# --------------------------------------------------------------------


def test_challenger_positive_but_below_legacy_stays_legacy():
    available = _available("challenger")
    evidence = {
        ("legacy", BUCKET, "live"): _cell("legacy", BUCKET, "live", 30, 0.80),
        ("challenger", BUCKET, "live"): _cell("challenger", BUCKET, "live", 40, 0.20),
    }
    selector = RollingPerformanceSelector(evidence=evidence)

    decision = selector.select_with_reason(_regime(), available)

    assert isinstance(decision.strategy, LegacyStrategy)
    assert decision.selection_reason == "fallback_legacy_no_qualifying_challenger"


# --------------------------------------------------------------------
# challenger negative but above a negative legacy -> legacy (>0 gate)
# --------------------------------------------------------------------


def test_challenger_negative_above_negative_legacy_stays_legacy():
    available = _available("challenger")
    evidence = {
        ("legacy", BUCKET, "live"): _cell("legacy", BUCKET, "live", 30, -0.50),
        # challenger beats legacy's expectancy (-0.10 > -0.50) but is still
        # negative -- the explicit >0 gate must reject it regardless.
        ("challenger", BUCKET, "live"): _cell("challenger", BUCKET, "live", 40, -0.10),
    }
    selector = RollingPerformanceSelector(evidence=evidence)

    decision = selector.select_with_reason(_regime(), available)

    assert isinstance(decision.strategy, LegacyStrategy)
    assert decision.selection_reason == "fallback_legacy_no_qualifying_challenger"


# --------------------------------------------------------------------
# live precedence: bad live cell + great shadow cell -> live governs
# --------------------------------------------------------------------


def test_live_precedence_bad_live_cell_ignores_great_shadow_cell():
    available = _available("challenger")
    evidence = {
        ("legacy", BUCKET, "live"): _cell("legacy", BUCKET, "live", 30, 0.50),
        # live cell is sufficient but does not beat legacy -> must NOT be
        # skipped in favor of the (better-looking) shadow cell below.
        ("challenger", BUCKET, "live"): _cell("challenger", BUCKET, "live", 40, 0.10),
        ("challenger", BUCKET, "shadow"): _cell("challenger", BUCKET, "shadow", 100, 9.99),
    }
    selector = RollingPerformanceSelector(evidence=evidence)

    decision = selector.select_with_reason(_regime(), available)

    assert isinstance(decision.strategy, LegacyStrategy)
    assert decision.selection_reason == "fallback_legacy_no_qualifying_challenger"


# --------------------------------------------------------------------
# shadow-evidence win carries the optimism marker
# --------------------------------------------------------------------


def test_shadow_evidence_win_carries_optimism_marker():
    available = _available("challenger")
    evidence = {
        ("legacy", BUCKET, "live"): _cell("legacy", BUCKET, "live", 30, 0.30),
        # no live cell for challenger at all -- only a sufficient, winning
        # shadow cell.
        ("challenger", BUCKET, "shadow"): _cell("challenger", BUCKET, "shadow", 40, 0.90),
    }
    selector = RollingPerformanceSelector(evidence=evidence)

    decision = selector.select_with_reason(_regime(), available)

    assert decision.strategy.name == "challenger"
    assert decision.selection_reason == "rolling_performance_argmax_shadow_evidence_optimistic"
    assert decision.fallback_reason is None


# --------------------------------------------------------------------
# insufficient challenger (n=19) -> legacy
# --------------------------------------------------------------------


def test_challenger_below_sample_floor_stays_legacy():
    available = _available("challenger")
    evidence = {
        ("legacy", BUCKET, "live"): _cell("legacy", BUCKET, "live", 30, 0.30),
        # n=19 is one below the 20-sample floor -> sufficient=False even
        # though its expectancy would otherwise qualify.
        ("challenger", BUCKET, "live"): _cell("challenger", BUCKET, "live", 19, 5.0),
    }
    selector = RollingPerformanceSelector(evidence=evidence)

    decision = selector.select_with_reason(_regime(), available)

    assert isinstance(decision.strategy, LegacyStrategy)
    assert decision.selection_reason == "fallback_legacy_no_qualifying_challenger"


# --------------------------------------------------------------------
# tie among multiple qualifying challengers -> legacy
# --------------------------------------------------------------------


def test_tied_qualifying_challengers_stay_legacy():
    available = _available("challenger_a", "challenger_b")
    evidence = {
        ("legacy", BUCKET, "live"): _cell("legacy", BUCKET, "live", 30, 0.30),
        ("challenger_a", BUCKET, "live"): _cell("challenger_a", BUCKET, "live", 40, 0.80),
        ("challenger_b", BUCKET, "live"): _cell("challenger_b", BUCKET, "live", 50, 0.80),
    }
    selector = RollingPerformanceSelector(evidence=evidence)

    decision = selector.select_with_reason(_regime(), available)

    assert isinstance(decision.strategy, LegacyStrategy)
    assert decision.selection_reason == "fallback_legacy_tied_challengers"


# --------------------------------------------------------------------
# min_samples is honored by the caller-supplied evidence's own
# `sufficient` flag (this class does not recompute it)
# --------------------------------------------------------------------


def test_custom_min_samples_reflected_via_evidence_sufficiency():
    available = _available("challenger")
    # Built with min_samples=10, so n=15 is sufficient here even though
    # it would not be at the default floor of 20.
    evidence = {
        ("legacy", BUCKET, "live"): _cell("legacy", BUCKET, "live", 15, 0.30, min_samples=10),
        ("challenger", BUCKET, "live"): _cell(
            "challenger", BUCKET, "live", 15, 0.80, min_samples=10
        ),
    }
    selector = RollingPerformanceSelector(evidence=evidence, min_samples=10)

    decision = selector.select_with_reason(_regime(), available)

    assert decision.strategy.name == "challenger"
    assert decision.selection_reason == "rolling_performance_argmax"


# --------------------------------------------------------------------
# bucket computed from regime.trend/regime.volatility, matches
# market_regime_bucket's own convention
# --------------------------------------------------------------------


def test_bucket_computed_from_regime_trend_and_volatility():
    available = _available("challenger")
    other_bucket = "strong_trend/high_volatility"
    evidence = {
        # Evidence exists only for a DIFFERENT bucket -- the selector
        # must not accidentally match across buckets.
        (
            "legacy",
            other_bucket,
            "live",
        ): _cell("legacy", other_bucket, "live", 30, 0.30),
        (
            "challenger",
            other_bucket,
            "live",
        ): _cell("challenger", other_bucket, "live", 40, 5.0),
    }
    selector = RollingPerformanceSelector(evidence=evidence)

    decision = selector.select_with_reason(_regime("weak_trend", "normal_volatility"), available)
    assert isinstance(decision.strategy, LegacyStrategy)
    assert decision.selection_reason == "fallback_legacy_baseline_unmeasured"

    decision2 = selector.select_with_reason(
        _regime("strong_trend", "high_volatility"), available
    )
    assert decision2.strategy.name == "challenger"
