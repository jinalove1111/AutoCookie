"""Fair Value Gap (FVG) detection.

Part of the Strategy Engine. Detects imbalance zones (fair value gaps) left
behind by impulsive price moves. Produces analysis data only — never places
orders. Any resulting signal is validated by the Risk Engine before reaching
Execution.
"""

from __future__ import annotations

from .utils import cf


def detect_fair_value_gap(candles: list) -> list[dict]:
    """Detect all fair value gap zones present in the given candles."""
    zones: list[dict] = []
    for i in range(1, len(candles) - 1):
        prev_high = cf(candles[i - 1], "high")
        prev_low = cf(candles[i - 1], "low")
        next_high = cf(candles[i + 1], "high")
        next_low = cf(candles[i + 1], "low")

        if prev_high < next_low:
            zones.append({"type": "bullish", "top": next_low, "bottom": prev_high, "index": i})
        elif prev_low > next_high:
            zones.append({"type": "bearish", "top": prev_low, "bottom": next_high, "index": i})

    return zones
