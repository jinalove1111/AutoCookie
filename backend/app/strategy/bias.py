"""HTF (higher time frame) bias detection.

Part of the Strategy Engine. This module only analyzes market structure to
infer directional bias. It must never place orders directly — output is
consumed downstream by CHOCH/MSS and entry-model logic, and any resulting
signal is validated by the Risk Engine before reaching Execution.

Bias reads only the last 3 swing highs/lows (or fewer, down to 2, if that's
all that is available): HTF bias should track the current leg of structure,
not stale swings several legs back.
"""

from __future__ import annotations

from .market_structure import find_swing_highs, find_swing_lows
from .utils import cf


def detect_htf_bias(candles: list, n: int = 2) -> str:
    """Infer higher-time-frame directional bias ("bullish"/"bearish"/"neutral") from candles."""
    if len(candles) < 10:
        return "neutral"

    swing_highs = find_swing_highs(candles, n)
    swing_lows = find_swing_lows(candles, n)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "neutral"

    high_vals = [cf(candles[i], "high") for i in swing_highs[-3:]]
    low_vals = [cf(candles[i], "low") for i in swing_lows[-3:]]

    highs_rising = all(b > a for a, b in zip(high_vals, high_vals[1:]))
    lows_rising = all(b > a for a, b in zip(low_vals, low_vals[1:]))
    highs_falling = all(b < a for a, b in zip(high_vals, high_vals[1:]))
    lows_falling = all(b < a for a, b in zip(low_vals, low_vals[1:]))

    if highs_rising and lows_rising:
        return "bullish"
    if highs_falling and lows_falling:
        return "bearish"
    return "neutral"
