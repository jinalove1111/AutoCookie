"""Shared candle-field accessor for the Strategy Engine sub-package.

Candles may arrive as plain dicts (the normal case, matching the `candles`
DB row) or as lightweight objects (e.g. ORM rows); this accessor lets every
detector in this package stay agnostic to the concrete candle type.
"""

from __future__ import annotations

from typing import Any


def cf(candle: Any, key: str) -> Any:
    """Read a single OHLCV field from a candle, whether dict-like or attribute-like."""
    if isinstance(candle, dict):
        return candle[key]
    return getattr(candle, key)


def is_zone_mitigated(candles: list, start_index: int, top: float, bottom: float) -> bool:
    """True if any candle in `candles[start_index:-1]` has a [low, high]
    range that overlaps `[bottom, top]` -- i.e. price has already traded
    back into the zone at some point BEFORE the current (most recent)
    candle.

    Standard SMC "mitigation" concept: once price has returned into an FVG
    or order block, the imbalance/zone has already been retested, so a
    FRESH entry off that same zone is not a new setup -- it's re-entering
    a level price has already interacted with (empirically, this is
    exactly what was producing near-identical duplicate signals/trades
    back-to-back in real backtests before this check existed: the same
    still-visible zone kept re-qualifying as "the most recent zone" on
    consecutive walk-forward steps even after a trade off it had already
    failed and price had moved back through it). `start_index` is caller-
    chosen (see `SignalEngine.generate_signal`) since "since it formed"
    means different things for an FVG (the candle after the 3-candle gap)
    vs. an order block (the candle after the confirming impulse candle,
    not the base candle itself -- the impulse candle's own range routinely
    overlaps the base zone it originated from, which is not mitigation).

    The LAST candle in `candles` is deliberately EXCLUDED from this check
    (hence `[:-1]`): callers always pass "everything known up to and
    including right now," and the current candle touching a zone as part
    of triggering a signal (e.g. a liquidity-sweep wick that taps straight
    into a nearby FVG in the same candle -- a completely standard, valid
    SMC entry trigger) is the setup itself, not a disqualifying PRIOR
    retest. Only candles strictly before "now" count as mitigation.
    """
    if len(candles) <= 1:
        return False
    return any(
        cf(c, "high") >= bottom and cf(c, "low") <= top for c in candles[start_index:-1]
    )
