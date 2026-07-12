"""Jade Entry Point Engine (official specification, operator directive
2026-07-12).

Determines ONLY: Entry Direction, Entry Zone, Stop Loss, Entry Model,
Invalidation Level (plus Target Reference / Confidence Score / Reason
List / Reject Reason List, per the spec's OUTPUT section). Deliberately
does NOT implement: Take Profit Logic, Position Sizing, Risk Management,
Elliott Wave, CRT, Trendline Logic, Session Bias, Live Order Execution --
those are explicitly out of scope per the spec, not omissions.

This is a separate, parallel construct from `entry_model.build_entry_model`/
`SignalEngine` -- per the spec's "Implement ONLY the Entry Point Engine"
instruction, neither of those is modified. It reuses the same underlying
detectors (`order_block.py`, `fvg.py`, `liquidity.py`,
`premium_discount.py`, `market_structure.py`) rather than duplicating
their logic, composed under THIS spec's own rules, which differ from
`SignalEngine`'s in one deliberate, spec-mandated way: zone mitigation
(`app.strategy.utils.is_zone_mitigated`) is NOT applied here -- the spec
states "Repeated FVG tests do not invalidate the setup. Only the
invalidation level invalidates the trade," which directly conflicts with
`SignalEngine`'s mitigation filter. Intentional divergence, not an
oversight -- see each model's docstring below.

`bias` ("bullish"/"bearish"/"neutral") is a caller-supplied input to
every model here (e.g. from `bias.detect_htf_bias`), same convention as
`entry_model.build_entry_model` -- this engine does not compute bias
itself, since "Session Bias" is explicitly out of scope and directional
bias is a separate, already-existing concept.
"""

from __future__ import annotations

from .entry_model import _STOP_BUFFER
from .fvg import detect_fair_value_gap
from .liquidity import detect_equal_highs, detect_equal_lows
from .market_structure import detect_choch_mss, find_swing_highs, find_swing_lows
from .order_block import _IMPULSE_MULT, _LOOKBACK, _range, detect_breaker_block, detect_order_block
from .premium_discount import calculate_premium_discount
from .utils import cf

# Displacement-scoring thresholds (Entry Model 1's "Prefer Displacement-
# Formed Ranges" rule -- see `_displacement_strength`). Not spec-specified
# numerically (the spec states the 5 criteria qualitatively, not with
# exact thresholds); reasonable, disclosed-not-tuned defaults, same
# "disclosed default, not yet backtest-tuned" status `entry_model._RR`
# started at before its own eventual sweep.
_DOMINANT_CANDLE_RATIO = 0.4  # criterion 4: impulse candle's share of the move's total range
_MIN_BODY_RATIO = 0.5  # criterion 5: impulse candle's body as a fraction of its own range


def _last_candle_overlaps_zone(candles: list, top: float, bottom: float) -> bool:
    """True if the LAST candle's [low, high] range overlaps [bottom, top]
    -- "price is trading into the zone right now", the entry trigger
    condition for FVG/Order Block/Breaker Block below. Deliberately only
    the CURRENT candle (unlike `app.strategy.utils.is_zone_mitigated`,
    which deliberately EXCLUDES the current candle to check PRIOR
    mitigation) -- this is the opposite check, on purpose: this function
    asks "is this the retracement", not "was this zone already tested".
    """
    last = candles[-1]
    return cf(last, "high") >= bottom and cf(last, "low") <= top


def _candidate_dealing_ranges(candles: list, direction: str) -> list[tuple[int, int]]:
    """Enumerate candidate dealing ranges for Model 1's displacement
    ranking (operator spec, 2026-07-12): "Bullish range: Swing Low ->
    Swing High; Bearish range: Swing High -> Swing Low" (per the
    original Model 1 spec). Every confirmed swing point of the range's
    STARTING type is paired with EVERY confirmed swing point of the
    ENDING type that follows it chronologically -- not just the
    immediately-next one, since the displacement move that actually
    created a usable dealing range may have skipped over a smaller,
    intervening structural point (e.g. a swing low displacing all the
    way past an intermediate swing high to a much stronger, more recent
    one). "If multiple valid dealing ranges exist, always prefer the
    range created by the strongest displacement" (spec) presumes exactly
    this kind of multi-candidate set.

    Returns `(start_index, end_index)` pairs, `start_index < end_index`.
    """
    swing_highs = find_swing_highs(candles)
    swing_lows = find_swing_lows(candles)

    candidates: list[tuple[int, int]] = []
    if direction == "long":
        for low_idx in swing_lows:
            for high_idx in swing_highs:
                if high_idx > low_idx:
                    candidates.append((low_idx, high_idx))
    else:
        for high_idx in swing_highs:
            for low_idx in swing_lows:
                if low_idx > high_idx:
                    candidates.append((high_idx, low_idx))
    return candidates


def _displacement_strength(candles: list, start_index: int, end_index: int, direction: str) -> float | None:
    """Score the move from `candles[start_index]` to `candles[end_index]`
    against the spec's 5 displacement criteria (ALL must hold); returns
    a strength score (higher = stronger) if it qualifies, else `None`.
    "This rule is only used for ranking candidate dealing ranges. It
    must never reject a valid setup by itself" -- `None` here means
    "don't prefer this range", never "reject the setup"; the caller
    always still has the fallback (most recent confirmed swing range,
    `calculate_premium_discount`'s own existing behavior) available.

    1. Breaks market structure (BOS or CHOCH): a real, direction-matching
       CHOCH (`detect_choch_mss`, reused unmodified) confirmed at or
       before `end_index`, whose broken level is at or after
       `start_index` -- i.e. structure broke DURING this specific move,
       not from some unrelated earlier shift.
    2. Impulse candle(s) significantly larger than the recent average:
       reuses `order_block._IMPULSE_MULT`/`_LOOKBACK` unmodified -- the
       move's single largest-range candle must exceed `_IMPULSE_MULT`
       times the average candle range of the `_LOOKBACK` candles
       immediately BEFORE the move starts (same "impulse vs. recent
       volatility" concept `detect_order_block` already uses).
    3. Leaves at least one valid FVG: `detect_fair_value_gap` (reused
       unmodified) finds at least one direction-matching gap within the
       move's own candles.
    4. Not composed of multiple overlapping small candles: the move's
       largest-range candle must account for at least
       `_DOMINANT_CANDLE_RATIO` of the move's TOTAL price distance
       (high-to-low across every candle in the move) -- one candle
       dominating the move, not many small overlapping ones each
       contributing a little.
    5. Clearly represents aggressive buying/selling: the largest-range
       candle's body (`close - open`) must point in the move's direction
       AND be at least `_MIN_BODY_RATIO` of that candle's own range (a
       strong-bodied candle, not a big-wick indecision candle).
    """
    if end_index <= start_index:
        return None
    move = candles[start_index : end_index + 1]
    wanted_type = "bullish" if direction == "long" else "bearish"

    lookback_window = candles[max(0, start_index - _LOOKBACK) : start_index]
    if not lookback_window:
        return None
    avg_range = sum(_range(c) for c in lookback_window) / len(lookback_window)
    if avg_range <= 0:
        return None

    ranges = [_range(c) for c in move]
    impulse_pos = max(range(len(move)), key=lambda i: ranges[i])
    impulse_candle = move[impulse_pos]
    impulse_range = ranges[impulse_pos]

    # 2. impulse candle significantly larger than recent average.
    if impulse_range <= _IMPULSE_MULT * avg_range:
        return None

    # 4. one candle dominates the move, not many small overlapping ones.
    move_span = max(cf(c, "high") for c in move) - min(cf(c, "low") for c in move)
    if move_span <= 0 or impulse_range < _DOMINANT_CANDLE_RATIO * move_span:
        return None

    # 5. strong-bodied impulse candle in the expected direction.
    body = cf(impulse_candle, "close") - cf(impulse_candle, "open")
    if direction == "long" and body <= 0:
        return None
    if direction == "short" and body >= 0:
        return None
    if abs(body) < _MIN_BODY_RATIO * impulse_range:
        return None

    # 3. leaves at least one valid, direction-matching FVG.
    if not any(z["type"] == wanted_type for z in detect_fair_value_gap(move)):
        return None

    # 1. breaks market structure (BOS or CHOCH) during THIS move.
    wanted_choch_type = "bullish_choch" if direction == "long" else "bearish_choch"
    choch = detect_choch_mss(candles[: end_index + 1])
    if choch is None or choch["type"] != wanted_choch_type or choch["broken_index"] < start_index:
        return None

    return impulse_range / avg_range


def _evaluate_premium_discount(candles: list, bias: str) -> tuple[dict | None, str | None]:
    """Entry Model 1: Premium / Discount.

    Standing Limit Zone (operator decision, 2026-07-12): the entry zone
    always runs from Equilibrium (50%) to the extreme of the matching
    half of the range -- Equilibrium to the range low for a LONG
    (discount extreme), Equilibrium to the range high for a SHORT
    (premium extreme). The full zone is returned, not a single entry
    price -- callers place a limit order across it and let price come to
    them. Reuses `calculate_premium_discount` unmodified for the range/
    equilibrium math (see ROADMAP item #1 / docs/strategy_spec.md §8).

    Current Price Gating (operator decision, 2026-07-12): this model
    NEVER rejects a setup because current price sits outside the entry
    zone -- the Entry Point Engine's job is only to identify a valid
    zone; whether/when price actually reaches it is the execution
    engine's concern, not this one's. (Unlike Models 3-5 below, which
    DO require the current candle to already be retracing into their
    zone -- those model an active retest, not a standing limit order.)

    Prefer Displacement-Formed Ranges (operator decision, 2026-07-12):
    among candidate dealing ranges (`_candidate_dealing_ranges`), the one
    created by the STRONGEST qualifying displacement move
    (`_displacement_strength`, all 5 spec criteria) is preferred over
    `calculate_premium_discount`'s own "most recent confirmed swing
    range". If no candidate qualifies, falls back to that most-recent
    range unchanged -- ranking-only, per spec: "It must never reject a
    valid setup by itself."
    """
    if bias not in ("bullish", "bearish"):
        return None, "bias is neutral or invalid"
    direction = "long" if bias == "bullish" else "short"

    pd = calculate_premium_discount(candles)
    if pd is None:
        return None, "no coherent current swing range"

    top, bottom = pd["top"], pd["bottom"]
    displacement_used = False
    best_score: float | None = None
    for start_idx, end_idx in _candidate_dealing_ranges(candles, direction):
        score = _displacement_strength(candles, start_idx, end_idx, direction)
        if score is None:
            continue
        if direction == "long":
            cand_bottom = cf(candles[start_idx], "low")
            cand_top = cf(candles[end_idx], "high")
        else:
            cand_top = cf(candles[start_idx], "high")
            cand_bottom = cf(candles[end_idx], "low")
        if cand_top <= cand_bottom:
            continue
        if best_score is None or score > best_score:
            best_score = score
            top, bottom = cand_top, cand_bottom
            displacement_used = True

    equilibrium = (top + bottom) / 2
    if direction == "long":
        entry_zone = {"top": equilibrium, "bottom": bottom}
        stop_loss = bottom * (1 - _STOP_BUFFER)
    else:
        entry_zone = {"top": top, "bottom": equilibrium}
        stop_loss = top * (1 + _STOP_BUFFER)

    reasons = [
        f"{direction} limit zone: "
        f"{'discount' if direction == 'long' else 'premium'} half of range "
        f"[{bottom}, {top}], equilibrium {equilibrium}"
    ]
    reasons.append(
        "range selected by strongest qualifying displacement move"
        if displacement_used
        else "no displacement-qualified range found; used most recent confirmed swing range"
    )

    return {
        "entry_model": "premium_discount",
        "direction": direction,
        "entry_zone": entry_zone,
        "stop_loss": stop_loss,
        "invalidation_level": stop_loss,
        "target_reference": None,
        "confidence_score": 4,
        "reasons": reasons,
    }, None


def _evaluate_liquidity_raid(candles: list, bias: str) -> tuple[dict | None, str | None]:
    """Entry Model 2: Liquidity Raid (Turtle Soup).

    Workflow per spec: Liquidity Sweep -> NO ENTRY -> Close Back Inside
    -> Rejection Confirmed -> Entry. Implemented as: the LAST candle
    wicks beyond a liquidity level and closes back on the other side
    (both conditions on the same candle -- a sweep alone, with no close
    back inside, is explicitly "NEVER an entry" per spec, so a bare wick
    with no reclaim produces no result here).

    Liquidity source: Equal High / Equal Low only (`detect_equal_highs`/
    `detect_equal_lows`, ROADMAP item #5) -- operator decision
    (2026-07-12): implement only the liquidity detectors that already
    exist in the codebase; do not build new ones yet. The other 5 of the
    spec's 7 listed sources are explicit TODOs, deferred pending real
    session/day/week timezone-boundary definitions this repo doesn't
    have yet (getting a session boundary wrong would silently produce a
    WRONG liquidity level, not a missing one, so these are deferred
    rather than guessed at):

    TODO: Previous Weekly High / Low
    TODO: Previous Daily High / Low
    TODO: Previous Session High / Low
    TODO: Asian High / Low
    TODO: London High / Low

    Target Reference ("opposite side of the range" per spec) uses
    `calculate_premium_discount`'s range (the same "current dealing
    range" concept Model 1 uses) as the best available "the range"
    referent, since the spec doesn't otherwise define which range.
    """
    if bias not in ("bullish", "bearish"):
        return None, "bias is neutral or invalid"
    direction = "long" if bias == "bullish" else "short"

    last = candles[-1]
    last_high = cf(last, "high")
    last_low = cf(last, "low")
    last_close = cf(last, "close")
    last_idx = len(candles) - 1

    level = None
    if direction == "long":
        for z in reversed(detect_equal_lows(candles)):
            if z["second_index"] >= last_idx:
                continue
            if last_low < z["level"] and last_close > z["level"]:
                level = z["level"]
                break
    else:
        for z in reversed(detect_equal_highs(candles)):
            if z["second_index"] >= last_idx:
                continue
            if last_high > z["level"] and last_close < z["level"]:
                level = z["level"]
                break

    if level is None:
        return None, "no confirmed equal-high/low liquidity sweep with a close back inside"

    if direction == "long":
        stop_loss = last_low * (1 - _STOP_BUFFER)
        entry_zone = {"top": level, "bottom": last_low}
    else:
        stop_loss = last_high * (1 + _STOP_BUFFER)
        entry_zone = {"top": last_high, "bottom": level}

    pd = calculate_premium_discount(candles)
    target_reference = (pd["top"] if direction == "long" else pd["bottom"]) if pd is not None else None

    return {
        "entry_model": "liquidity_raid",
        "direction": direction,
        "entry_zone": entry_zone,
        "stop_loss": stop_loss,
        "invalidation_level": stop_loss,
        "target_reference": target_reference,
        "confidence_score": 4,
        "reasons": [
            f"equal-{'lows' if direction == 'long' else 'highs'} liquidity swept at "
            f"{level}, closed back inside the range"
        ],
    }, None


_FVG_STOP_MODELS = ("aggressive", "moderate", "conservative")


def _evaluate_fair_value_gap(
    candles: list, bias: str, stop_model: str = "moderate"
) -> tuple[dict | None, str | None]:
    """Entry Model 3: Fair Value Gap.

    Reuses `detect_fair_value_gap` unmodified. Entry trigger is the LAST
    candle trading back into a matching, unmitigated-by-spec-definition
    gap (see `_last_candle_overlaps_zone`) -- "Do NOT wait for an
    additional confirmation candle" per spec, so no separate confirming
    bar is required beyond the retracement itself.

    Deliberately does NOT apply `app.strategy.utils.is_zone_mitigated`:
    "Repeated FVG tests do not invalidate the setup. Only the
    invalidation level invalidates the trade" -- an explicit spec
    instruction that directly conflicts with `SignalEngine`'s mitigation
    filter (see module docstring). A gap that's been tested multiple
    times before is still a valid entry here as long as price hasn't
    breached the invalidation level.

    Three stop models, each keyed off the zone's own `index` (the
    displacement/impulse candle -- `detect_fair_value_gap` sets `index`
    to the MIDDLE of its 3-candle window) and `index - 1` (the first
    candle, i.e. the candle whose high/low originally defined the gap):
    - aggressive: the gap boundary itself (`zone["top"]`/`zone["bottom"]`).
    - moderate: the displacement candle's low/high.
    - conservative: the first candle's low/high.
    `invalidation_level` is ALWAYS the conservative level regardless of
    which `stop_model` is chosen for `stop_loss` -- the spec's "only the
    invalidation level invalidates the trade" reads as a single, stable
    structural boundary independent of which (tighter) stop the trader
    chooses to actually risk against.
    """
    if bias not in ("bullish", "bearish"):
        return None, "bias is neutral or invalid"
    if stop_model not in _FVG_STOP_MODELS:
        raise ValueError(f"stop_model must be one of {_FVG_STOP_MODELS}, got {stop_model!r}")
    direction = "long" if bias == "bullish" else "short"
    wanted_type = "bullish" if direction == "long" else "bearish"

    matching = [z for z in detect_fair_value_gap(candles) if z["type"] == wanted_type]
    zone = None
    for z in sorted(matching, key=lambda z: z["index"], reverse=True):
        if _last_candle_overlaps_zone(candles, z["top"], z["bottom"]):
            zone = z
            break
    if zone is None:
        return None, "no matching fair value gap currently being retested"

    displacement_candle = candles[zone["index"]]
    first_candle = candles[zone["index"] - 1]

    if direction == "long":
        levels = {
            "aggressive": zone["bottom"],
            "moderate": cf(displacement_candle, "low"),
            "conservative": cf(first_candle, "low"),
        }
        buffer_mult = 1 - _STOP_BUFFER
    else:
        levels = {
            "aggressive": zone["top"],
            "moderate": cf(displacement_candle, "high"),
            "conservative": cf(first_candle, "high"),
        }
        buffer_mult = 1 + _STOP_BUFFER

    stop_loss = levels[stop_model] * buffer_mult
    invalidation_level = levels["conservative"] * buffer_mult

    return {
        "entry_model": "fair_value_gap",
        "direction": direction,
        "entry_zone": {"top": zone["top"], "bottom": zone["bottom"]},
        "stop_loss": stop_loss,
        "invalidation_level": invalidation_level,
        "target_reference": None,
        "confidence_score": 4,
        "reasons": [
            f"price trading back into a {wanted_type} FVG [{zone['bottom']}, {zone['top']}], "
            f"stop_model={stop_model}"
        ],
    }, None


def _evaluate_order_block(candles: list, bias: str) -> tuple[dict | None, str | None]:
    """Entry Model 4: Order Block.

    Reuses `detect_order_block` unmodified (its own docstring already
    defines "final opposite-colored candle before strong displacement",
    matching this spec's Order Block definition exactly). Entry trigger
    is the LAST candle retracing into the OB zone. Does NOT apply
    `is_zone_mitigated` -- same rationale as `_evaluate_fair_value_gap`
    (spec-mandated divergence from `SignalEngine`).

    Confidence: 5 (spec's "Order Block + FVG" tier) if the OB zone
    overlaps a matching-direction FVG, else 3 ("Order Block Only").
    """
    if bias not in ("bullish", "bearish"):
        return None, "bias is neutral or invalid"
    direction = "long" if bias == "bullish" else "short"
    wanted_type = "bullish" if direction == "long" else "bearish"

    ob = detect_order_block(candles)
    if ob is None or ob["type"] != wanted_type:
        return None, "no matching order block"

    if not _last_candle_overlaps_zone(candles, ob["top"], ob["bottom"]):
        return None, "price has not retraced into the order block yet"

    fvg_zones = [z for z in detect_fair_value_gap(candles) if z["type"] == wanted_type]
    overlaps_fvg = any(z["bottom"] <= ob["top"] and z["top"] >= ob["bottom"] for z in fvg_zones)

    if direction == "long":
        stop_loss = ob["bottom"] * (1 - _STOP_BUFFER)
    else:
        stop_loss = ob["top"] * (1 + _STOP_BUFFER)

    reasons = [f"price retraced into a matching order block [{ob['bottom']}, {ob['top']}]"]
    if overlaps_fvg:
        reasons.append("order block overlaps a matching FVG -- higher-probability confluence")

    return {
        "entry_model": "order_block",
        "direction": direction,
        "entry_zone": {"top": ob["top"], "bottom": ob["bottom"]},
        "stop_loss": stop_loss,
        "invalidation_level": stop_loss,
        "target_reference": None,
        "confidence_score": 5 if overlaps_fvg else 3,
        "reasons": reasons,
    }, None


_BREAKER_STOP_MODELS = ("aggressive", "conservative")


def _evaluate_breaker_block(
    candles: list, bias: str, stop_model: str = "aggressive"
) -> tuple[dict | None, str | None]:
    """Entry Model 5: Breaker Block.

    Reuses `detect_breaker_block` unmodified. Entry trigger is the LAST
    candle retracing into the breaker zone. Two stop models: aggressive
    (the breaker's own boundary) and conservative (extended to the far
    edge of an overlapping FVG, when one exists -- "additional breathing
    room" per spec). Does NOT apply `is_zone_mitigated`, same rationale
    as the other retracement-based models above.

    Confidence: 5 ("Breaker + FVG" tier) when the breaker overlaps a
    matching FVG, else 4 ("Breaker Only", no FVG overlap) -- operator
    decision (2026-07-12), resolving the spec priority table's silence
    on the no-overlap case.
    """
    if bias not in ("bullish", "bearish"):
        return None, "bias is neutral or invalid"
    if stop_model not in _BREAKER_STOP_MODELS:
        raise ValueError(f"stop_model must be one of {_BREAKER_STOP_MODELS}, got {stop_model!r}")
    direction = "long" if bias == "bullish" else "short"
    wanted_type = "bullish" if direction == "long" else "bearish"

    breaker = detect_breaker_block(candles)
    if breaker is None or breaker["type"] != wanted_type:
        return None, "no matching breaker block"

    if not _last_candle_overlaps_zone(candles, breaker["top"], breaker["bottom"]):
        return None, "price has not retraced into the breaker block yet"

    fvg_zones = [z for z in detect_fair_value_gap(candles) if z["type"] == wanted_type]
    overlapping_fvgs = [
        z for z in fvg_zones if z["bottom"] <= breaker["top"] and z["top"] >= breaker["bottom"]
    ]
    overlaps_fvg = bool(overlapping_fvgs)

    top, bottom = breaker["top"], breaker["bottom"]
    if overlaps_fvg:
        for z in overlapping_fvgs:
            top = max(top, z["top"])
            bottom = min(bottom, z["bottom"])

    if stop_model == "aggressive":
        stop_raw = breaker["bottom"] if direction == "long" else breaker["top"]
    else:
        stop_raw = bottom if direction == "long" else top

    stop_loss = stop_raw * (1 - _STOP_BUFFER) if direction == "long" else stop_raw * (1 + _STOP_BUFFER)

    reasons = [f"price retraced into a matching breaker block [{breaker['bottom']}, {breaker['top']}]"]
    if overlaps_fvg:
        reasons.append("breaker block overlaps a matching FVG -- additional breathing room applied")

    return {
        "entry_model": "breaker_block",
        "direction": direction,
        "entry_zone": {"top": top, "bottom": bottom},
        "stop_loss": stop_loss,
        "invalidation_level": stop_loss,
        "target_reference": None,
        "confidence_score": 5 if overlaps_fvg else 4,
        "reasons": reasons,
    }, None


def find_entry_point(
    candles: list,
    bias: str,
    fvg_stop_model: str = "moderate",
    breaker_stop_model: str = "aggressive",
) -> dict | None:
    """Evaluate all 5 Entry Models against `candles`/`bias` and return the
    highest-confidence valid entry, or `None` if none apply.

    Per the spec's OUTPUT section, the returned dict includes `direction`,
    `entry_model`, `entry_zone`, `stop_loss`, `invalidation_level`,
    `target_reference`, `confidence_score`, `reason_list` (why THIS model
    was chosen), and `reject_reason_list` (why every other model, checked
    but not chosen, was rejected or ranked lower) -- this last field is
    what makes `find_entry_point` an aggregator over all 5 models rather
    than a single-model check, per the spec's ENTRY PRIORITY table.
    """
    evaluators = (
        ("order_block", lambda: _evaluate_order_block(candles, bias)),
        ("breaker_block", lambda: _evaluate_breaker_block(candles, bias, breaker_stop_model)),
        ("liquidity_raid", lambda: _evaluate_liquidity_raid(candles, bias)),
        ("premium_discount", lambda: _evaluate_premium_discount(candles, bias)),
        ("fair_value_gap", lambda: _evaluate_fair_value_gap(candles, bias, fvg_stop_model)),
    )

    candidates: list[dict] = []
    reject_reasons: list[str] = []
    for name, evaluate in evaluators:
        result, reject_reason = evaluate()
        if result is not None:
            candidates.append(result)
        else:
            reject_reasons.append(f"{name}: {reject_reason}")

    if not candidates:
        return None

    best = max(candidates, key=lambda r: r["confidence_score"])
    for candidate in candidates:
        if candidate is not best:
            reject_reasons.append(
                f"{candidate['entry_model']}: lower confidence "
                f"({candidate['confidence_score']}) than chosen model "
                f"{best['entry_model']} ({best['confidence_score']})"
            )

    best["reason_list"] = best.pop("reasons")
    best["reject_reason_list"] = reject_reasons
    return best
