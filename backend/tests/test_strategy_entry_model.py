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
    assert model["rr"] == 2.0
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
