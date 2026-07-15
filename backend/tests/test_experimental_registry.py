"""Tests for app.strategy.experimental -- the quarantined experimental
strategy registry (Milestone 9, 2026-07-16 -- see that module's docstring
for the full quarantine-discipline rationale).
"""

from __future__ import annotations

from app.strategy.experimental import EXPERIMENTAL_STRATEGIES, all_strategies
from app.strategy.selector import ConfigurableFallbackSelector, DefaultToLegacySelector
from app.strategy.strategy_interface import AVAILABLE_STRATEGIES, Strategy

EXPECTED_EXPERIMENTAL_NAMES = {
    "trend_following",
    "range_trading",
    "breakout",
    "volatility_expansion",
}


def test_all_strategies_contains_legacy_and_jade():
    """The production registry's two existing strategies must both be
    present in the merged view -- `all_strategies()` must never hide or
    drop anything from `AVAILABLE_STRATEGIES`."""
    strategies = all_strategies()
    assert "legacy" in strategies
    assert "jade" in strategies
    assert strategies["legacy"] is AVAILABLE_STRATEGIES["legacy"]
    assert strategies["jade"] is AVAILABLE_STRATEGIES["jade"]


def test_experimental_strategies_populated_with_expected_four():
    """Milestone 9 integration (2026-07-16): `EXPERIMENTAL_STRATEGIES` is no
    longer empty -- it now holds exactly the four strategy modules that
    landed alongside the quarantine mechanism, keyed by their own `.name`.
    (Previously this test asserted `EXPERIMENTAL_STRATEGIES == {}`; that
    assertion is replaced here now that population has happened -- see
    `test_experimental_strategies_conform_to_protocol` for the Protocol/key
    consistency checks.)"""
    assert set(EXPERIMENTAL_STRATEGIES.keys()) == EXPECTED_EXPERIMENTAL_NAMES


def test_experimental_strategies_conform_to_protocol():
    """Every experimental strategy must structurally satisfy the
    `Strategy` Protocol (`runtime_checkable`), and each dict key must
    equal that instance's own `.name` -- the same key/`.name` consistency
    `AVAILABLE_STRATEGIES` already guarantees for `legacy`/`jade`."""
    assert len(EXPERIMENTAL_STRATEGIES) == 4
    for key, instance in EXPERIMENTAL_STRATEGIES.items():
        assert isinstance(instance, Strategy)
        assert instance.name == key


def test_available_strategies_still_exactly_legacy_and_jade():
    """Production registry proof: populating `EXPERIMENTAL_STRATEGIES`
    must never touch `AVAILABLE_STRATEGIES` -- it must stay EXACTLY
    {"legacy", "jade"}, unchanged by the Milestone 9 integration."""
    assert set(AVAILABLE_STRATEGIES.keys()) == {"legacy", "jade"}


def test_all_strategies_has_exactly_six_expected_keys():
    """The merged view must have exactly the 6 expected keys: the 2
    production strategies plus the 4 experimental ones."""
    assert set(all_strategies().keys()) == {"legacy", "jade"} | EXPECTED_EXPERIMENTAL_NAMES
    assert len(all_strategies()) == 6


def test_production_selectors_never_select_an_experimental_strategy():
    """Production-safety proof: even if someone mistakenly passed the
    MERGED registry (`all_strategies()`, production + experimental) to a
    production selector instead of `AVAILABLE_STRATEGIES`, no experimental
    strategy could ever be selected -- both selectors only ever index
    `available["legacy"]` / `available["jade"]` directly (see
    `app.strategy.selector`), so an experimental module's mere presence in
    the dict passed in is inert."""
    merged = all_strategies()
    legacy = AVAILABLE_STRATEGIES["legacy"]
    jade = AVAILABLE_STRATEGIES["jade"]

    assert DefaultToLegacySelector().select(None, merged) is legacy

    assert ConfigurableFallbackSelector(use_jade_engine=False).select(None, merged) is legacy
    assert ConfigurableFallbackSelector(use_jade_engine=True).select(None, merged) is jade


def test_all_strategies_returns_a_fresh_merged_dict_each_call():
    """`all_strategies()` must return a NEW dict object every call (not a
    shared reference to either registry) -- mutating the returned mapping
    must never corrupt AVAILABLE_STRATEGIES or EXPERIMENTAL_STRATEGIES.
    """
    first = all_strategies()
    second = all_strategies()

    assert first is not second
    assert first == second
    assert first is not AVAILABLE_STRATEGIES
    assert first is not EXPERIMENTAL_STRATEGIES

    # Mutate the returned dict, then prove neither underlying registry was
    # touched.
    first["bogus"] = object()
    del first["legacy"]

    assert "bogus" not in AVAILABLE_STRATEGIES
    assert "bogus" not in EXPERIMENTAL_STRATEGIES
    assert "legacy" in AVAILABLE_STRATEGIES

    third = all_strategies()
    assert "bogus" not in third
    assert "legacy" in third


def test_all_strategies_merged_count_matches_both_registries_combined():
    """Sanity check on the merge itself: the merged dict's size equals the
    sum of both registries' sizes (true as long as no name collides between
    production and experimental -- documents that assumption explicitly
    rather than leaving it implicit)."""
    strategies = all_strategies()
    assert len(strategies) == len(AVAILABLE_STRATEGIES) + len(EXPERIMENTAL_STRATEGIES)
