"""Entry model composition.

Part of the Strategy Engine. Combines bias, liquidity sweep, CHOCH/MSS, FVG,
and order block signals into a single entry candidate. Produces analysis
data only — never places orders. Any resulting signal is validated by the
Risk Engine before reaching Execution.
"""

from __future__ import annotations

_RR = 2.0
_STOP_BUFFER = 0.001  # 0.1% beyond the far edge of the zone


def build_entry_model(
    bias: str,
    sweep: dict | None,
    choch: dict | None,
    fvg: list[dict],
    order_block: dict | None,
) -> dict | None:
    """Combine bias/sweep/CHOCH/FVG/order-block signals into an entry candidate, or None.

    Confluence rule: bias must not be neutral, AND at least one of
    sweep/choch must be present, AND at least one FVG or order block must
    agree with the bias direction. The zone (FVG or OB) with the most
    recent index is chosen as the entry zone.

    On success returns `{direction, entry_price, stop_loss, take_profit, rr,
    zone}` — `zone` (the raw FVG/OB dict used) is included so callers (e.g.
    SignalEngine) can attach it to a signal without recomputing selection.
    """
    if bias not in ("bullish", "bearish"):
        return None
    if sweep is None and choch is None:
        return None

    direction = "long" if bias == "bullish" else "short"
    wanted_type = "bullish" if direction == "long" else "bearish"

    zone: dict | None = None
    if order_block is not None and order_block["type"] == wanted_type:
        zone = order_block

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
