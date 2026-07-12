"""Jade HTF/LTF Confluence Rules.

Scores how much a real, higher-timeframe candle series confirms an LTF
entry candidate (e.g. from `entry_point_engine.find_entry_point`) --
"does the bigger picture agree with this trade, and how much." Same
parallel-module pattern as `entry_point_engine.py`/`exit_point_engine.py`:
reuses existing detectors against a SEPARATE `htf_candles` series rather
than duplicating logic, and does not modify `bias.py`/`SignalEngine`
(which already do their own, narrower HTF/LTF separation for bias only
-- see docs/strategy_spec.md section 1).

No spec document defines Jade's exact HTF/LTF confluence rules; per
operator instruction (2026-07-12: "if any ambiguity exists, implement
the most reasonable ICT/Jade interpretation and document it in
ENGINEERING_DECISIONS.md instead of waiting for approval"), the design
below is that interpretation -- see ENGINEERING_DECISIONS.md #25 for the
full rationale.
"""

from __future__ import annotations

from .exit_point_engine import find_exit_targets
from .fvg import detect_fair_value_gap
from .order_block import detect_order_block
from .premium_discount import calculate_premium_discount


def evaluate_htf_ltf_confluence(direction: str, entry_zone: dict, htf_candles: list) -> dict:
    """Score HTF confirmation for an LTF entry candidate. Purely
    informational/scoring -- like `entry_point_engine`'s displacement
    ranking, this NEVER rejects a setup; it reports what genuinely
    aligns and what doesn't, leaving any accept/reject threshold to
    whatever consumes this output.

    `entry_zone` is the LTF candidate's `{"top", "bottom"}` (e.g. from
    `find_entry_point`'s `entry_zone` field). `htf_candles` must be a
    genuinely distinct, real higher-timeframe series (per
    docs/strategy_spec.md section 1's HTF/LTF-separation rule) -- this
    function does not itself derive or validate that separation, same
    as `SignalEngine.generate_signal`'s own trusted-input convention.

    Three checks, each reusing an existing detector called on
    `htf_candles` (see ENGINEERING_DECISIONS.md #25 for why these three):

    1. `htf_premium_discount_alignment`: the LTF direction must not sit
       on the WRONG half of the HTF premium/discount range (a long is
       fine from HTF discount or equilibrium, wrong from HTF premium --
       same rule `entry_model`'s `require_premium_discount_filter`
       already applies, here applied against the HTF series specifically
       instead of the LTF one).
    2. `htf_pd_array_overlap`: the LTF entry zone overlaps a real,
       direction-matching HTF Order Block or HTF Fair Value Gap
       (`detect_order_block`/`detect_fair_value_gap` on `htf_candles`) --
       standard ICT "HTF PD array" confluence: an LTF zone sitting
       inside a genuine HTF zone of the same kind is a materially
       stronger setup than one that doesn't.
    3. `htf_liquidity_draw`: real HTF liquidity exists beyond this entry
       to be drawn toward -- reuses `exit_point_engine.find_exit_targets`
       directly against `htf_candles`, at the entry zone's midpoint; a
       non-empty target list means real HTF liquidity (previous HTF
       swing high/low, HTF equal highs/lows, HTF premium/discount
       equilibrium/extreme) actually exists to draw price toward.

    Returns `{"direction", "confluence_score" (0-3, count of checks that
    passed), "checks" (per-check booleans), "reasons"}`.
    """
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")

    checks: dict[str, bool] = {}
    reasons: list[str] = []

    premium_discount = calculate_premium_discount(htf_candles)
    wrong_zone = "premium" if direction == "long" else "discount"
    pd_aligned = premium_discount is not None and premium_discount["zone"] != wrong_zone
    checks["htf_premium_discount_alignment"] = pd_aligned
    if pd_aligned:
        reasons.append(
            f"HTF range zone is {premium_discount['zone']}, aligned with a {direction}"
        )

    wanted_type = "bullish" if direction == "long" else "bearish"
    overlap = False
    htf_order_block = detect_order_block(htf_candles)
    if htf_order_block is not None and htf_order_block["type"] == wanted_type:
        if htf_order_block["bottom"] <= entry_zone["top"] and htf_order_block["top"] >= entry_zone["bottom"]:
            overlap = True
            reasons.append(
                f"LTF entry zone overlaps an HTF order block "
                f"[{htf_order_block['bottom']}, {htf_order_block['top']}]"
            )
    if not overlap:
        for zone in detect_fair_value_gap(htf_candles):
            if zone["type"] != wanted_type:
                continue
            if zone["bottom"] <= entry_zone["top"] and zone["top"] >= entry_zone["bottom"]:
                overlap = True
                reasons.append(
                    f"LTF entry zone overlaps an HTF FVG [{zone['bottom']}, {zone['top']}]"
                )
                break
    checks["htf_pd_array_overlap"] = overlap

    entry_price = (entry_zone["top"] + entry_zone["bottom"]) / 2
    htf_targets = find_exit_targets(htf_candles, direction, entry_price)["targets"]
    liquidity_draw = len(htf_targets) > 0
    checks["htf_liquidity_draw"] = liquidity_draw
    if liquidity_draw:
        reasons.append(f"HTF liquidity draw exists: {htf_targets[0]['reason']}")

    return {
        "direction": direction,
        "confluence_score": sum(checks.values()),
        "checks": checks,
        "reasons": reasons,
    }
