"""Fair Value Gap (FVG) detection.

Part of the Strategy Engine. Detects imbalance zones (fair value gaps) left
behind by impulsive price moves. Produces analysis data only — never places
orders. Any resulting signal is validated by the Risk Engine before reaching
Execution.
"""

from __future__ import annotations

from .utils import cf, is_zone_mitigated


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


def find_latest_unmitigated_fvg_zone(candles: list, wanted_type: str) -> dict | None:
    """Return the highest-index FVG zone of `wanted_type` that is NOT yet
    mitigated (per `app.strategy.utils.is_zone_mitigated`, using the same
    `index + 2` mitigation-window start every other caller of
    `is_zone_mitigated` on an FVG zone uses -- see
    `app.strategy.signal_engine`'s own former inline computation, now
    replaced by this function), or `None`.

    PERFORMANCE (2026-07-17, Performance round 2 / Milestone 22
    continuation -- see `app.strategy.signal_engine.
    _select_unmitigated_fvg_zones`'s docstring for the original
    argmax-identity proof this function extends): that fix stopped
    calling `is_zone_mitigated` on every historical zone, but still paid
    for `detect_fair_value_gap`'s full forward scan over every candle
    before reverse-walking its result. This function fuses detection,
    type filtering, and mitigation checking into ONE reverse scan with an
    early exit, so a call that only needs the newest surviving zone (the
    ONLY caller of this function, `signal_engine.py`) no longer pays for
    the full forward detection scan either.

    Why the reverse walk is provably the same answer as
    `detect_fair_value_gap`'s forward scan, not just a faster one:
    `detect_fair_value_gap`'s loop body at a given `i` reads ONLY
    `candles[i-1]`, `candles[i]`, `candles[i+1]` -- nothing carries
    across iterations (no running total, no "last seen" state) -- so the
    SET of `i` values that qualify as a gap, and each one's computed
    `type`/`top`/`bottom`, is completely independent of which direction
    `i` is visited in. Visiting `i` from `len(candles) - 2` down to `1`
    therefore finds the exact same zones `detect_fair_value_gap` would,
    merely in reverse discovery order -- so the first one found (highest
    `index`) that also matches `wanted_type` and passes
    `is_zone_mitigated` is, by construction, the same zone
    `max(matching_fvgs, key=lambda z: z["index"])` would have selected
    from the full `detect_fair_value_gap` + eager-mitigation-filter
    result. `detect_fair_value_gap` itself is left completely unchanged
    -- its other callers (`entry_point_engine.py`, `htf_ltf_confluence.py`)
    need the FULL ordered zone list for their own different consumption
    patterns and are not touched by this addition.

    See test_strategy_fvg.py's property test (verbatim reference via
    `detect_fair_value_gap` + eager `is_zone_mitigated` filtering, 5,000+
    seeded synthetic series) for the bit-identical verification this
    docstring's claims were checked against.
    """
    for i in range(len(candles) - 2, 0, -1):
        prev_high = cf(candles[i - 1], "high")
        prev_low = cf(candles[i - 1], "low")
        next_high = cf(candles[i + 1], "high")
        next_low = cf(candles[i + 1], "low")

        if prev_high < next_low:
            zone_type, top, bottom = "bullish", next_low, prev_high
        elif prev_low > next_high:
            zone_type, top, bottom = "bearish", prev_low, next_high
        else:
            continue

        if zone_type != wanted_type:
            continue

        if not is_zone_mitigated(candles, i + 2, top, bottom):
            return {"type": zone_type, "top": top, "bottom": bottom, "index": i}

    return None
