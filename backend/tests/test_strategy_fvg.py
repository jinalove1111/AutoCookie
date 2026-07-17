"""Unit tests for app.strategy.fvg: 3-candle imbalance (fair value gap)
detection, against hand-constructed candle triples with a known,
unambiguous gap (or overlap, for the no-gap case).
"""

from __future__ import annotations

import random

from app.strategy.fvg import detect_fair_value_gap, find_latest_unmitigated_fvg_zone
from app.strategy.utils import is_zone_mitigated


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def test_detect_fair_value_gap_bullish_clear_gap():
    # candle[0].high (11) < candle[2].low (13) -> a bullish FVG zone
    # bounded by [11, 13], attributed to the middle (impulse) candle.
    candles = [
        candle(10, 11, 9, 10, "t0"),
        candle(10, 15, 10, 14, "t1"),
        candle(14, 16, 13, 15, "t2"),
    ]

    zones = detect_fair_value_gap(candles)

    assert zones == [{"type": "bullish", "top": 13, "bottom": 11, "index": 1}]


def test_detect_fair_value_gap_bearish_clear_gap():
    # candle[0].low (14) > candle[2].high (11) -> a bearish FVG zone
    # bounded by [11, 14].
    candles = [
        candle(15, 16, 14, 15, "t0"),
        candle(15, 15, 9, 10, "t1"),
        candle(10, 11, 9, 9.5, "t2"),
    ]

    zones = detect_fair_value_gap(candles)

    assert zones == [{"type": "bearish", "top": 14, "bottom": 11, "index": 1}]


def test_detect_fair_value_gap_none_on_overlapping_ranges():
    candles = [candle(10, 11, 9, 10, f"t{i}") for i in range(3)]
    assert detect_fair_value_gap(candles) == []


def test_detect_fair_value_gap_returns_all_zones_found():
    # Two independent impulsive legs back-to-back should each register
    # their own zone.
    candles = [
        candle(10, 11, 9, 10, "t0"),
        candle(10, 15, 10, 14, "t1"),  # bullish gap vs t0/t2
        candle(14, 16, 13, 15, "t2"),
        candle(15, 15, 9, 10, "t3"),  # bearish gap vs t2/t4
        candle(10, 11, 9, 9.5, "t4"),
    ]

    zones = detect_fair_value_gap(candles)

    assert zones == [
        {"type": "bullish", "top": 13, "bottom": 11, "index": 1},
        {"type": "bearish", "top": 13, "bottom": 11, "index": 3},
    ]


# ---------------------------------------------------------------------------
# Milestone 22 (2026-07-17, Performance round 2, Fix B continuation):
# `find_latest_unmitigated_fvg_zone` fuses gap detection, type filtering,
# and mitigation checking into one reverse (newest-candle-first) scan with
# an early exit, replacing what `app.strategy.signal_engine` used to do in
# two phases: a full forward `detect_fair_value_gap` scan, then a reverse
# walk over its output calling `is_zone_mitigated` per zone. `_reference`
# below is that OLD two-phase logic, kept verbatim as an independent
# ground truth -- do not "clean up" or optimize it. The acceptance
# criterion is BIT-IDENTICAL output; if this test ever fails, the module
# implementation must NOT be "fixed" to make it pass -- it means the scan
# direction altered behavior and must be reverted.
# ---------------------------------------------------------------------------


def _find_latest_unmitigated_fvg_zone_reference(candles: list, wanted_type: str) -> dict | None:
    """Verbatim pre-fusion logic: `detect_fair_value_gap`'s full forward
    scan, filtered to `wanted_type`, then the highest-index zone among
    those that are NOT mitigated (`is_zone_mitigated` at `index + 2`,
    exactly the same mitigation-window convention `find_latest_
    unmitigated_fvg_zone` uses).
    """
    matching = [z for z in detect_fair_value_gap(candles) if z["type"] == wanted_type]
    unmitigated = [
        z for z in matching if not is_zone_mitigated(candles, z["index"] + 2, z["top"], z["bottom"])
    ]
    return max(unmitigated, key=lambda z: z["index"]) if unmitigated else None


def _random_mitigation_candle(rng: random.Random, mode: str, prev_close: float) -> dict:
    """Same generator shape as test_strategy_order_block.py's (Milestone
    19) and test_strategy_signal_engine.py's (Milestone 22) property
    tests, reused independently here so this file stays self-contained.
    """
    o = prev_close

    if mode == "doji":
        c = o
    elif mode == "all_bull":
        c = o + rng.uniform(0.01, 5.0)
    elif mode == "all_bear":
        c = o - rng.uniform(0.01, 5.0)
    elif mode == "flat":
        c = o + rng.uniform(-0.05, 0.05)
    elif mode == "trending_runs":
        direction = 1 if (int(prev_close * 100) // 7) % 2 == 0 else -1
        c = o + direction * rng.uniform(0.5, 4.0)
    else:  # "mixed"
        delta = rng.uniform(-3.0, 3.0)
        if rng.random() < 0.1:
            delta *= 10
        c = o + delta

    high = max(o, c) + abs(rng.uniform(0, 1.0 if mode != "flat" else 0.05))
    low = min(o, c) - abs(rng.uniform(0, 1.0 if mode != "flat" else 0.05))
    return {"open": o, "high": high, "low": low, "close": c}


def _random_mitigation_series(rng: random.Random, length: int, mode: str) -> list[dict]:
    candles = []
    price = 100.0
    for _ in range(length):
        c = _random_mitigation_candle(rng, mode, price)
        candles.append(c)
        price = c["close"]
    return candles


def test_find_latest_unmitigated_fvg_zone_matches_reference_property():
    """5,200 randomized synthetic candle series (seeded for determinism),
    varied lengths 5-400, covering adversarial modes, both zone types on
    every case: the fused reverse-scan-with-early-exit must resolve to
    the EXACT SAME winning zone (or both None) as the old
    forward-detect-then-filter-then-max-by-index logic.
    """
    rng = random.Random(220717100)
    modes = ["mixed", "all_bull", "all_bear", "doji", "flat", "trending_runs"]
    num_cases = 5200
    mismatches = []

    for case_idx in range(num_cases):
        length = rng.randint(5, 400)
        mode = modes[case_idx % len(modes)]
        candles = _random_mitigation_series(rng, length, mode)

        for wanted_type in ("bullish", "bearish"):
            expected = _find_latest_unmitigated_fvg_zone_reference(candles, wanted_type)
            actual = find_latest_unmitigated_fvg_zone(candles, wanted_type)

            if actual != expected:
                mismatches.append((case_idx, length, mode, wanted_type, expected, actual))

    assert not mismatches, f"{len(mismatches)} mismatches (showing first 3): {mismatches[:3]}"


def test_find_latest_unmitigated_fvg_zone_none_on_short_or_empty_candles():
    assert find_latest_unmitigated_fvg_zone([], "bullish") is None
    assert find_latest_unmitigated_fvg_zone([candle(10, 11, 9, 10, "t0")], "bullish") is None
    assert (
        find_latest_unmitigated_fvg_zone(
            [candle(10, 11, 9, 10, "t0"), candle(10, 11, 9, 10, "t1")], "bullish"
        )
        is None
    )
