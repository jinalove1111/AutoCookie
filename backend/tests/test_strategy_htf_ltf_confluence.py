"""Unit tests for app.strategy.htf_ltf_confluence: HTF confirmation
scoring for an LTF entry candidate. Real detector calls throughout
(nothing mocked), same discipline as entry_point_engine/exit_point_engine.
"""

from __future__ import annotations

import pytest

from app.strategy.htf_ltf_confluence import evaluate_htf_ltf_confluence


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def _no_structure_candles() -> list[dict]:
    # Gently rising, heavily overlapping ranges: no swing points ever
    # confirm, no FVG, no order block -- see the identical pattern used
    # in test_strategy_entry_point_engine.py's "nothing matches" fixture.
    return [
        candle(100 + i * 0.1, 100 + i * 0.1 + 1, 100 + i * 0.1 - 1, 100 + i * 0.1 + 0.5, f"t{i}")
        for i in range(20)
    ]


def test_invalid_direction_raises():
    with pytest.raises(ValueError):
        evaluate_htf_ltf_confluence("up", {"top": 101, "bottom": 99}, _no_structure_candles())


def test_all_checks_false_when_htf_has_no_structure():
    result = evaluate_htf_ltf_confluence("long", {"top": 101, "bottom": 99}, _no_structure_candles())

    assert result["confluence_score"] == 0
    assert result["checks"] == {
        "htf_premium_discount_alignment": False,
        "htf_pd_array_overlap": False,
        "htf_liquidity_draw": False,
    }
    assert result["reasons"] == []


# --- htf_premium_discount_alignment -----------------------------------


def _pd_range_candles(last_close: float) -> list[dict]:
    """Same verified shape used in test_strategy_entry_point_engine.py:
    top=30, bottom=5, equilibrium=17.5.
    """
    highs = [10, 11, 20, 15, 12, 14, 18, 20, 25, 27, 30, 20, 18, 16]
    lows = [8, 9, 15, 11, 5, 9, 14, 16, 20, 22, 22, 15, 13, 12]
    candles = [candle(l, h, l, l, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]
    candles[-1] = candle(last_close, highs[-1], lows[-1], last_close, "t_last")
    return candles


def test_premium_discount_alignment_true_for_long_from_htf_discount():
    result = evaluate_htf_ltf_confluence("long", {"top": 6, "bottom": 5.5}, _pd_range_candles(10.0))
    assert result["checks"]["htf_premium_discount_alignment"] is True
    assert any("aligned with a long" in r for r in result["reasons"])


def test_premium_discount_alignment_false_for_long_from_htf_premium():
    result = evaluate_htf_ltf_confluence("long", {"top": 6, "bottom": 5.5}, _pd_range_candles(25.0))
    assert result["checks"]["htf_premium_discount_alignment"] is False


def test_premium_discount_alignment_true_for_short_from_htf_premium():
    result = evaluate_htf_ltf_confluence("short", {"top": 30, "bottom": 29}, _pd_range_candles(25.0))
    assert result["checks"]["htf_premium_discount_alignment"] is True


# --- htf_pd_array_overlap ------------------------------------------------


def _htf_order_block_candles() -> list[dict]:
    """Same proven shape used throughout this session: bullish OB
    [99, 101] confirmed by a strong impulse.
    """
    candles = [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))
    candles.append(candle(100, 111, 99, 110, "t16"))
    return candles


def test_pd_array_overlap_true_when_ltf_zone_overlaps_htf_order_block():
    result = evaluate_htf_ltf_confluence(
        "long", {"top": 100, "bottom": 99.5}, _htf_order_block_candles()
    )
    assert result["checks"]["htf_pd_array_overlap"] is True
    assert any("HTF order block" in r for r in result["reasons"])


def test_pd_array_overlap_false_when_ltf_zone_does_not_overlap():
    result = evaluate_htf_ltf_confluence(
        "long", {"top": 200, "bottom": 190}, _htf_order_block_candles()
    )
    assert result["checks"]["htf_pd_array_overlap"] is False


def test_pd_array_overlap_false_on_direction_mismatched_htf_order_block():
    """A bullish HTF order block must not count as confluence for a
    short, even if the LTF zone overlaps its price range."""
    result = evaluate_htf_ltf_confluence(
        "short", {"top": 100, "bottom": 99.5}, _htf_order_block_candles()
    )
    assert result["checks"]["htf_pd_array_overlap"] is False


def test_pd_array_overlap_true_via_htf_fvg():
    candles = [
        candle(9, 10, 8, 9.5, "t0"),
        candle(12, 20, 11, 19, "t1"),
        candle(19, 22, 15, 21, "t2"),  # bullish FVG [10, 15] against t0
    ]
    result = evaluate_htf_ltf_confluence("long", {"top": 13, "bottom": 11}, candles)
    assert result["checks"]["htf_pd_array_overlap"] is True
    assert any("HTF FVG" in r for r in result["reasons"])


# --- htf_liquidity_draw ---------------------------------------------------


def test_liquidity_draw_true_when_htf_previous_swing_high_exists_beyond_entry():
    candles = _htf_order_block_candles()  # has real swing structure via its impulse
    result = evaluate_htf_ltf_confluence("long", {"top": 100, "bottom": 99.5}, candles)
    assert result["checks"]["htf_liquidity_draw"] is True
    assert any("HTF liquidity draw exists" in r for r in result["reasons"])


def test_liquidity_draw_false_when_entry_already_beyond_all_htf_targets():
    candles = _htf_order_block_candles()
    result = evaluate_htf_ltf_confluence("long", {"top": 500, "bottom": 499}, candles)
    assert result["checks"]["htf_liquidity_draw"] is False


# --- full confluence -------------------------------------------------------


def test_full_confluence_score_of_three_when_all_checks_pass():
    """A single fixture engineered so all 3 checks pass: a real HTF
    order block (also the source of a real swing high beyond entry,
    satisfying the liquidity-draw check) sitting in the HTF discount
    half of the range for a long.
    """
    candles = _htf_order_block_candles()
    entry_zone = {"top": 100, "bottom": 99.5}  # overlaps the OB [99, 101]

    result = evaluate_htf_ltf_confluence("long", entry_zone, candles)

    assert result["confluence_score"] == sum(result["checks"].values())
    assert result["checks"]["htf_pd_array_overlap"] is True
    assert result["checks"]["htf_liquidity_draw"] is True
    assert len(result["reasons"]) == result["confluence_score"]
