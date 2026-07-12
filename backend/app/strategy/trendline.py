"""Jade Trendline Methodology.

Diagonal-line counterpart to this package's existing HORIZONTAL-level
detectors (`detect_liquidity_sweep`, `detect_choch_mss`): a trendline
connects two confirmed swing points of the same type and projects a
price at any later candle index, the same way a swing high/low already
acts as a fixed horizontal level -- these functions mirror
`detect_liquidity_sweep`/`detect_choch_mss`'s own break/sweep mechanics,
generalized from a constant level to `slope * index + intercept`.

No spec document defines Jade's exact trendline methodology; per
operator instruction (2026-07-12: "if any ambiguity exists, implement
the most reasonable ICT/Jade interpretation and document it in
ENGINEERING_DECISIONS.md instead of waiting for approval"), the design
below is that interpretation -- see ENGINEERING_DECISIONS.md #26 for the
full rationale, including why a trendline is defined by exactly the two
MOST RECENT confirmed swing points of the matching type (a simple,
deterministic 2-point line), not a best-fit regression through more.
"""

from __future__ import annotations

from .market_structure import find_swing_highs, find_swing_lows
from .utils import cf


def detect_trendline(candles: list, direction: str, n: int = 2) -> dict | None:
    """Construct a trendline from the two most recent confirmed swing
    points of the matching type: `"support"` connects swing LOWS
    (`find_swing_lows`, an ascending line under an uptrend), `"resistance"`
    connects swing HIGHS (`find_swing_highs`, a descending line over a
    downtrend). Returns `None` if fewer than 2 such swing points exist
    yet.

    Returns `{"type", "point1", "point2", "slope", "intercept"}` --
    `point1`/`point2` are `{"index", "price"}` (the two swing points
    used, in chronological order), and `slope`/`intercept` let
    `trendline_price_at` project the line's price at any index (`slope *
    index + intercept`), including indices AFTER `point2` (extrapolation
    is exactly the point: the whole reason to build a trendline is to
    check what it implies about candles that come after it).
    """
    if direction not in ("support", "resistance"):
        raise ValueError(f"direction must be 'support' or 'resistance', got {direction!r}")

    if direction == "support":
        swing_indices = find_swing_lows(candles, n)
        field = "low"
    else:
        swing_indices = find_swing_highs(candles, n)
        field = "high"

    if len(swing_indices) < 2:
        return None

    idx1, idx2 = swing_indices[-2], swing_indices[-1]
    price1 = cf(candles[idx1], field)
    price2 = cf(candles[idx2], field)

    slope = (price2 - price1) / (idx2 - idx1)
    intercept = price1 - slope * idx1

    return {
        "type": direction,
        "point1": {"index": idx1, "price": price1},
        "point2": {"index": idx2, "price": price2},
        "slope": slope,
        "intercept": intercept,
    }


def trendline_price_at(trendline: dict, index: int) -> float:
    """The trendline's projected price at `index` (`slope * index +
    intercept`), including indices beyond the two points that defined
    it.
    """
    return trendline["slope"] * index + trendline["intercept"]


def detect_trendline_break(candles: list, trendline: dict) -> dict | None:
    """True break: the LAST candle's close is beyond the trendline at
    its own index -- below it for a `"support"` line (the ascending line
    under an uptrend has been violated to the downside, a bearish
    signal), above it for a `"resistance"` line (violated to the upside,
    a bullish signal). Mirrors `detect_choch_mss`'s "only the latest
    candle is checked, only a CLOSE beyond the level counts" discipline,
    generalized from a constant level to the trendline's projected price.

    Returns `{"type": "support_break"|"resistance_break",
    "trendline_price_at_break", "break_index"}` or `None`.
    """
    last_index = len(candles) - 1
    last_close = cf(candles[last_index], "close")
    line_price = trendline_price_at(trendline, last_index)

    if trendline["type"] == "support" and last_close < line_price:
        return {
            "type": "support_break",
            "trendline_price_at_break": line_price,
            "break_index": last_index,
        }
    if trendline["type"] == "resistance" and last_close > line_price:
        return {
            "type": "resistance_break",
            "trendline_price_at_break": line_price,
            "break_index": last_index,
        }
    return None


def detect_trendline_liquidity_sweep(candles: list, trendline: dict) -> dict | None:
    """Trendline liquidity sweep: the LAST candle wicks THROUGH the
    trendline's projected price at its own index, then closes back on
    the ORIGINATING side -- the diagonal-line mirror of
    `detect_liquidity_sweep`'s horizontal-level sweep (resting stops
    sitting just beyond an obvious trendline get run, then price
    reverses and the trend continues, rather than breaking). For a
    `"support"` line: wicks below, closes back above (bullish
    continuation). For `"resistance"`: wicks above, closes back below
    (bearish continuation).

    Returns `{"type": "trendline_sweep_support"|"trendline_sweep_
    resistance", "level", "sweep_index"}` or `None`.
    """
    last_index = len(candles) - 1
    last = candles[last_index]
    last_high = cf(last, "high")
    last_low = cf(last, "low")
    last_close = cf(last, "close")
    line_price = trendline_price_at(trendline, last_index)

    if trendline["type"] == "support" and last_low < line_price and last_close > line_price:
        return {"type": "trendline_sweep_support", "level": line_price, "sweep_index": last_index}
    if trendline["type"] == "resistance" and last_high > line_price and last_close < line_price:
        return {"type": "trendline_sweep_resistance", "level": line_price, "sweep_index": last_index}
    return None
