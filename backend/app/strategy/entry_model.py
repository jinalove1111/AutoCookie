"""Entry model composition.

Part of the Strategy Engine. Combines bias, liquidity sweep, CHOCH/MSS, FVG,
and order block signals into a single entry candidate. Produces analysis
data only — never places orders. Any resulting signal is validated by the
Risk Engine before reaching Execution.
"""

from __future__ import annotations

# Not derived from backtesting/optimization -- reasonable starting defaults,
# not yet tuned against real performance data. RR=2.0 is a common baseline
# minimum reward:risk for this style of setup (also mirrors
# `Settings.MIN_RR` in config.py, so Risk Engine's floor and the Strategy
# Engine's own target already agree); revisit once real backtest results
# exist to justify a different value.
_RR = 2.0
# 0.1% beyond the far edge of the zone: a small buffer so the stop sits
# just outside the zone rather than exactly on its boundary (a stop exactly
# on the boundary could get tagged by the same wick that respects the
# zone). The specific 0.1% figure is an arbitrary small buffer, not derived
# from volatility/ATR data -- not yet tuned.
_STOP_BUFFER = 0.001


def build_entry_model(
    bias: str,
    sweep: dict | None,
    choch: dict | None,
    fvg: list[dict],
    order_block: dict | None,
    breaker_block: dict | None = None,
) -> dict | None:
    """Combine bias/sweep/CHOCH/FVG/order-block(/breaker-block) signals into
    an entry candidate, or None.

    Confluence rule: bias must not be neutral, AND at least one of
    sweep/choch must be present *and match the bias direction*, AND at
    least one FVG, order block, or breaker block must agree with the bias
    direction. The zone (FVG, OB, or breaker) with the most recent index
    is chosen as the entry zone.

    `breaker_block` (optional, default `None` -- existing callers that
    don't pass it get byte-for-byte the prior behavior) is a second,
    independent zone candidate alongside `order_block`: in practice the
    two are mutually exclusive at any given evaluation point (a breaker
    only exists once its underlying order block has already been closed
    through and retested -- see `detect_breaker_block`'s docstring -- at
    which point `detect_order_block` no longer reports that same zone as
    a fresh OB), but both are still passed through the same "most recent
    index wins" selection as FVG/OB already are, rather than special-cased,
    since a breaker's `type` is the FLIPPED polarity of its original OB
    and may genuinely be the freshest/only zone available in either
    direction at a given point.

    Direction-matching rationale (documented per project rule -- every
    strategy rule must have its "why" explicit, see docs/strategy_spec.md):
    a `sell_side` liquidity sweep (price sweeps below a prior swing low,
    grabbing resting sell-side liquidity) is the setup that precedes a
    bullish reversal, so it is only valid confluence for a bullish-bias
    `long` entry. A `buy_side` sweep (grabs liquidity above a prior high)
    is only valid confluence for a bearish-bias `short` entry.
    Symmetrically, a `bullish_choch` only counts for `long`, and a
    `bearish_choch` only counts for `short`. A sweep/choch whose type
    conflicts with the bias-derived direction is treated as if absent (not
    an error -- it just doesn't count toward confluence), because a
    direction-mismatched sweep/CHoCH would mean entering against the
    engine's own structural read.

    On success returns `{direction, entry_price, stop_loss, take_profit, rr,
    zone}` — `zone` (the raw FVG/OB/breaker dict used) is included so callers (e.g.
    SignalEngine) can attach it to a signal without recomputing selection.
    """
    if bias not in ("bullish", "bearish"):
        return None

    direction = "long" if bias == "bullish" else "short"
    wanted_type = "bullish" if direction == "long" else "bearish"

    wanted_sweep_type = "sell_side" if direction == "long" else "buy_side"
    wanted_choch_type = "bullish_choch" if direction == "long" else "bearish_choch"

    matching_sweep = sweep if sweep is not None and sweep["type"] == wanted_sweep_type else None
    matching_choch = choch if choch is not None and choch["type"] == wanted_choch_type else None

    if matching_sweep is None and matching_choch is None:
        return None

    zone: dict | None = None
    if order_block is not None and order_block["type"] == wanted_type:
        zone = order_block

    if breaker_block is not None and breaker_block["type"] == wanted_type:
        if zone is None or breaker_block["index"] > zone["index"]:
            zone = breaker_block

    matching_fvgs = [z for z in fvg if z["type"] == wanted_type]
    if matching_fvgs:
        latest_fvg = max(matching_fvgs, key=lambda z: z["index"])
        if zone is None or latest_fvg["index"] > zone["index"]:
            zone = latest_fvg

    if zone is None:
        return None

    top = zone["top"]
    bottom = zone["bottom"]

    if direction == "long":
        entry_price = top
        stop_loss = bottom * (1 - _STOP_BUFFER)
        risk = entry_price - stop_loss
        take_profit = entry_price + risk * _RR
    else:
        entry_price = bottom
        stop_loss = top * (1 + _STOP_BUFFER)
        risk = stop_loss - entry_price
        take_profit = entry_price - risk * _RR

    if risk <= 0:
        return None

    return {
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rr": _RR,
        "zone": zone,
    }
