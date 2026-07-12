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
    require_ob_fvg_confluence: bool = False,
    previous_swing_high: dict | None = None,
    previous_swing_low: dict | None = None,
    premium_discount: dict | None = None,
    use_structure_tp: bool = False,
    require_premium_discount_filter: bool = False,
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
    The FVG/OB/breaker zone selection itself is UNCHANGED by
    `require_full_confluence` -- see `require_ob_fvg_confluence` below for
    the parameter that addresses THAT half of the ambiguity instead.
    Default `False` preserves the exact prior behavior for every existing
    caller while this is A/B tested, same discipline as `SignalEngine`'s
    `use_breaker_block` and `BacktestEngine`'s `use_breakeven`/`use_partial_tp`.

    `require_ob_fvg_confluence` (opt-in, default `False` -- see
    docs/ROADMAP.md "Core Rule MVP completion" item #3): the spec's
    "FVG/OB" phrasing (a slash, not "and") has always been implemented as
    alternatives -- either a matching order block/breaker OR a matching
    FVG is enough, whichever has the more recent index wins zone
    selection. When `True`, this changes that to "both agree": a matching
    order block (or breaker block) AND a matching FVG must BOTH be
    present, or no entry is produced (same treatment as
    `require_full_confluence` narrowing sweep/CHOCH from "either" to
    "both" -- this is the FVG/OB counterpart). The zone actually used for
    entry is still whichever of the two (OB/breaker vs. FVG) has the more
    recent index, same "most recent index wins" rule as the default mode
    -- this parameter only gates whether both must be PRESENT, it doesn't
    change which one is picked once they are.

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

    `use_structure_tp` (opt-in, default `False` -- see docs/ROADMAP.md
    "Core Rule MVP completion" item #4, which depends on items #1
    (`premium_discount.calculate_premium_discount`) and #2
    (`market_structure.find_previous_swing_high`/`find_previous_swing_low`)):
    when `False`, `take_profit` is always the fixed-`_RR` target (the
    prior, only behavior). When `True`, `take_profit` instead targets
    real structure -- resolved as follows (`previous_swing_high`/
    `previous_swing_low`/`premium_discount` are the raw dicts from those
    two detectors, caller-supplied so this function stays a pure
    composition step like the rest of it):

    For a `long`, the candidate targets are the previous swing high's
    price (`previous_swing_high["price"]`, "long targets previous high
    first" per the roadmap item) and the premium/discount equilibrium
    (`premium_discount["equilibrium"]`, "if structure allows, target the
    0.5 equilibrium instead" -- read here as "instead" meaning whichever
    candidate is FURTHER from entry in the trade's favor, since a further
    valid target is strictly the more favorable read of "structure
    allows" reaching past the nearer one). Only candidates strictly above
    `entry_price` are valid (a previous high/equilibrium already behind
    price is not a usable forward target). `short` is the exact mirror:
    previous swing low first, equilibrium if it extends further below
    entry, only candidates strictly below `entry_price` are valid.

    If neither candidate is valid (both missing, or both already behind
    price), this falls back to the exact prior fixed-`_RR` `take_profit`
    -- a missing/invalid structure input degrades to old behavior rather
    than rejecting an otherwise-valid entry. Whenever a structure target
    IS used, the returned `rr` is recomputed as the trade's REAL
    reward:risk (`reward / risk`, not the fixed `_RR` constant) -- unlike
    the default mode, `take_profit` here is no longer *defined* as
    `entry +/- risk * _RR`, so reporting the fixed constant as `rr` would
    misrepresent the trade to the Risk Engine's `MIN_RR` gate
    (`risk_manager.py`), which reads this exact field.

    `previous_swing_high`/`previous_swing_low`/`premium_discount` are
    read from LTF structure (matching every other detector `SignalEngine`
    feeds this function -- see docs/strategy_spec.md section 1's
    HTF/LTF-separation rule): the roadmap's "if HTF structure allows"
    phrasing is used loosely there for "if the broader swing-range
    context allows", not a literal second candle series -- `find_previous_
    swing_high`/`find_previous_swing_low`/`calculate_premium_discount`
    all already operate on a single candle list, same as `find_swing_highs`/
    `find_swing_lows` underneath every other LTF structural detector in
    this pipeline.

    `require_premium_discount_filter` (opt-in, default `False` -- see
    docs/strategy_spec.md section 8's entry-quality-filter gap): standard
    ICT/SMC rule -- a `long` entered from the PREMIUM half of the current
    swing range (buying the expensive half) or a `short` entered from the
    DISCOUNT half (selling the cheap half) is entering against the range's
    own supply/demand read, per section 8's documented rationale. When
    `True` and `premium_discount["zone"]` disagrees with the trade
    direction (`long` + `"premium"`, or `short` + `"discount"`), no entry
    is produced. `"equilibrium"` (exactly at the midpoint) is treated as
    valid for EITHER direction -- it is deliberately neither cheap nor
    expensive, so there is no directional reason to reject it. A missing
    `premium_discount` (detector found no coherent current range) degrades
    to NOT rejecting -- same "missing structure input never rejects an
    otherwise-valid entry" discipline as `use_structure_tp` above, since
    this parameter is a quality filter on top of an already-valid setup,
    not a required-presence check like `require_full_confluence`/
    `require_ob_fvg_confluence`. This check runs independently of
    `use_structure_tp` -- either, both, or neither may be enabled, since
    one governs whether an entry is produced at all and the other governs
    where its take-profit is placed.

    On success returns `{direction, entry_price, stop_loss, take_profit, rr,
    zone}` — `zone` (the raw FVG/OB/breaker dict used) is included so callers (e.g.
    SignalEngine) can attach it to a signal without recomputing selection.
    """
    if bias not in ("bullish", "bearish"):
        return None

    direction = "long" if bias == "bullish" else "short"
    wanted_type = "bullish" if direction == "long" else "bearish"

    if require_premium_discount_filter and premium_discount is not None:
        wrong_side = "premium" if direction == "long" else "discount"
        if premium_discount["zone"] == wrong_side:
            return None

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

    ob_zone: dict | None = None
    if order_block is not None and order_block["type"] == wanted_type:
        ob_zone = order_block

    if breaker_block is not None and breaker_block["type"] == wanted_type:
        if ob_zone is None or breaker_block["index"] > ob_zone["index"]:
            ob_zone = breaker_block

    matching_fvgs = [z for z in fvg if z["type"] == wanted_type]
    fvg_zone = max(matching_fvgs, key=lambda z: z["index"]) if matching_fvgs else None

    if require_ob_fvg_confluence and (ob_zone is None or fvg_zone is None):
        return None

    zone = ob_zone
    if fvg_zone is not None and (zone is None or fvg_zone["index"] > zone["index"]):
        zone = fvg_zone

    if zone is None:
        return None

    top = zone["top"]
    bottom = zone["bottom"]

    if direction == "long":
        entry_price = top
        stop_loss = bottom * (1 - _STOP_BUFFER)
        risk = entry_price - stop_loss
    else:
        entry_price = bottom
        stop_loss = top * (1 + _STOP_BUFFER)
        risk = stop_loss - entry_price

    if risk <= 0:
        return None

    take_profit = entry_price + risk * _RR if direction == "long" else entry_price - risk * _RR
    rr = _RR

    if use_structure_tp:
        structure_target = _structure_take_profit_target(
            direction, entry_price, previous_swing_high, previous_swing_low, premium_discount
        )
        if structure_target is not None:
            reward = abs(structure_target - entry_price)
            take_profit = structure_target
            rr = reward / risk

    return {
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rr": rr,
        "zone": zone,
    }


def _structure_take_profit_target(
    direction: str,
    entry_price: float,
    previous_swing_high: dict | None,
    previous_swing_low: dict | None,
    premium_discount: dict | None,
) -> float | None:
    """Pick the further-from-entry (more favorable) of the previous swing
    high/low and premium/discount equilibrium, whichever are valid forward
    targets -- see `use_structure_tp`'s docstring above. Returns `None` if
    neither candidate is valid, so the caller can fall back to the
    fixed-`_RR` target.
    """
    candidates: list[float] = []

    if direction == "long":
        if previous_swing_high is not None and previous_swing_high["price"] > entry_price:
            candidates.append(previous_swing_high["price"])
        if premium_discount is not None and premium_discount["equilibrium"] > entry_price:
            candidates.append(premium_discount["equilibrium"])
        return max(candidates) if candidates else None

    if previous_swing_low is not None and previous_swing_low["price"] < entry_price:
        candidates.append(previous_swing_low["price"])
    if premium_discount is not None and premium_discount["equilibrium"] < entry_price:
        candidates.append(premium_discount["equilibrium"])
    return min(candidates) if candidates else None
