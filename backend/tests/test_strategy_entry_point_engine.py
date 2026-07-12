"""Unit tests for app.strategy.entry_point_engine: the Jade Entry Point
Engine (official specification, operator directive 2026-07-12) -- 5
entry models plus the `find_entry_point` orchestrator. Real detector
calls throughout (nothing mocked), same discipline as every other
strategy test in this package.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.strategy.entry_point_engine import (
    _displacement_strength,
    _evaluate_breaker_block,
    _evaluate_fair_value_gap,
    _evaluate_liquidity_raid,
    _evaluate_order_block,
    _evaluate_premium_discount,
    find_entry_point,
)
from app.strategy.fvg import detect_fair_value_gap
from app.strategy.market_structure import detect_choch_mss
from app.strategy.premium_discount import calculate_premium_discount
from app.strategy.utils import is_zone_mitigated


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


# --- Entry Model 1: Premium / Discount -------------------------------------


def _pd_range_candles(last_close: float) -> list[dict]:
    """Same verified shape as test_strategy_premium_discount.py: swing
    highs [2, 10] -> top=30 (idx10); swing lows [4] -> bottom=5 (idx4).
    Range [5, 30], equilibrium 17.5.
    """
    highs = [10, 11, 20, 15, 12, 14, 18, 20, 25, 27, 30, 20, 18, 16]
    lows = [8, 9, 15, 11, 5, 9, 14, 16, 20, 22, 22, 15, 13, 12]
    candles = [candle(l, h, l, l, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]
    candles[-1] = candle(last_close, highs[-1], lows[-1], last_close, "t_last")
    return candles


def test_premium_discount_none_on_neutral_bias():
    result, reason = _evaluate_premium_discount(_pd_range_candles(10.0), "neutral")
    assert result is None
    assert reason is not None


def test_premium_discount_none_without_coherent_range():
    candles = [candle(10, 11, 9, 10, f"t{i}") for i in range(4)]
    result, reason = _evaluate_premium_discount(candles, "bullish")
    assert result is None


def test_premium_discount_long_entry_zone_is_discount_half():
    candles = _pd_range_candles(10.0)
    pd = calculate_premium_discount(candles)
    assert pd == {
        "top": 30, "bottom": 5, "equilibrium": 17.5, "zone": "discount",
        "range_high_index": 10, "range_low_index": 4,
    }

    result, reject_reason = _evaluate_premium_discount(candles, "bullish")

    assert reject_reason is None
    assert result["entry_model"] == "premium_discount"
    assert result["direction"] == "long"
    assert result["entry_zone"] == {"top": 17.5, "bottom": 5}
    assert result["stop_loss"] < 5
    assert result["invalidation_level"] == result["stop_loss"]
    assert result["confidence_score"] == 4


def test_premium_discount_short_entry_zone_is_premium_half():
    candles = _pd_range_candles(25.0)

    result, reject_reason = _evaluate_premium_discount(candles, "bearish")

    assert reject_reason is None
    assert result["direction"] == "short"
    assert result["entry_zone"] == {"top": 30, "bottom": 17.5}
    assert result["stop_loss"] > 30


def test_premium_discount_falls_back_reason_when_no_displacement_qualifies():
    """`_pd_range_candles` has no big impulse, no FVG, no CHOCH anywhere
    -- none of the 5 displacement criteria are ever satisfied. The
    result must say so explicitly and use the unmodified
    calculate_premium_discount range (already covered by the exact-value
    assertions in the two tests above; this test asserts the REASON
    text specifically).
    """
    result, _ = _evaluate_premium_discount(_pd_range_candles(10.0), "bullish")
    assert result["reasons"][-1] == (
        "no displacement-qualified range found; used most recent confirmed swing range"
    )


def _displacement_zigzag_candles() -> list[dict]:
    """Downtrend zigzag (verified: 2 confirmed swing highs [30, 25, 20]
    at indices 2/6/10, 2 confirmed swing lows [6, 3] at indices 4/8) --
    same proven shape used elsewhere in this package for a real
    bullish_choch -- followed by a genuine displacement leg: a large,
    strong-bodied bullish impulse (t13, range 14, body 12 -- both far
    exceeding the recent average range) that closes back above the most
    recent swing high (20), confirming a real bullish CHOCH, and leaves
    a real bullish FVG against its neighbors. Two confirming candles
    (t14/t15, lower highs) let t13 itself confirm as a fresh swing high.
    """
    highs = [10, 11, 30, 11, 9, 11, 25, 11, 9, 11, 20, 11, 9]
    lows = [8, 9, 15, 9, 6, 9, 18, 9, 3, 9, 22, 11, 12]
    candles = [
        candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))
    ]
    candles.append(candle(10, 23, 9, 22, "t13"))  # displacement impulse
    candles.append(candle(21, 22, 20, 21, "t14"))
    candles.append(candle(20, 21, 19, 20, "t15"))
    return candles


def test_displacement_strength_qualifies_a_real_displacement_move():
    candles = _displacement_zigzag_candles()

    # Premise: this move satisfies all 5 criteria for real.
    move = candles[8:14]
    assert any(z["type"] == "bullish" for z in detect_fair_value_gap(move))
    choch = detect_choch_mss(candles[:14])
    assert choch == {
        "type": "bullish_choch", "broken_level": 20, "broken_index": 10, "confirm_index": 13,
    }

    score = _displacement_strength(candles, 8, 13, "long")
    assert score is not None and score > 0


def test_premium_discount_prefers_strongest_of_multiple_qualifying_candidates():
    """Two genuinely different candidate ranges both qualify here
    ((4, 13) and (8, 13), confirmed directly below) -- the STRONGER one,
    (8, 13), must be preferred, and both must beat the naive
    calculate_premium_discount fallback (which degenerately pairs the
    most recent swing high AND most recent swing low at the SAME candle,
    t13, since t13 registers as both).
    """
    candles = _displacement_zigzag_candles()

    score_weaker = _displacement_strength(candles, 4, 13, "long")
    score_stronger = _displacement_strength(candles, 8, 13, "long")
    assert score_weaker is not None and score_stronger is not None
    assert score_stronger > score_weaker

    fallback = calculate_premium_discount(candles)
    assert fallback["bottom"] == 9  # t13's own low -- the degenerate naive pairing

    result, reject_reason = _evaluate_premium_discount(candles, "bullish")

    assert reject_reason is None
    assert result["reasons"][-1] == "range selected by strongest qualifying displacement move"
    # bottom=3 (candle 8's low) -- the (8, 13) range, not (4, 13)'s bottom=6
    # or the naive fallback's bottom=9.
    assert result["entry_zone"]["bottom"] == 3


# --- Entry Model 2: Liquidity Raid (Turtle Soup) ----------------------------


def _equal_lows_base_candles() -> list[dict]:
    lows = [9, 9, 5.00, 9, 9, 9, 9, 5.003, 9, 9]
    return [candle(9, 10, low, 9.5, f"t{i}") for i, low in enumerate(lows)]


def _equal_highs_base_candles() -> list[dict]:
    highs = [10, 10, 15.00, 10, 10, 10, 10, 15.01, 10, 10]
    return [candle(9, high, 9, 9.5, f"h{i}") for i, high in enumerate(highs)]


def test_liquidity_raid_none_on_neutral_bias():
    result, _ = _evaluate_liquidity_raid(_equal_lows_base_candles(), "neutral")
    assert result is None


def test_liquidity_raid_none_without_confirmed_sweep():
    candles = _equal_lows_base_candles() + [candle(9, 10, 9, 9.5, "t10")]
    result, reason = _evaluate_liquidity_raid(candles, "bullish")
    assert result is None
    assert "no confirmed" in reason


def test_liquidity_raid_none_on_sweep_without_close_back_inside():
    """A liquidity sweep alone -- wicks below 5.00 but closes BELOW it
    too (no reclaim) -- must NEVER be an entry, per spec.
    """
    candles = _equal_lows_base_candles() + [candle(6, 6.5, 4.5, 4.8, "t10")]
    result, reason = _evaluate_liquidity_raid(candles, "bullish")
    assert result is None


def test_liquidity_raid_long_on_equal_lows_swept_and_reclaimed():
    candles = _equal_lows_base_candles() + [candle(6, 6.5, 4.5, 5.5, "t10")]

    result, reject_reason = _evaluate_liquidity_raid(candles, "bullish")

    assert reject_reason is None
    assert result["entry_model"] == "liquidity_raid"
    assert result["direction"] == "long"
    assert result["entry_zone"] == {"top": 5.0, "bottom": 4.5}
    assert result["stop_loss"] < 4.5
    assert result["confidence_score"] == 4


def test_liquidity_raid_short_on_equal_highs_swept_and_reclaimed():
    candles = _equal_highs_base_candles() + [candle(14, 16, 13, 13.5, "h10")]

    result, reject_reason = _evaluate_liquidity_raid(candles, "bearish")

    assert reject_reason is None
    assert result["direction"] == "short"
    assert result["entry_zone"] == {"top": 16, "bottom": 15.01}
    assert result["stop_loss"] > 16


def test_liquidity_raid_target_reference_matches_premium_discount_range():
    candles = _equal_lows_base_candles() + [candle(6, 6.5, 4.5, 5.5, "t10")]
    result, _ = _evaluate_liquidity_raid(candles, "bullish")

    pd = calculate_premium_discount(candles)
    expected = pd["top"] if pd is not None else None
    assert result["target_reference"] == expected


# --- Liquidity Raid: real session/day/week sources (session_liquidity.py,
# ENGINEERING_DECISIONS.md #27) -- these need real `datetime` timestamps,
# unlike every fixture above, which uses plain strings -----------------


def test_liquidity_raid_long_on_previous_daily_low_swept_and_reclaimed():
    candles = [
        candle(95, 100, 90, 95, datetime(2026, 1, 13, 10, tzinfo=timezone.utc)),  # previous day, low=90
        candle(96, 101, 92, 96, datetime(2026, 1, 13, 14, tzinfo=timezone.utc)),
        candle(97, 102, 95, 97, datetime(2026, 1, 14, 10, tzinfo=timezone.utc)),  # today so far
        candle(96, 98, 88, 96, datetime(2026, 1, 14, 12, tzinfo=timezone.utc)),   # sweeps below 90, reclaims
    ]

    result, reject_reason = _evaluate_liquidity_raid(candles, "bullish")

    assert reject_reason is None
    assert result["direction"] == "long"
    assert result["entry_zone"] == {"top": 90, "bottom": 88}
    assert result["reasons"] == ["previous_daily_low liquidity swept at 90, closed back inside the range"]


def test_liquidity_raid_short_on_previous_weekly_high_swept_and_reclaimed():
    candles = [
        # ISO week Mon 2026-01-12 - Sun 2026-01-18 (the immediately preceding week).
        candle(100, 120, 95, 100, datetime(2026, 1, 14, 10, tzinfo=timezone.utc)),
        candle(100, 110, 95, 100, datetime(2026, 1, 16, 10, tzinfo=timezone.utc)),
        # ISO week Mon 2026-01-19 - Sun 2026-01-25 ("now").
        candle(100, 105, 95, 100, datetime(2026, 1, 20, 10, tzinfo=timezone.utc)),
        candle(100, 125, 95, 96, datetime(2026, 1, 20, 12, tzinfo=timezone.utc)),  # sweeps above 120, reclaims
    ]

    result, reject_reason = _evaluate_liquidity_raid(candles, "bearish")

    assert reject_reason is None
    assert result["direction"] == "short"
    assert result["entry_zone"] == {"top": 125, "bottom": 120}
    assert result["reasons"] == ["previous_weekly_high liquidity swept at 120, closed back inside the range"]


def test_liquidity_raid_string_timestamps_degrade_gracefully_to_equal_lows():
    """Every OTHER liquidity-raid test in this file uses plain string
    timestamps (`"t0"`, etc.) -- session_liquidity's 5 sources can't
    parse those as real dates, so they must be silently skipped (not
    raise), falling through to Equal Lows exactly as this model behaved
    before session_liquidity was wired in.
    """
    candles = _equal_lows_base_candles() + [candle(6, 6.5, 4.5, 5.5, "t10")]

    result, reject_reason = _evaluate_liquidity_raid(candles, "bullish")

    assert reject_reason is None
    assert result["reasons"] == ["equal_lows liquidity swept at 5.0, closed back inside the range"]


# --- Entry Model 3: Fair Value Gap -------------------------------------


def _fvg_bullish_candles(retest_high: float = 14, retest_low: float = 12) -> list[dict]:
    """Bullish FVG [10, 15] (index=1, the impulse candle), with distinct
    aggressive (10, zone boundary) / moderate (11, impulse candle low) /
    conservative (8, first candle low) stop levels.
    """
    return [
        candle(9, 10, 8, 9.5, "t0"),
        candle(12, 20, 11, 19, "t1"),
        candle(19, 22, 15, 21, "t2"),
        candle(13, retest_high, retest_low, 12.5, "t3"),
    ]


def test_fvg_none_on_neutral_bias():
    result, _ = _evaluate_fair_value_gap(_fvg_bullish_candles(), "neutral")
    assert result is None


def test_fvg_none_without_matching_gap():
    candles = [candle(10, 11, 9, 10, f"t{i}") for i in range(5)]
    result, reason = _evaluate_fair_value_gap(candles, "bullish")
    assert result is None


def test_fvg_none_when_not_currently_retesting():
    candles = _fvg_bullish_candles(retest_high=21, retest_low=19)  # well above the gap
    result, reason = _evaluate_fair_value_gap(candles, "bullish")
    assert result is None
    assert "not" in reason or "no matching" in reason


def test_fvg_invalid_stop_model_raises():
    import pytest

    with pytest.raises(ValueError):
        _evaluate_fair_value_gap(_fvg_bullish_candles(), "bullish", stop_model="middle")


def test_fvg_long_entry_aggressive_moderate_conservative_stops():
    candles = _fvg_bullish_candles()

    aggressive, _ = _evaluate_fair_value_gap(candles, "bullish", stop_model="aggressive")
    moderate, _ = _evaluate_fair_value_gap(candles, "bullish", stop_model="moderate")
    conservative, _ = _evaluate_fair_value_gap(candles, "bullish", stop_model="conservative")

    assert aggressive["entry_zone"] == {"top": 15, "bottom": 10}
    # aggressive = gap boundary (10), moderate = impulse candle low (11),
    # conservative = first candle low (8) -- all buffered slightly below.
    assert aggressive["stop_loss"] < 10
    assert moderate["stop_loss"] < 11
    assert conservative["stop_loss"] < 8
    # invalidation_level is ALWAYS the conservative level, regardless of stop_model.
    assert aggressive["invalidation_level"] == conservative["invalidation_level"] == moderate["invalidation_level"]


def test_fvg_repeated_test_does_not_invalidate_setup():
    """Spec-mandated divergence from SignalEngine: this exact zone WOULD
    be excluded under SignalEngine's mitigation filter (confirmed
    directly below), but must still produce a valid entry here.
    """
    candles = [
        candle(9, 10, 8, 9.5, "t0"),
        candle(12, 20, 11, 19, "t1"),
        candle(19, 22, 15, 21, "t2"),
        candle(13, 14, 12, 13, "t2b"),  # an EARLIER retest of the zone
        candle(13, 14, 12, 12.5, "t3"),  # retest AGAIN -- last candle
    ]
    zone = [z for z in detect_fair_value_gap(candles) if z["type"] == "bullish"][0]
    assert is_zone_mitigated(candles, zone["index"] + 2, zone["top"], zone["bottom"]) is True

    result, reject_reason = _evaluate_fair_value_gap(candles, "bullish")

    assert reject_reason is None
    assert result["entry_zone"] == {"top": 15, "bottom": 10}


def test_fvg_short_mirror():
    bearish_candles = [
        candle(9, 10, 8, 9.5, "t0"),
        candle(8, 9, 0, 1, "t1"),
        candle(1, 5, 0, 2, "t2"),
        candle(6, 7, 5.5, 6.5, "t3"),  # retests the zone [5, 8]
    ]
    # prev_low(8) > next_high(5) -> bearish FVG[8,5], index=1
    result, reject_reason = _evaluate_fair_value_gap(bearish_candles, "bearish")
    assert reject_reason is None
    assert result["direction"] == "short"
    assert result["entry_zone"] == {"top": 8, "bottom": 5}
    assert result["stop_loss"] > 8


# --- Entry Model 4: Order Block ---------------------------------------


def _order_block_bullish_candles(retrace_high=101, retrace_low=99) -> list[dict]:
    candles = [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))  # bearish base -> bullish OB [99,101]
    candles.append(candle(100, 111, 99, 110, "t16"))  # bullish impulse confirms OB
    candles.append(candle(100, retrace_high, retrace_low, 100, "t17"))
    return candles


def test_order_block_none_on_neutral_bias():
    result, _ = _evaluate_order_block(_order_block_bullish_candles(), "neutral")
    assert result is None


def test_order_block_none_without_matching_ob():
    candles = [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(20)]
    result, reason = _evaluate_order_block(candles, "bullish")
    assert result is None
    assert reason == "no matching order block"


def test_order_block_none_when_not_retraced_into_zone():
    candles = _order_block_bullish_candles(retrace_high=115, retrace_low=112)
    result, reason = _evaluate_order_block(candles, "bullish")
    assert result is None
    assert "retraced" in reason


def test_order_block_confidence_3_without_fvg_overlap():
    candles = _order_block_bullish_candles()

    result, reject_reason = _evaluate_order_block(candles, "bullish")

    assert reject_reason is None
    assert result["entry_model"] == "order_block"
    assert result["entry_zone"] == {"top": 101, "bottom": 99}
    assert result["stop_loss"] < 99
    assert result["confidence_score"] == 3


def test_order_block_confidence_5_with_fvg_overlap():
    candles = [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))
    candles.append(candle(100, 111, 99, 110, "t16"))
    candles.append(candle(97, 98, 96, 97.5, "tA"))    # fvg prev, high=98
    candles.append(candle(97.5, 105, 97, 104, "tB"))  # fvg middle
    candles.append(candle(104, 106, 100, 105, "tC"))  # fvg next, low=100 -> bullish FVG[98,100]
    candles.append(candle(100, 101, 99.5, 100, "tD"))  # retrace into OB[99,101]

    result, reject_reason = _evaluate_order_block(candles, "bullish")

    assert reject_reason is None
    assert result["confidence_score"] == 5
    assert "overlaps a matching FVG" in result["reasons"][-1]


# --- Entry Model 5: Breaker Block ---------------------------------------


def _breaker_bearish_candles(retrace_high=100.5, retrace_low=99.5) -> list[dict]:
    candles = [candle(100, 101, 100, 100.5, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))
    candles.append(candle(100, 111, 99, 110, "t16"))
    candles.append(candle(99.4, 99.5, 98.5, 98.6, "t17"))
    candles.append(candle(98.6, 99.3, 98.5, 99.2, "t18"))  # retest confirms bearish breaker [99,101]
    candles.append(candle(99.5, retrace_high, retrace_low, 100, "t19"))
    return candles


def test_breaker_none_on_neutral_bias():
    result, _ = _evaluate_breaker_block(_breaker_bearish_candles(), "neutral")
    assert result is None


def test_breaker_none_without_matching_breaker():
    candles = [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(20)]
    result, reason = _evaluate_breaker_block(candles, "bearish")
    assert result is None
    assert reason == "no matching breaker block"


def test_breaker_none_when_not_retraced():
    candles = _breaker_bearish_candles(retrace_high=95, retrace_low=93)
    result, reason = _evaluate_breaker_block(candles, "bearish")
    assert result is None
    assert "retraced" in reason


def test_breaker_invalid_stop_model_raises():
    import pytest

    with pytest.raises(ValueError):
        _evaluate_breaker_block(_breaker_bearish_candles(), "bearish", stop_model="moderate")


def test_breaker_confidence_4_without_fvg_overlap():
    candles = _breaker_bearish_candles()

    result, reject_reason = _evaluate_breaker_block(candles, "bearish")

    assert reject_reason is None
    assert result["entry_model"] == "breaker_block"
    assert result["direction"] == "short"
    assert result["entry_zone"] == {"top": 101, "bottom": 99}
    assert result["confidence_score"] == 4


def test_breaker_confidence_5_with_fvg_overlap_and_breathing_room():
    candles = [candle(100, 101, 100, 100.5, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))
    candles.append(candle(100, 111, 99, 110, "t16"))
    candles.append(candle(99.4, 99.5, 98.5, 98.6, "t17"))
    candles.append(candle(98.6, 99.3, 98.5, 99.2, "t18"))
    candles.append(candle(102, 102.3, 102, 102.2, "tX"))    # fvg prev, low=102
    candles.append(candle(101, 101.5, 100, 100.5, "tY"))    # fvg middle
    candles.append(candle(100, 100.5, 99.5, 99.8, "tZ"))    # fvg next (high=100.5) + retrace

    aggressive, reject_reason = _evaluate_breaker_block(candles, "bearish", stop_model="aggressive")
    conservative, _ = _evaluate_breaker_block(candles, "bearish", stop_model="conservative")

    assert reject_reason is None
    assert aggressive["confidence_score"] == 5
    assert "breathing room" in aggressive["reasons"][-1]
    # aggressive stop uses the breaker's own top (101); conservative extends
    # to the overlapping FVG's far edge (102) -- genuinely more room, not
    # just a relabeling of the same value.
    assert aggressive["entry_zone"]["top"] == 101 or conservative["entry_zone"]["top"] == 102
    assert conservative["stop_loss"] > aggressive["stop_loss"]


# --- find_entry_point orchestrator ---------------------------------------


def test_find_entry_point_none_when_nothing_matches():
    # Gently rising, heavily overlapping ranges: no swing highs/lows ever
    # confirm (strictly increasing), no FVG (no gaps between candles), no
    # order block (constant range never exceeds the impulse threshold) --
    # genuinely nothing for any of the 5 models to find.
    candles = [
        candle(100 + i * 0.1, 100 + i * 0.1 + 1, 100 + i * 0.1 - 1, 100 + i * 0.1 + 0.5, f"t{i}")
        for i in range(20)
    ]
    assert find_entry_point(candles, "bullish") is None


def test_find_entry_point_picks_highest_confidence_candidate():
    """A fixture with a real Order Block + overlapping FVG (confidence 5)
    -- the highest possible tier -- must be the chosen result.
    """
    candles = [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))
    candles.append(candle(100, 111, 99, 110, "t16"))
    candles.append(candle(97, 98, 96, 97.5, "tA"))
    candles.append(candle(97.5, 105, 97, 104, "tB"))
    candles.append(candle(104, 106, 100, 105, "tC"))
    candles.append(candle(100, 101, 99.5, 100, "tD"))

    result = find_entry_point(candles, "bullish")

    assert result is not None
    assert result["entry_model"] == "order_block"
    assert result["confidence_score"] == 5
    assert "reason_list" in result
    assert "reject_reason_list" in result
    assert any("fair_value_gap" in r for r in result["reject_reason_list"])


def test_find_entry_point_reject_reason_list_documents_every_other_model():
    """Structural invariant: regardless of which models matched or not,
    exactly 4 of the 5 evaluators end up in reject_reason_list (every
    evaluator except whichever one was chosen as `best`) -- reuses the
    same real OB+FVG fixture as the "picks highest confidence" test
    above.
    """
    candles = [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))
    candles.append(candle(100, 111, 99, 110, "t16"))
    candles.append(candle(97, 98, 96, 97.5, "tA"))
    candles.append(candle(97.5, 105, 97, 104, "tB"))
    candles.append(candle(104, 106, 100, 105, "tC"))
    candles.append(candle(100, 101, 99.5, 100, "tD"))

    result = find_entry_point(candles, "bullish")

    assert result is not None
    assert len(result["reject_reason_list"]) == 4
