"""Liquidity sweep detection.

Part of the Strategy Engine. Detects where price has swept resting liquidity
(equal highs/lows, prior swing points). Produces analysis data only — never
places orders. Any resulting signal is validated by the Risk Engine before
reaching Execution.

Only the latest candle is checked as the sweep candle: this module is meant
to be called once per new candle close, so "a sweep happened" always means
"on the candle that just closed".

Also houses `detect_equal_highs`/`detect_equal_lows` (docs/ROADMAP.md "Core
Rule MVP completion" item #5): unlike `detect_liquidity_sweep` above, these
scan the WHOLE given candle series for resting-liquidity pools, not just
whatever the latest candle just did to them -- see their own docstrings.
"""

from __future__ import annotations

from .market_structure import find_swing_highs, find_swing_lows
from .utils import cf


def detect_liquidity_sweep(candles: list, n: int = 2) -> dict | None:
    """Detect a liquidity sweep event in the given candles and return its details, or None."""
    if len(candles) < 2 * n + 2:
        return None

    last_idx = len(candles) - 1
    last_high = cf(candles[last_idx], "high")
    last_low = cf(candles[last_idx], "low")
    last_close = cf(candles[last_idx], "close")

    swing_highs = find_swing_highs(candles, n)
    for idx in reversed(swing_highs):
        if idx >= last_idx:
            continue
        level = cf(candles[idx], "high")
        if last_high > level and last_close < level:
            return {
                "type": "buy_side",
                "level": level,
                "swept_index": idx,
                "sweep_index": last_idx,
            }

    swing_lows = find_swing_lows(candles, n)
    for idx in reversed(swing_lows):
        if idx >= last_idx:
            continue
        level = cf(candles[idx], "low")
        if last_low < level and last_close > level:
            return {
                "type": "sell_side",
                "level": level,
                "swept_index": idx,
                "sweep_index": last_idx,
            }

    return None


_EQUAL_LEVEL_TOLERANCE = 0.001  # 0.1% -- see detect_equal_highs's docstring.


def detect_equal_highs(candles: list, n: int = 2, tolerance: float = _EQUAL_LEVEL_TOLERANCE) -> list[dict]:
    """Detect equal-highs ("EQH") resting buy-side liquidity: consecutive
    confirmed swing highs (`find_swing_highs`) sitting within `tolerance`
    (fractional, default 0.1%) of each other.

    Real price action essentially never prints two swing highs at the
    EXACT same price, so this is a tolerance match, not equality --
    standard ICT/SMC "equal highs" concept: price failing to make a clean
    new high twice near the same level leaves a pool of resting buy-side
    liquidity (stops/breakout orders) just above both highs, a common
    sweep target (mirrors `detect_liquidity_sweep`'s own swing-high-based
    `buy_side` sweep, just as the LIQUIDITY POOL rather than the sweep
    event itself). Only ADJACENT pairs in the swing-high sequence are
    checked (not every possible pair), matching how equal highs are read
    in practice -- two consecutive, still-nearby attempts at a new high,
    not two highs separated by an unrelated intervening swing.

    Returns one entry per qualifying adjacent pair:
    `{"type": "equal_highs", "level": <higher of the two prices>,
    "first_index": <earlier swing index>, "second_index": <later swing
    index>}`. `level` is the HIGHER of the two (not their average) so it
    stays a real, tradeable price actually printed in the series, sitting
    at (or just under) where resting liquidity above the pool would
    actually rest.
    """
    swing_highs = find_swing_highs(candles, n)
    zones: list[dict] = []
    for first_idx, second_idx in zip(swing_highs, swing_highs[1:]):
        first_price = cf(candles[first_idx], "high")
        second_price = cf(candles[second_idx], "high")
        if abs(first_price - second_price) / first_price <= tolerance:
            zones.append({
                "type": "equal_highs",
                "level": max(first_price, second_price),
                "first_index": first_idx,
                "second_index": second_idx,
            })
    return zones


def detect_equal_lows(candles: list, n: int = 2, tolerance: float = _EQUAL_LEVEL_TOLERANCE) -> list[dict]:
    """Detect equal-lows ("EQL") resting sell-side liquidity -- exact
    mirror of `detect_equal_highs`, see its docstring for the full
    rationale. Consecutive confirmed swing lows (`find_swing_lows`)
    within `tolerance` of each other.

    Returns one entry per qualifying adjacent pair:
    `{"type": "equal_lows", "level": <lower of the two prices>,
    "first_index": ..., "second_index": ...}`. `level` is the LOWER of
    the two (mirrors `detect_equal_highs` using the higher), sitting at
    (or just above) where resting sell-side liquidity below the pool
    would actually rest.
    """
    swing_lows = find_swing_lows(candles, n)
    zones: list[dict] = []
    for first_idx, second_idx in zip(swing_lows, swing_lows[1:]):
        first_price = cf(candles[first_idx], "low")
        second_price = cf(candles[second_idx], "low")
        if abs(first_price - second_price) / first_price <= tolerance:
            zones.append({
                "type": "equal_lows",
                "level": min(first_price, second_price),
                "first_index": first_idx,
                "second_index": second_idx,
            })
    return zones
