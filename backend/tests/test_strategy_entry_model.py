"""Unit tests for app.strategy.entry_model: confluence rule (bias +
sweep/choch + a matching FVG/order-block zone) composed into an entry
candidate.
"""

from __future__ import annotations

from app.strategy.entry_model import build_entry_model

_SWEEP = {"type": "sell_side", "level": 100, "swept_index": 1, "sweep_index": 4}
_BULLISH_FVG = [{"type": "bullish", "top": 110, "bottom": 108, "index": 3}]


def test_build_entry_model_long_on_bullish_confluence():
    model = build_entry_model("bullish", _SWEEP, None, _BULLISH_FVG, None)

    assert model is not None
    assert model["direction"] == "long"
    assert model["entry_price"] == 110
    assert model["rr"] == 2.5
    # stop_loss just below the zone bottom (108), take_profit 2x the risk above entry.
    assert model["stop_loss"] < 108
    assert model["take_profit"] > model["entry_price"]
    assert model["zone"] == _BULLISH_FVG[0]


def test_build_entry_model_none_when_bias_neutral():
    assert build_entry_model("neutral", _SWEEP, None, _BULLISH_FVG, None) is None


def test_build_entry_model_none_without_sweep_or_choch():
    assert build_entry_model("bullish", None, None, _BULLISH_FVG, None) is None


def test_build_entry_model_none_without_matching_zone():
    assert build_entry_model("bullish", _SWEEP, None, [], None) is None


def test_build_entry_model_short_on_bearish_confluence():
    bearish_fvg = [{"type": "bearish", "top": 100, "bottom": 98, "index": 3}]
    choch = {"type": "bearish_choch", "broken_level": 99, "broken_index": 2, "confirm_index": 4}

    model = build_entry_model("bearish", None, choch, bearish_fvg, None)

    assert model is not None
    assert model["direction"] == "short"
    assert model["entry_price"] == 98
    assert model["stop_loss"] > 100
    assert model["take_profit"] < model["entry_price"]


def test_build_entry_model_prefers_order_block_over_older_fvg():
    order_block = {"type": "bullish", "top": 120, "bottom": 118, "index": 10}
    older_fvg = [{"type": "bullish", "top": 110, "bottom": 108, "index": 3}]

    model = build_entry_model("bullish", _SWEEP, None, older_fvg, order_block)

    # order_block has the more recent index (10 > 3), so it wins zone selection.
    assert model["zone"] == order_block
    assert model["entry_price"] == 120


# --- Breaker block as an additional zone candidate (optional 6th param,
# default None -- every test above omits it and is unaffected) ---


def test_build_entry_model_uses_breaker_block_when_no_other_zone_present():
    """A matching breaker block alone (no order block, no matching FVG)
    must still produce a valid entry -- proving it's a genuine additional
    zone source, not just a tie-breaker.
    """
    breaker_block = {"type": "bullish", "top": 105, "bottom": 103, "index": 7, "retest_index": 12}

    model = build_entry_model("bullish", _SWEEP, None, [], None, breaker_block)

    assert model is not None
    assert model["zone"] == breaker_block
    assert model["entry_price"] == 105


def test_build_entry_model_breaker_block_competes_by_index_like_fvg_and_ob():
    """A breaker block with a MORE recent index than an order block wins
    zone selection, same "most recent index wins" rule already governing
    FVG vs. OB.
    """
    order_block = {"type": "bullish", "top": 120, "bottom": 118, "index": 5}
    breaker_block = {"type": "bullish", "top": 105, "bottom": 103, "index": 9, "retest_index": 12}

    model = build_entry_model("bullish", _SWEEP, None, [], order_block, breaker_block)

    assert model["zone"] == breaker_block  # index 9 > order_block's index 5
    assert model["entry_price"] == 105


def test_build_entry_model_ignores_breaker_block_with_older_index():
    order_block = {"type": "bullish", "top": 120, "bottom": 118, "index": 10}
    breaker_block = {"type": "bullish", "top": 105, "bottom": 103, "index": 3, "retest_index": 4}

    model = build_entry_model("bullish", _SWEEP, None, [], order_block, breaker_block)

    assert model["zone"] == order_block  # index 10 > breaker_block's index 3


def test_build_entry_model_ignores_direction_mismatched_breaker_block():
    """A bearish breaker block must not count toward a bullish-bias long
    entry, same direction-matching discipline as FVG/OB."""
    bearish_breaker = {"type": "bearish", "top": 105, "bottom": 103, "index": 7, "retest_index": 12}

    model = build_entry_model("bullish", _SWEEP, None, [], None, bearish_breaker)

    assert model is None


# --- Regression tests: direction-matching confluence (the bug fixed here) ---
#
# Before this fix, `build_entry_model` only checked *presence* of a
# sweep/choch (`if sweep is None and choch is None: return None`), never
# whether its `type` actually agreed with the bias-derived direction. Each
# test below is a case that the pre-fix presence-only check would have
# wrongly accepted (producing a signal that entered against the engine's
# own structural read) and that direction-matching now correctly rejects.


def test_build_entry_model_none_on_bullish_bias_with_wrong_direction_sweep():
    """bullish bias => wants a `long` entry, which per the documented
    rule only accepts a `sell_side` sweep as valid confluence. A
    `buy_side` sweep (the sweep type that precedes a *bearish* reversal)
    must NOT count, even though a matching bullish FVG and no choch are
    otherwise present. Pre-fix, presence-only checking would have passed
    (`sweep is not None`) and returned a "long" signal; that would have
    been the engine entering long directly against a buy-side liquidity
    grab it just detected.
    """
    buy_side_sweep = {"type": "buy_side", "level": 100, "swept_index": 1, "sweep_index": 4}

    model = build_entry_model("bullish", buy_side_sweep, None, _BULLISH_FVG, None)

    assert model is None


def test_build_entry_model_none_on_bullish_bias_with_wrong_direction_choch():
    """Same bug, via CHOCH instead of sweep: bullish bias wants a
    `bullish_choch`, not a `bearish_choch`. Pre-fix, presence-only
    checking would have passed (`choch is not None`) and returned a
    "long" signal despite the CHOCH itself reading bearish.
    """
    bearish_choch = {
        "type": "bearish_choch",
        "broken_level": 99,
        "broken_index": 2,
        "confirm_index": 4,
    }

    model = build_entry_model("bullish", None, bearish_choch, _BULLISH_FVG, None)

    assert model is None


def test_build_entry_model_none_on_bearish_bias_with_wrong_direction_sweep():
    """Mirror case: bearish bias wants a `buy_side` sweep for a `short`
    entry; a `sell_side` sweep must not count even with a matching
    bearish FVG present.
    """
    sell_side_sweep = {"type": "sell_side", "level": 100, "swept_index": 1, "sweep_index": 4}
    bearish_fvg = [{"type": "bearish", "top": 100, "bottom": 98, "index": 3}]

    model = build_entry_model("bearish", sell_side_sweep, None, bearish_fvg, None)

    assert model is None


def test_build_entry_model_still_accepts_direction_matching_choch_alone():
    """Sanity check alongside the regression tests above: a CORRECTLY
    direction-matched choch (bearish_choch + bearish bias) with no sweep
    still produces a valid short entry -- this is
    test_build_entry_model_short_on_bearish_confluence's exact scenario,
    re-asserted here to make the contrast with the wrong-direction cases
    explicit within this block.
    """
    bearish_fvg = [{"type": "bearish", "top": 100, "bottom": 98, "index": 3}]
    choch = {"type": "bearish_choch", "broken_level": 99, "broken_index": 2, "confirm_index": 4}

    model = build_entry_model("bearish", None, choch, bearish_fvg, None)

    assert model is not None
    assert model["direction"] == "short"


# --- require_full_confluence (opt-in strict-confluence mode) ---------------


def test_build_entry_model_require_full_confluence_rejects_sweep_alone():
    """Default (loose) behavior accepts sweep alone (no choch) -- see
    test_build_entry_model_long_on_bullish_confluence. With
    require_full_confluence=True, the SAME inputs must be rejected since
    choch is missing.
    """
    model = build_entry_model(
        "bullish", _SWEEP, None, _BULLISH_FVG, None, require_full_confluence=True
    )
    assert model is None


def test_build_entry_model_require_full_confluence_rejects_choch_alone():
    """Mirrors the sweep-alone case: choch alone (no sweep) is accepted by
    default (see test_build_entry_model_still_accepts_direction_matching_
    choch_alone) but must be rejected under require_full_confluence=True.
    """
    bearish_fvg = [{"type": "bearish", "top": 100, "bottom": 98, "index": 3}]
    choch = {"type": "bearish_choch", "broken_level": 99, "broken_index": 2, "confirm_index": 4}

    model = build_entry_model(
        "bearish", None, choch, bearish_fvg, None, require_full_confluence=True
    )
    assert model is None


def test_build_entry_model_require_full_confluence_accepts_sweep_and_choch_both():
    """With BOTH a matching sweep AND a matching choch present,
    require_full_confluence=True must still produce a valid entry --
    the stricter mode narrows what's accepted, it doesn't break the
    case it's designed to require.
    """
    choch = {"type": "bullish_choch", "broken_level": 99, "broken_index": 2, "confirm_index": 4}

    model = build_entry_model(
        "bullish", _SWEEP, choch, _BULLISH_FVG, None, require_full_confluence=True
    )

    assert model is not None
    assert model["direction"] == "long"


def test_build_entry_model_require_full_confluence_still_respects_direction_matching():
    """require_full_confluence=True does not bypass the existing
    direction-matching rule: a wrong-direction sweep alongside a
    CORRECTLY matched choch still fails, since the wrong-direction sweep
    doesn't count as "matching" at all (matching_sweep stays None).
    """
    wrong_direction_sweep = {"type": "buy_side", "level": 100, "swept_index": 1, "sweep_index": 4}
    choch = {"type": "bullish_choch", "broken_level": 99, "broken_index": 2, "confirm_index": 4}

    model = build_entry_model(
        "bullish",
        wrong_direction_sweep,
        choch,
        _BULLISH_FVG,
        None,
        require_full_confluence=True,
    )
    assert model is None


# --- require_ob_fvg_confluence (opt-in OB+FVG confluence mode -- changes
# zone selection from "either zone" to "both agree", see
# docs/ROADMAP.md "Core Rule MVP completion" item #3) ---------------------


def test_build_entry_model_require_ob_fvg_confluence_rejects_fvg_alone():
    """Default (loose) behavior accepts an FVG alone (no order block) --
    see test_build_entry_model_long_on_bullish_confluence. With
    require_ob_fvg_confluence=True, the SAME inputs must be rejected since
    there is no matching order block/breaker block.
    """
    model = build_entry_model(
        "bullish", _SWEEP, None, _BULLISH_FVG, None, require_ob_fvg_confluence=True
    )
    assert model is None


def test_build_entry_model_require_ob_fvg_confluence_rejects_order_block_alone():
    """Mirrors the fvg-alone case: an order block alone (no matching FVG)
    is accepted by default (see
    test_build_entry_model_prefers_order_block_over_older_fvg's premise)
    but must be rejected under require_ob_fvg_confluence=True.
    """
    order_block = {"type": "bullish", "top": 120, "bottom": 118, "index": 10}

    model = build_entry_model(
        "bullish", _SWEEP, None, [], order_block, require_ob_fvg_confluence=True
    )
    assert model is None


def test_build_entry_model_require_ob_fvg_confluence_accepts_both_present():
    """With BOTH a matching order block AND a matching FVG present,
    require_ob_fvg_confluence=True must still produce a valid entry --
    the stricter mode narrows what's accepted, it doesn't break the case
    it's designed to require. Zone selection still follows "most recent
    index wins": the order block (index 10) is more recent than the FVG
    (index 3), so it's chosen as the entry zone.
    """
    order_block = {"type": "bullish", "top": 120, "bottom": 118, "index": 10}

    model = build_entry_model(
        "bullish", _SWEEP, None, _BULLISH_FVG, order_block, require_ob_fvg_confluence=True
    )

    assert model is not None
    assert model["direction"] == "long"
    assert model["zone"] == order_block


def test_build_entry_model_require_ob_fvg_confluence_breaker_block_satisfies_ob_side():
    """A breaker block (no order block) paired with a matching FVG must
    also satisfy require_ob_fvg_confluence=True -- the breaker block is a
    genuine alternative "OB side" candidate, same as in default mode."""
    breaker_block = {"type": "bullish", "top": 105, "bottom": 103, "index": 7, "retest_index": 12}

    model = build_entry_model(
        "bullish",
        _SWEEP,
        None,
        _BULLISH_FVG,
        None,
        breaker_block,
        require_ob_fvg_confluence=True,
    )

    assert model is not None
    # breaker_block (index 7) is more recent than the FVG (index 3).
    assert model["zone"] == breaker_block


def test_build_entry_model_require_ob_fvg_confluence_direction_mismatched_ob_still_rejected():
    """A bearish order block must not satisfy confluence for a
    bullish-bias long entry, even though a correctly-matched bullish FVG
    is present -- direction-matching still applies under
    require_ob_fvg_confluence=True.
    """
    bearish_order_block = {"type": "bearish", "top": 120, "bottom": 118, "index": 10}

    model = build_entry_model(
        "bullish",
        _SWEEP,
        None,
        _BULLISH_FVG,
        bearish_order_block,
        require_ob_fvg_confluence=True,
    )
    assert model is None


# --- use_structure_tp (opt-in structure-based take-profit, see
# docs/ROADMAP.md "Core Rule MVP completion" item #4) ---------------------


def test_build_entry_model_use_structure_tp_ignored_by_default():
    """Passing previous_swing_high/premium_discount without
    use_structure_tp=True must have zero effect -- the fixed-RR target
    (test_build_entry_model_long_on_bullish_confluence's exact result) is
    unchanged.
    """
    previous_swing_high = {"price": 200, "index": 20}
    premium_discount = {"top": 300, "bottom": 50, "equilibrium": 175, "zone": "discount",
                         "range_high_index": 20, "range_low_index": 0}

    model = build_entry_model(
        "bullish",
        _SWEEP,
        None,
        _BULLISH_FVG,
        None,
        previous_swing_high=previous_swing_high,
        premium_discount=premium_discount,
    )

    baseline = build_entry_model("bullish", _SWEEP, None, _BULLISH_FVG, None)
    assert model["take_profit"] == baseline["take_profit"]
    assert model["rr"] == baseline["rr"] == 2.5


def test_build_entry_model_use_structure_tp_targets_previous_swing_high():
    """With use_structure_tp=True and only a valid previous swing high
    (no premium_discount), take_profit targets that high directly --
    "long targets previous high first" -- and rr is recomputed as the
    real reward:risk, not the fixed _RR constant.
    """
    previous_swing_high = {"price": 130, "index": 20}

    model = build_entry_model(
        "bullish",
        _SWEEP,
        None,
        _BULLISH_FVG,
        None,
        previous_swing_high=previous_swing_high,
        use_structure_tp=True,
    )

    assert model is not None
    assert model["take_profit"] == 130
    expected_rr = (130 - model["entry_price"]) / (model["entry_price"] - model["stop_loss"])
    assert model["rr"] == expected_rr
    assert model["rr"] != 2.5


def test_build_entry_model_use_structure_tp_extends_to_equilibrium_when_further():
    """When the premium/discount equilibrium reaches FURTHER than the
    previous swing high, it is used instead -- "if structure allows,
    target the 0.5 equilibrium instead" (read here as: whichever
    candidate is more favorable wins).
    """
    previous_swing_high = {"price": 120, "index": 20}
    premium_discount = {"top": 300, "bottom": 50, "equilibrium": 140, "zone": "discount",
                         "range_high_index": 20, "range_low_index": 0}

    model = build_entry_model(
        "bullish",
        _SWEEP,
        None,
        _BULLISH_FVG,
        None,
        previous_swing_high=previous_swing_high,
        premium_discount=premium_discount,
        use_structure_tp=True,
    )

    assert model["take_profit"] == 140


def test_build_entry_model_use_structure_tp_prefers_farther_previous_high_over_nearer_equilibrium():
    """Sanity mirror of the test above: when the previous swing high
    reaches FURTHER than equilibrium, the previous high wins instead --
    proving this is a genuine "most favorable of the two", not just
    "always prefer equilibrium".
    """
    previous_swing_high = {"price": 150, "index": 20}
    premium_discount = {"top": 300, "bottom": 50, "equilibrium": 130, "zone": "discount",
                         "range_high_index": 20, "range_low_index": 0}

    model = build_entry_model(
        "bullish",
        _SWEEP,
        None,
        _BULLISH_FVG,
        None,
        previous_swing_high=previous_swing_high,
        premium_discount=premium_discount,
        use_structure_tp=True,
    )

    assert model["take_profit"] == 150


def test_build_entry_model_use_structure_tp_falls_back_to_fixed_rr_when_no_valid_target():
    """Both previous_swing_high and premium_discount missing (the
    detector found neither) must fall back to the exact fixed-RR target
    -- a missing structure input degrades gracefully, it doesn't reject
    an otherwise-valid entry.
    """
    model = build_entry_model(
        "bullish", _SWEEP, None, _BULLISH_FVG, None, use_structure_tp=True
    )
    baseline = build_entry_model("bullish", _SWEEP, None, _BULLISH_FVG, None)

    assert model["take_profit"] == baseline["take_profit"]
    assert model["rr"] == baseline["rr"] == 2.5


def test_build_entry_model_use_structure_tp_falls_back_when_previous_high_already_behind_price():
    """A previous swing high that's already BELOW the entry price (stale,
    already-passed structure -- not a usable forward target) must be
    treated the same as a missing one: fall back to the fixed-RR target.
    """
    stale_previous_high = {"price": 105, "index": 20}  # below entry_price (110)

    model = build_entry_model(
        "bullish",
        _SWEEP,
        None,
        _BULLISH_FVG,
        None,
        previous_swing_high=stale_previous_high,
        use_structure_tp=True,
    )
    baseline = build_entry_model("bullish", _SWEEP, None, _BULLISH_FVG, None)

    assert model["take_profit"] == baseline["take_profit"]
    assert model["rr"] == 2.5


def test_build_entry_model_use_structure_tp_short_targets_previous_swing_low():
    """Mirror of the long case: a short targets the previous swing low
    (below entry), extended further down to equilibrium if that reaches
    further.
    """
    bearish_fvg = [{"type": "bearish", "top": 100, "bottom": 98, "index": 3}]
    choch = {"type": "bearish_choch", "broken_level": 99, "broken_index": 2, "confirm_index": 4}
    previous_swing_low = {"price": 70, "index": 20}
    premium_discount = {"top": 150, "bottom": 60, "equilibrium": 80, "zone": "premium",
                         "range_high_index": 20, "range_low_index": 0}

    model = build_entry_model(
        "bearish",
        None,
        choch,
        bearish_fvg,
        None,
        previous_swing_low=previous_swing_low,
        premium_discount=premium_discount,
        use_structure_tp=True,
    )

    assert model is not None
    assert model["direction"] == "short"
    # previous_swing_low (70) reaches further down than equilibrium (80).
    assert model["take_profit"] == 70
    expected_rr = (model["entry_price"] - 70) / (model["stop_loss"] - model["entry_price"])
    assert model["rr"] == expected_rr


# --- require_premium_discount_filter (opt-in entry-quality filter, see
# docs/strategy_spec.md section 8) -----------------------------------------


def test_build_entry_model_premium_discount_filter_ignored_by_default():
    """Passing a premium_discount dict without require_premium_discount_
    filter=True must have zero effect -- a long from the premium half is
    still accepted, matching the unfiltered baseline exactly.
    """
    premium_discount = {"top": 200, "bottom": 50, "equilibrium": 125, "zone": "premium",
                         "range_high_index": 20, "range_low_index": 0}

    model = build_entry_model(
        "bullish", _SWEEP, None, _BULLISH_FVG, None, premium_discount=premium_discount
    )
    baseline = build_entry_model("bullish", _SWEEP, None, _BULLISH_FVG, None)

    assert model is not None
    assert model["take_profit"] == baseline["take_profit"]


def test_build_entry_model_premium_discount_filter_rejects_long_from_premium():
    """A long entered while price sits in the PREMIUM half of the range
    must be rejected -- buying the expensive half of the range."""
    premium_discount = {"top": 200, "bottom": 50, "equilibrium": 125, "zone": "premium",
                         "range_high_index": 20, "range_low_index": 0}

    model = build_entry_model(
        "bullish",
        _SWEEP,
        None,
        _BULLISH_FVG,
        None,
        premium_discount=premium_discount,
        require_premium_discount_filter=True,
    )
    assert model is None


def test_build_entry_model_premium_discount_filter_accepts_long_from_discount():
    """A long entered while price sits in the DISCOUNT half of the range
    is exactly the setup this filter is designed to allow -- must still
    produce a valid entry."""
    premium_discount = {"top": 200, "bottom": 50, "equilibrium": 125, "zone": "discount",
                         "range_high_index": 20, "range_low_index": 0}

    model = build_entry_model(
        "bullish",
        _SWEEP,
        None,
        _BULLISH_FVG,
        None,
        premium_discount=premium_discount,
        require_premium_discount_filter=True,
    )
    assert model is not None
    assert model["direction"] == "long"


def test_build_entry_model_premium_discount_filter_rejects_short_from_discount():
    """Mirror case: a short entered from the DISCOUNT half (selling the
    cheap half) must be rejected."""
    bearish_fvg = [{"type": "bearish", "top": 100, "bottom": 98, "index": 3}]
    choch = {"type": "bearish_choch", "broken_level": 99, "broken_index": 2, "confirm_index": 4}
    premium_discount = {"top": 150, "bottom": 60, "equilibrium": 105, "zone": "discount",
                         "range_high_index": 20, "range_low_index": 0}

    model = build_entry_model(
        "bearish",
        None,
        choch,
        bearish_fvg,
        None,
        premium_discount=premium_discount,
        require_premium_discount_filter=True,
    )
    assert model is None


def test_build_entry_model_premium_discount_filter_accepts_short_from_premium():
    bearish_fvg = [{"type": "bearish", "top": 100, "bottom": 98, "index": 3}]
    choch = {"type": "bearish_choch", "broken_level": 99, "broken_index": 2, "confirm_index": 4}
    premium_discount = {"top": 150, "bottom": 60, "equilibrium": 105, "zone": "premium",
                         "range_high_index": 20, "range_low_index": 0}

    model = build_entry_model(
        "bearish",
        None,
        choch,
        bearish_fvg,
        None,
        premium_discount=premium_discount,
        require_premium_discount_filter=True,
    )
    assert model is not None
    assert model["direction"] == "short"


def test_build_entry_model_premium_discount_filter_accepts_either_direction_from_equilibrium():
    """Exactly at equilibrium is neither cheap nor expensive -- must be
    valid for BOTH a long and a short, unlike premium/discount which are
    each valid for only one direction.
    """
    premium_discount = {"top": 200, "bottom": 50, "equilibrium": 125, "zone": "equilibrium",
                         "range_high_index": 20, "range_low_index": 0}

    long_model = build_entry_model(
        "bullish",
        _SWEEP,
        None,
        _BULLISH_FVG,
        None,
        premium_discount=premium_discount,
        require_premium_discount_filter=True,
    )
    assert long_model is not None

    bearish_fvg = [{"type": "bearish", "top": 100, "bottom": 98, "index": 3}]
    choch = {"type": "bearish_choch", "broken_level": 99, "broken_index": 2, "confirm_index": 4}
    short_model = build_entry_model(
        "bearish",
        None,
        choch,
        bearish_fvg,
        None,
        premium_discount=premium_discount,
        require_premium_discount_filter=True,
    )
    assert short_model is not None


def test_build_entry_model_premium_discount_filter_missing_data_does_not_reject():
    """No premium_discount available (detector found no coherent current
    range) must NOT reject an otherwise-valid entry -- same
    missing-input-degrades-gracefully discipline as use_structure_tp.
    """
    model = build_entry_model(
        "bullish", _SWEEP, None, _BULLISH_FVG, None, require_premium_discount_filter=True
    )
    assert model is not None


def test_build_entry_model_premium_discount_filter_independent_of_structure_tp():
    """Both filters can be enabled together: the premium/discount filter
    gates whether an entry is produced at all, use_structure_tp governs
    where its take-profit lands -- combining them must still produce a
    valid entry with a structure-based TP.
    """
    previous_swing_high = {"price": 130, "index": 20}
    premium_discount = {"top": 200, "bottom": 50, "equilibrium": 125, "zone": "discount",
                         "range_high_index": 20, "range_low_index": 0}

    model = build_entry_model(
        "bullish",
        _SWEEP,
        None,
        _BULLISH_FVG,
        None,
        previous_swing_high=previous_swing_high,
        premium_discount=premium_discount,
        use_structure_tp=True,
        require_premium_discount_filter=True,
    )

    assert model is not None
    assert model["take_profit"] == 130
