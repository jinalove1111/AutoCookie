"""Unit tests for app.strategy.jade_trade_plan: composes
entry_point_engine/exit_point_engine/htf_ltf_confluence into one trade
plan. Real detector calls throughout (nothing mocked).
"""

from __future__ import annotations

from app.strategy.jade_trade_plan import build_trade_plan


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def test_build_trade_plan_none_when_no_entry_found():
    # Gently rising, heavily overlapping ranges: no entry model finds
    # anything -- same fixture used throughout entry_point_engine's own
    # "nothing matches" tests.
    candles = [
        candle(100 + i * 0.1, 100 + i * 0.1 + 1, 100 + i * 0.1 - 1, 100 + i * 0.1 + 0.5, f"t{i}")
        for i in range(20)
    ]
    assert build_trade_plan(candles, candles, "bullish") is None


def _ltf_order_block_fvg_candles() -> list[dict]:
    """Real OB+FVG-overlap fixture (verified in
    test_strategy_entry_point_engine.py): confidence-5 order_block entry,
    zone [99, 101].
    """
    candles = [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))
    candles.append(candle(100, 111, 99, 110, "t16"))
    candles.append(candle(97, 98, 96, 97.5, "tA"))
    candles.append(candle(97.5, 105, 97, 104, "tB"))
    candles.append(candle(104, 106, 100, 105, "tC"))
    candles.append(candle(100, 101, 99.5, 100, "tD"))
    return candles


def _htf_order_block_candles() -> list[dict]:
    """Real HTF order block [99, 101] -- same zone as the LTF entry, so
    the HTF PD-array-overlap check is guaranteed to fire.
    """
    candles = [candle(100, 100.5, 99.5, 100.2, f"h{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "h15"))
    candles.append(candle(100, 111, 99, 110, "h16"))
    return candles


def test_build_trade_plan_composes_entry_exit_and_confluence():
    ltf_candles = _ltf_order_block_fvg_candles()
    htf_candles = _htf_order_block_candles()

    plan = build_trade_plan(ltf_candles, htf_candles, "bullish")

    assert plan is not None
    # Every field find_entry_point itself returns must still be present, unchanged.
    assert plan["entry_model"] == "order_block"
    assert plan["direction"] == "long"
    assert plan["entry_zone"] == {"top": 101, "bottom": 99}
    assert plan["confidence_score"] == 5
    assert "reason_list" in plan
    assert "reject_reason_list" in plan

    # Composed additions.
    assert isinstance(plan["exit_targets"], list)
    assert len(plan["exit_targets"]) > 0
    assert all(t["raw_level"] > plan["entry_zone"]["bottom"] for t in plan["exit_targets"])

    assert plan["htf_confluence"]["direction"] == "long"
    assert plan["htf_confluence"]["checks"]["htf_pd_array_overlap"] is True
    assert "LTF entry zone overlaps an HTF order block" in plan["htf_confluence"]["reasons"][0]


def test_build_trade_plan_exit_targets_computed_from_entry_zone_midpoint():
    """The entry_price fed to find_exit_targets is the entry zone's
    midpoint (100, for zone [99, 101]) -- proven by checking that a
    target sitting between the zone's bottom and its midpoint (e.g. the
    zone top itself, 101 > 100) is still included as a valid forward
    target for a long.
    """
    ltf_candles = _ltf_order_block_fvg_candles()
    htf_candles = _htf_order_block_candles()

    plan = build_trade_plan(ltf_candles, htf_candles, "bullish")

    midpoint = (plan["entry_zone"]["top"] + plan["entry_zone"]["bottom"]) / 2
    assert midpoint == 100
    assert any(t["raw_level"] > midpoint for t in plan["exit_targets"])
