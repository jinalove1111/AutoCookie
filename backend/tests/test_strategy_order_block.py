"""Unit tests for app.strategy.order_block: order block and breaker
block detection, against a hand-constructed 13-candle series with a
known quiet period, one clearly impulsive move, and (for the breaker
case) a subsequent close-through + retest.
"""

from __future__ import annotations

import random

from app.strategy.order_block import (
    _IMPULSE_MULT,
    _LOOKBACK,
    _is_bearish,
    _is_bullish,
    _range,
    cf,
    detect_breaker_block,
    detect_order_block,
)


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def _base_candles() -> list[dict]:
    """15 quiet candles (range ~1, matching order_block._LOOKBACK=15) + 1
    bearish candle (the order block) + 1 impulsive bullish candle (range
    >> 1.8x the rolling average range, matching order_block._IMPULSE_MULT=1.8).
    """
    candles = [candle(100, 101, 100, 100.5, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))  # bearish -> order block candidate
    candles.append(candle(100, 111, 99, 110, "t16"))  # impulsive bullish move
    return candles


def test_detect_order_block_none_when_no_impulsive_move():
    candles = [candle(100, 101, 100, 100.5, f"t{i}") for i in range(11)]
    assert detect_order_block(candles) is None


def test_detect_order_block_finds_bearish_candle_before_bullish_impulse():
    candles = _base_candles()

    result = detect_order_block(candles)

    assert result == {
        "type": "bullish",
        "top": 101,
        "bottom": 99,
        "index": 15,
        "impulse_index": 16,
    }


def test_detect_breaker_block_none_when_zone_never_closed_through():
    candles = _base_candles()
    assert detect_breaker_block(candles) is None


def test_detect_breaker_block_flips_type_after_close_through_and_retest():
    """After the bullish order block (top=101, bottom=99, index=15) is
    fully closed through (a later close < bottom) and then retested from
    below (a later high wicks back up into the zone), the same zone is
    returned with `type` flipped to bearish.
    """
    candles = _base_candles()
    candles.append(candle(99.4, 99.5, 98.5, 98.6, "t17"))  # closes through bottom (99)
    candles.append(candle(98.6, 99.3, 98.5, 99.2, "t18"))  # retest: high (99.3) >= bottom (99)

    result = detect_breaker_block(candles)

    assert result == {
        "type": "bearish",
        "top": 101,
        "bottom": 99,
        "index": 15,
        "retest_index": 18,
    }


# ---------------------------------------------------------------------------
# Milestone 19 (2026-07-16, performance): `detect_order_block` was rewritten
# from a forward scan (O(n^2) across a walk-forward backtest, since it was
# called once per step and always rescanned from the oldest eligible candle)
# to a reverse scan with an early exit, returning the newest qualifying
# match directly instead of scanning everything and keeping only the last
# overwrite. `_detect_order_block_reference` below is the ORIGINAL forward
# implementation, kept verbatim (not imported from the module -- the module
# no longer has it) as a ground truth to property-test the new
# implementation against on thousands of randomized synthetic candle
# series. The acceptance criterion for this milestone was BIT-IDENTICAL
# output; if this test ever fails, the two implementations have diverged
# and the module implementation must NOT be "fixed" to make the test pass --
# it means the performance change altered behavior and must be reverted.
# ---------------------------------------------------------------------------


def _detect_order_block_reference(candles: list) -> dict | None:
    """Verbatim copy of the pre-Milestone-19 `detect_order_block` forward
    scan. Do not "clean up" or optimize this -- it exists ONLY to be an
    independent ground truth for the property test below.
    """
    found: dict | None = None

    for i in range(_LOOKBACK, len(candles)):
        window = candles[i - _LOOKBACK : i]
        avg_range = sum(_range(c) for c in window) / _LOOKBACK
        if avg_range <= 0:
            continue

        impulse_range = _range(candles[i])
        if impulse_range <= _IMPULSE_MULT * avg_range:
            continue

        if _is_bullish(candles[i]):
            for j in range(i - 1, -1, -1):
                if _is_bearish(candles[j]):
                    found = {
                        "type": "bullish",
                        "top": cf(candles[j], "high"),
                        "bottom": cf(candles[j], "low"),
                        "index": j,
                        "impulse_index": i,
                    }
                    break
        elif _is_bearish(candles[i]):
            for j in range(i - 1, -1, -1):
                if _is_bullish(candles[j]):
                    found = {
                        "type": "bearish",
                        "top": cf(candles[j], "high"),
                        "bottom": cf(candles[j], "low"),
                        "index": j,
                        "impulse_index": i,
                    }
                    break

    return found


def _random_candle(rng: random.Random, mode: str, prev_close: float) -> dict:
    """Generate one synthetic candle under a given adversarial `mode`."""
    o = prev_close

    if mode == "doji":
        # close == open (a doji): _is_bullish/_is_bearish both False.
        c = o
    elif mode == "all_bull":
        c = o + rng.uniform(0.01, 5.0)
    elif mode == "all_bear":
        c = o - rng.uniform(0.01, 5.0)
    elif mode == "flat":
        # Tiny range, no impulse ever qualifies.
        c = o + rng.uniform(-0.05, 0.05)
    else:  # "mixed" -- default, includes occasional large impulsive moves
        delta = rng.uniform(-3.0, 3.0)
        if rng.random() < 0.1:
            delta *= 10  # occasional impulsive spike
        c = o + delta

    high = max(o, c) + abs(rng.uniform(0, 1.0 if mode != "flat" else 0.05))
    low = min(o, c) - abs(rng.uniform(0, 1.0 if mode != "flat" else 0.05))
    return {"open": o, "high": high, "low": low, "close": c}


def _random_series(rng: random.Random, length: int, mode: str) -> list[dict]:
    candles = []
    price = 100.0
    for _ in range(length):
        candle = _random_candle(rng, mode, price)
        candles.append(candle)
        price = candle["close"]
    return candles


def test_detect_order_block_matches_reference_forward_scan_property():
    """5,000+ randomized synthetic candle series (seeded for determinism),
    varied lengths 16-400, covering adversarial cases (all-same-color runs,
    doji-heavy series, no-impulse flat series, and impulse-at-first/last-
    valid-index edge placements): the new reverse-scan implementation must
    return the EXACT SAME dict (or both None) as the original forward scan
    for every single case.
    """
    rng = random.Random(190716)  # seeded for determinism
    modes = ["mixed", "all_bull", "all_bear", "doji", "flat"]
    num_cases = 5200
    mismatches = []

    for case_idx in range(num_cases):
        length = rng.randint(16, 400)
        mode = modes[case_idx % len(modes)]
        candles = _random_series(rng, length, mode)

        # Adversarial edge placements: force an impulsive candle at the
        # first valid index (_LOOKBACK) and/or the last index, on top of
        # the otherwise-random series, for a slice of cases.
        if case_idx % 7 == 0 and length > _LOOKBACK:
            base = candles[_LOOKBACK - 1]
            base_close = cf(base, "close")
            candles[_LOOKBACK] = {
                "open": base_close,
                "high": base_close + 20.0,
                "low": base_close - 0.1,
                "close": base_close + 19.5,
            }
        if case_idx % 11 == 0 and length > _LOOKBACK:
            last = candles[-1]
            last_close = cf(last, "close")
            candles[-1] = {
                "open": last_close,
                "high": last_close + 0.1,
                "low": last_close - 20.0,
                "close": last_close - 19.5,
            }

        expected = _detect_order_block_reference(candles)
        actual = detect_order_block(candles)

        if actual != expected:
            mismatches.append((case_idx, length, mode, expected, actual))

    assert not mismatches, f"{len(mismatches)} mismatches (showing first 3): {mismatches[:3]}"
