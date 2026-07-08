"""Change of Character (CHOCH) / Market Structure Shift (MSS) detection.

Part of the Strategy Engine. Detects structural shifts that indicate a
potential change in trend direction. Produces analysis data only — never
places orders. Any resulting signal is validated by the Risk Engine before
reaching Execution.

Also houses the swing-high/swing-low helpers shared across this package.
Swing points use a symmetric lookback/lookforward window (default n=2): a
candle only confirms as a swing high/low once `n` candles on both sides
agree, which filters single-candle noise without needing a smoothing
indicator (e.g. a moving average) that would lag entries.
"""

from __future__ import annotations

from .utils import cf


def find_swing_highs(candles: list, n: int = 2) -> list[int]:
    """Return indices of swing highs: local maxima confirmed by `n` candles each side."""
    highs = [cf(c, "high") for c in candles]
    result: list[int] = []
    for i in range(n, len(candles) - n):
        window = highs[i - n : i + n + 1]
        if highs[i] == max(window):
            result.append(i)
    return result


def find_swing_lows(candles: list, n: int = 2) -> list[int]:
    """Return indices of swing lows: local minima confirmed by `n` candles each side."""
    lows = [cf(c, "low") for c in candles]
    result: list[int] = []
    for i in range(n, len(candles) - n):
        window = lows[i - n : i + n + 1]
        if lows[i] == min(window):
            result.append(i)
    return result


def detect_choch_mss(candles: list, n: int = 2) -> dict | None:
    """Detect a CHOCH/MSS event in the given candles and return its details, or None."""
    if len(candles) < 2 * n + 3:
        return None

    swing_highs = find_swing_highs(candles, n)
    swing_lows = find_swing_lows(candles, n)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None

    last_idx = len(candles) - 1
    last_close = cf(candles[last_idx], "close")

    high_vals = [cf(candles[i], "high") for i in swing_highs]
    low_vals = [cf(candles[i], "low") for i in swing_lows]

    downtrend = high_vals[-1] < high_vals[-2] and low_vals[-1] < low_vals[-2]
    uptrend = high_vals[-1] > high_vals[-2] and low_vals[-1] > low_vals[-2]

    if downtrend:
        level_idx = swing_highs[-1]
        level = high_vals[-1]
        if level_idx < last_idx and last_close > level:
            return {
                "type": "bullish_choch",
                "broken_level": level,
                "broken_index": level_idx,
                "confirm_index": last_idx,
            }
    elif uptrend:
        level_idx = swing_lows[-1]
        level = low_vals[-1]
        if level_idx < last_idx and last_close < level:
            return {
                "type": "bearish_choch",
                "broken_level": level,
                "broken_index": level_idx,
                "confirm_index": last_idx,
            }

    return None
