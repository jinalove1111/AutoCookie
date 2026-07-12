"""Jade CRT (Candle Range Theory).

A single reference candle's `[low, high]` range acts as a dealing range
for later price action -- Accumulation (the reference candle itself
sets the range), Manipulation (a later candle wicks beyond one side of
that range, sweeping its liquidity), Distribution (that same candle
closes back within/opposite the range, reversing). This is the diagonal
counterpart to `entry_point_engine`'s Liquidity Raid model (Entry
Model 2): the exact same "sweep then close back inside, a bare wick
alone is never a signal" mechanic (`detect_liquidity_sweep`'s own
pattern), but the "liquidity" being swept is a single candle's own
range instead of a swing point or session/day/week high-low.

`detect_crt(range_candle, candles)` takes the range candle and the
series to check SEPARATELY, deliberately -- this is what lets CRT work
across timeframes (the range candle can be a real HTF candle while
`candles` is an LTF series, the way CRT is most commonly taught: a
daily/weekly candle's range, manipulated and distributed by lower-
timeframe price action within it) as well as within a single series
(`detect_crt_from_previous_candle`, the simplest same-timeframe reading:
this candle vs. the immediately preceding one).

No spec document defines Jade's exact CRT methodology; per operator
instruction (2026-07-12: "if any ambiguity exists, implement the most
reasonable ICT/Jade interpretation and document it in
ENGINEERING_DECISIONS.md instead of waiting for approval"), the design
above is that interpretation -- see ENGINEERING_DECISIONS.md #31.
"""

from __future__ import annotations

from .utils import cf


def detect_crt(range_candle: object, candles: list) -> dict | None:
    """Check whether the LAST candle in `candles` manipulates and
    distributes `range_candle`'s `[low, high]` range: wicks beyond one
    side, then closes back on the originating side (mirrors
    `detect_liquidity_sweep`'s own "only the latest candle is checked"
    discipline).

    `"bullish_crt"`: the last candle wicks BELOW `range_candle`'s low
    (sweeping resting sell-side liquidity under the range) but closes
    back ABOVE it -- a bullish reversal signal. `"bearish_crt"` is the
    mirror: wicks above the range high, closes back below it.

    Returns `{"type", "range_high", "range_low", "target_reference"}` or
    `None`. `target_reference` is the OPPOSITE side of the range from
    whichever side was swept -- the standard CRT target (same "opposite
    side of the range" concept `entry_point_engine`'s Liquidity Raid
    model already uses for its own `target_reference`).
    """
    if not candles:
        return None

    range_high = cf(range_candle, "high")
    range_low = cf(range_candle, "low")

    last = candles[-1]
    last_high = cf(last, "high")
    last_low = cf(last, "low")
    last_close = cf(last, "close")

    if last_low < range_low and last_close > range_low:
        return {
            "type": "bullish_crt",
            "range_high": range_high,
            "range_low": range_low,
            "target_reference": range_high,
        }
    if last_high > range_high and last_close < range_high:
        return {
            "type": "bearish_crt",
            "range_high": range_high,
            "range_low": range_low,
            "target_reference": range_low,
        }
    return None


def detect_crt_from_previous_candle(candles: list) -> dict | None:
    """Convenience wrapper for the simplest, most literal same-timeframe
    CRT reading: the SECOND-TO-LAST candle in `candles` is the range
    candle, checked against the series' own last candle. Equivalent to
    `detect_crt(candles[-2], candles)`.
    """
    if len(candles) < 2:
        return None
    return detect_crt(candles[-2], candles)
