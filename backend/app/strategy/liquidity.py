"""Liquidity sweep detection.

Part of the Strategy Engine. Detects where price has swept resting liquidity
(equal highs/lows, prior swing points). Produces analysis data only — never
places orders. Any resulting signal is validated by the Risk Engine before
reaching Execution.

Only the latest candle is checked as the sweep candle: this module is meant
to be called once per new candle close, so "a sweep happened" always means
"on the candle that just closed".
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
