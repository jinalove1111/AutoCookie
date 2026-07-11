"""Entry model composition.

Part of the Strategy Engine. Combines bias, liquidity sweep, CHOCH/MSS, FVG,
and order block signals into a single entry candidate. Produces analysis
data only — never places orders. Any resulting signal is validated by the
Risk Engine before reaching Execution.
"""

from __future__ import annotations

# TUNED (2026-07-11, Phase 1 controlled parameter sweep -- see
# docs/parameter_sweep_report.md, ENGINEERING_DECISIONS.md, and
# ROADMAP.md for the full methodology/evidence). Previously 2.0
# ("reasonable starting default, not yet tuned"). A one-at-a-time sweep
# (holding all other strategy constants at their defaults) found 2.5
# robust across: in-sample selection (BTCUSDT, 8 chronological periods),
# held-out out-of-sample validation (4 further BTCUSDT periods untouched
# during selection), cross-asset validation (ETHUSDT/SOLUSDT/XRPUSDT,
# all showing consistent improvement), AND a cross-YEAR check (BTCUSDT
# anchored to 2025 instead of 2026, +33.5% PnL, same profitable-period
# ratio) -- the last of these specifically because this project has
# separately found that cross-asset robustness alone is NOT sufficient
# evidence (break-even's effect flipped sign across years on a single
# asset; see ENGINEERING_DECISIONS.md #15/#16). NOTE: `Settings.MIN_RR`
# in config.py (the Risk Engine's floor, currently 2) is a DIFFERENT,
# independently-configured constant -- this one is the Strategy Engine's
# own TARGET ratio for where take-profit is placed, not a risk-approval
# threshold; they no longer need to match numerically (they still both
# happen to be >= 2, coincidentally).
_RR = 2.5
# TUNED (2026-07-11, same sweep/evidence as _RR above). Previously
# 0.001 (0.1%, "arbitrary small buffer, not derived from volatility/ATR
# data"). The sweep tested a narrow band around the old default
# (0.05%-0.2%) and found 0.15% robust across the same four validation
# stages as _RR. Still not ATR/volatility-derived -- that remains a
# genuinely different, untested idea (see docs/parameter_sweep_report.md
# for why the sweep's range stayed deliberately narrow around the prior
# default rather than exploring that).
_STOP_BUFFER = 0.0015


def build_entry_model(
    bias: str,
    sweep: dict | None,
    choch: dict | None,
    fvg: list[dict],
    order_block: dict | None,
    breaker_block: dict | None = None,
    require_full_confluence: bool = False,
) -> dict | None:
    """Combine bias/sweep/CHOCH/FVG/order-block(/breaker-block) signals into
    an entry candidate, or None.

    Confluence rule (default, `require_full_confluence=False`): bias must
    not be neutral, AND at least one of sweep/choch must be present *and
    match the bias direction*, AND at least one FVG, order block, or
    breaker block must agree with the bias direction. The zone (FVG, OB,
    or breaker) with the most recent index is chosen as the entry zone.

    `require_full_confluence` (opt-in, default `False` -- see
    docs/strategy_coverage_audit.md row #9 and docs/strategy_spec.md
    section 6): resolves a real spec/code ambiguity. Section 6's prose
    ("once bias, liquidity sweep, CHOCH/MSS, FVG, and OB/Breaker Block
    have confluence") reads as requiring ALL of sweep AND CHOCH, not
    either one -- the actual code has always required only one of the two
    (`sweep OR choch`), a strictly looser bar. When `True`, this
    parameter requires BOTH `matching_sweep` AND `matching_choch` to be
    present (the stricter, spec-literal reading) instead of either one.
    The FVG/OB/breaker zone selection itself is UNCHANGED either way --
    the spec's "FVG/OB" phrasing (a slash, not "and") already reads as
    alternatives, not a simultaneous requirement, so only the sweep/CHOCH
    half of the ambiguity is addressed here. Default `False` preserves
    the exact prior behavior for every existing caller while this is A/B
    tested, same discipline as `SignalEngine`'s `use_breaker_block` and
    `BacktestEngine`'s `use_breakeven`/`use_partial_tp`.

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

    if require_full_confluence:
        if matching_sweep is None or matching_choch is None:
            return None
    else:
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
