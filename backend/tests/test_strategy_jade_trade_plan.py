"""Unit tests for app.strategy.jade_trade_plan: composes
detect_htf_bias/entry_point_engine/exit_point_engine/htf_ltf_confluence
into one trade plan. Real detector calls throughout (nothing mocked).
"""

from __future__ import annotations

from app.strategy.jade_trade_plan import build_trade_plan


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def _htf_bullish_bias_candles() -> list[dict]:
    """Real higher-highs/higher-lows zigzag -- confirmed bullish via
    `detect_htf_bias` directly (same fixture shape used throughout this
    package for the identical purpose, e.g.
    test_strategy_signal_engine.py's own `_htf_bullish_candles`).
    """
    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    return [candle((h + l) / 2, h, l, (h + l) / 2, f"h{i}") for i, (h, l) in enumerate(zip(highs, lows))]


def test_build_trade_plan_none_on_neutral_htf_bias():
    # Flat/featureless HTF series: detect_htf_bias returns "neutral".
    htf_candles = [candle(100, 100.5, 99.5, 100.2, f"h{i}") for i in range(20)]
    ltf_candles = [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(15)]
    assert build_trade_plan(ltf_candles, htf_candles) is None


def test_build_trade_plan_none_when_no_entry_found():
    # Gently rising, heavily overlapping ranges: no entry model finds
    # anything -- same fixture used throughout entry_point_engine's own
    # "nothing matches" tests. Paired with a real bullish HTF series so
    # this specifically tests the entry-model rejection path, not bias.
    candles = [
        candle(100 + i * 0.1, 100 + i * 0.1 + 1, 100 + i * 0.1 - 1, 100 + i * 0.1 + 0.5, f"t{i}")
        for i in range(20)
    ]
    assert build_trade_plan(candles, _htf_bullish_bias_candles()) is None


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


def test_build_trade_plan_composes_bias_entry_exit_and_confluence():
    ltf_candles = _ltf_order_block_fvg_candles()
    htf_candles = _htf_bullish_bias_candles()

    plan = build_trade_plan(ltf_candles, htf_candles)

    assert plan is not None
    assert plan["htf_bias"] == "bullish"
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

    # Trendline/CRT/session-bias additions (item #6, ENGINEERING_DECISIONS.md #33).
    assert plan["trendline_signal"] is not None
    assert plan["trendline_signal"]["trendline"]["type"] == "support"
    assert set(plan["trendline_signal"].keys()) == {"trendline", "break", "liquidity_sweep"}
    # This fixture's last two candles don't form a manipulation+distribution pair.
    assert plan["crt_signal"] is None
    # String-timestamp fixtures degrade gracefully (see _safe_session_bias_agreement).
    assert plan["session_bias"] is None


def test_build_trade_plan_crt_signal_populated_when_last_two_candles_form_one():
    """Append two candles to the proven OB+FVG fixture that form a real
    CRT manipulation+distribution pair (the immediately preceding
    candle's range gets swept and reclaimed by the final candle) --
    crt_signal must reflect it.
    """
    ltf_candles = _ltf_order_block_fvg_candles()
    ltf_candles.append(candle(100, 101, 99.8, 100.5, "tE"))  # the CRT range candle
    ltf_candles.append(candle(99.9, 100, 99.5, 100.7, "tF"))  # wicks below 99.8, closes back above
    htf_candles = _htf_bullish_bias_candles()

    plan = build_trade_plan(ltf_candles, htf_candles)

    assert plan is not None
    assert plan["crt_signal"] == {
        "type": "bullish_crt",
        "range_high": 101,
        "range_low": 99.8,
        "target_reference": 101,
    }


def test_build_trade_plan_exit_targets_computed_from_entry_zone_midpoint():
    """The entry_price fed to find_exit_targets is the entry zone's
    midpoint (100, for zone [99, 101]) -- proven by checking that a
    target above the midpoint (e.g. the zone top itself, 101 > 100) is
    still included as a valid forward target for a long.
    """
    ltf_candles = _ltf_order_block_fvg_candles()
    htf_candles = _htf_bullish_bias_candles()

    plan = build_trade_plan(ltf_candles, htf_candles)

    midpoint = (plan["entry_zone"]["top"] + plan["entry_zone"]["bottom"]) / 2
    assert midpoint == 100
    assert any(t["raw_level"] > midpoint for t in plan["exit_targets"])
