"""Premium / Discount zone calculation.

Part of the Strategy Engine. Divides the current swing range (most recent
swing high to most recent swing low) at its midpoint (equilibrium) to
classify where the latest close sits within that range. Produces analysis
data only -- never places orders. Any resulting signal is validated by the
Risk Engine before reaching Execution.

Standard ICT/SMC concept: the half of the range above equilibrium is
"premium" (expensive -- favors selling/shorting), the half below is
"discount" (cheap -- favors buying/longing). This is used both as an
entry-quality filter (see docs/strategy_spec.md section 8) and, per
ROADMAP, as an optional take-profit extension target (the equilibrium
itself, i.e. the midpoint) once structure allows it.
"""

from __future__ import annotations

from .market_structure import find_swing_highs, find_swing_lows
from .utils import cf


def calculate_premium_discount(candles: list, n: int = 2) -> dict | None:
    """Compute the current swing range and classify the latest close within it.

    The "current swing range" is defined by the MOST RECENT swing high and
    MOST RECENT swing low present in `candles` -- whichever is higher forms
    the range's top, the other its bottom. The two are not required to
    alternate strictly (real structure can print two swing lows before the
    next swing high forms, etc.); using "most recent of each type"
    independently, rather than requiring alternation, keeps this in sync
    with how `bias.py` and `market_structure.py` already read swing points
    elsewhere in this package.

    Returns `None` if fewer than one swing high or one swing low is found,
    or if the resulting range is degenerate (top <= bottom, e.g. the most
    recent swing high has already been broken below the most recent swing
    low -- there is no coherent "current range" to divide in that case; the
    caller should wait for fresh structure rather than get a misleading
    classification).

    On success returns `{top, bottom, equilibrium, zone, range_high_index,
    range_low_index}`, where `zone` is `"premium"` (latest close above
    equilibrium), `"discount"` (below), or `"equilibrium"` (exactly at the
    midpoint -- rare with real price data, but handled explicitly rather
    than left to arbitrarily fall into one side).
    """
    swing_highs = find_swing_highs(candles, n)
    swing_lows = find_swing_lows(candles, n)
    if not swing_highs or not swing_lows:
        return None

    range_high_index = swing_highs[-1]
    range_low_index = swing_lows[-1]
    top = cf(candles[range_high_index], "high")
    bottom = cf(candles[range_low_index], "low")
    if top <= bottom:
        return None

    equilibrium = (top + bottom) / 2
    last_close = cf(candles[-1], "close")
    if last_close > equilibrium:
        zone = "premium"
    elif last_close < equilibrium:
        zone = "discount"
    else:
        zone = "equilibrium"

    return {
        "top": top,
        "bottom": bottom,
        "equilibrium": equilibrium,
        "zone": zone,
        "range_high_index": range_high_index,
        "range_low_index": range_low_index,
    }
