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

Also houses `find_previous_swing_high`/`find_previous_swing_low`: the most
recently confirmed swing high/low, reported independently as resting
liquidity targets (see docs/strategy_spec.md section 9).
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


def find_previous_swing_high(candles: list, n: int = 2) -> dict | None:
    """Return the most recently confirmed swing high, or `None` if none exists yet.

    "Previous swing high" is the same "most recent swing high in the
    series" concept `premium_discount.calculate_premium_discount` and
    `bias.py` already read via `find_swing_highs` -- exposed here as its
    own detector because ROADMAP item #4 (TP logic: "long targets previous
    high first") needs just the high side as a resting liquidity target,
    independent of whether a swing low has formed yet.

    Returns `{"price": <high>, "index": <candle index>}`.
    """
    swing_highs = find_swing_highs(candles, n)
    if not swing_highs:
        return None
    index = swing_highs[-1]
    return {"price": cf(candles[index], "high"), "index": index}


def find_previous_swing_low(candles: list, n: int = 2) -> dict | None:
    """Return the most recently confirmed swing low, or `None` if none exists yet.

    Symmetric to `find_previous_swing_high` -- the resting liquidity target
    for short TPs (ROADMAP item #4).

    Returns `{"price": <low>, "index": <candle index>}`.
    """
    swing_lows = find_swing_lows(candles, n)
    if not swing_lows:
        return None
    index = swing_lows[-1]
    return {"price": cf(candles[index], "low"), "index": index}


def detect_choch_mss(
    candles: list, n: int = 2, swept_index: int | None = None
) -> dict | None:
    """Detect a CHOCH/MSS event in the given candles and return its details, or None.

    `swept_index` (optional): the index of the swing point a preceding
    `detect_liquidity_sweep()` call reported as swept (its `"swept_index"`).
    When provided, only swing highs/lows at index >= `swept_index` are
    considered when picking the broken level, so the CHOCH this function
    returns causally reflects structure that formed at or after that
    specific sweep -- not an arbitrary, unrelated earlier structural leg
    (see docs/strategy_spec.md section 3: "swept liquidity level" is a
    required input here). When `swept_index` is None (e.g. standalone
    calls, as the unit tests in this package do), behavior is unchanged
    from before this parameter was added -- all swing points are eligible.
    """
    if len(candles) < 2 * n + 3:
        return None

    swing_highs = find_swing_highs(candles, n)
    swing_lows = find_swing_lows(candles, n)
    if swept_index is not None:
        swing_highs = [i for i in swing_highs if i >= swept_index]
        swing_lows = [i for i in swing_lows if i >= swept_index]
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
