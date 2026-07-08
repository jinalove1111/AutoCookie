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
