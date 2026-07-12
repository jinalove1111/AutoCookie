"""Jade Exit Point Engine.

Take-profit target logic for the Jade methodology -- the counterpart the
official Entry Point Engine spec (docs referenced in ENGINEERING_DECISIONS.md
#23) explicitly excludes: "It must NOT implement: Take Profit Logic...".
This module is that separate, standalone piece, built the same way
`entry_point_engine.py` was: a parallel construct that reuses existing
detectors without modifying them, rather than extending
`entry_model.build_entry_model`'s existing (and differently-scoped)
`use_structure_tp` opt-in.

Determines ONLY take-profit target levels for an already-valid trade
(`direction` + `entry_price`, e.g. from `entry_point_engine.find_entry_point`).
Does NOT implement: entry logic, stop-loss placement, position sizing,
partial-exit percentage/portion splits (that remains Risk Engine /
`BacktestEngine`'s `use_partial_tp`/`PARTIAL_TP_PORTION` territory), or
live order execution.

No spec document defines Jade's exact exit methodology (unlike the Entry
Point Engine, which had one) -- per operator instruction (2026-07-12,
"if any ambiguity exists, implement the most reasonable ICT/Jade
interpretation and document it in ENGINEERING_DECISIONS.md"), this
module's design decisions are recorded there under entry #24.
"""

from __future__ import annotations

from .entry_model import _STOP_BUFFER
from .liquidity import detect_equal_highs, detect_equal_lows
from .market_structure import find_previous_swing_high, find_previous_swing_low
from .premium_discount import calculate_premium_discount


def find_exit_targets(candles: list, direction: str, entry_price: float) -> dict:
    """Compute ranked take-profit targets for a trade already known to be
    valid (`direction`/`entry_price` are trusted inputs -- this function
    does not judge entry validity, only finds targets).

    Candidate sources (see ENGINEERING_DECISIONS.md #24 for the full
    rationale), each included only when it's a genuine forward target
    (strictly beyond `entry_price` in the trade's favor):

    - Equal High / Equal Low (`detect_equal_highs`/`detect_equal_lows`):
      the nearest resting liquidity pool -- standard ICT/SMC "price is
      drawn toward the next liquidity" concept, the same source Entry
      Model 2 (Liquidity Raid) already uses as an ENTRY trigger; here
      it's the mirror use as an EXIT magnet.
    - Previous swing high/low (`find_previous_swing_high`/
      `find_previous_swing_low`).
    - Premium/discount equilibrium (`calculate_premium_discount`).
    - The opposite extreme of the current premium/discount range (a full
      range round-trip target, beyond equilibrium).

    Every valid candidate is returned, not just the nearest -- ranked
    `TP1` (nearest) to `TPn` (farthest), sorted by distance from
    `entry_price`. Each target's `level` has `entry_model._STOP_BUFFER`
    applied INWARD (short of the raw level, not beyond it) -- standard
    ICT practice: price reversing exactly AT a liquidity level without
    fully trading through it is common, so a take-profit sitting fully
    at or past the raw level routinely misses fills that a level just
    short of it would have caught. `raw_level` (the unbuffered price)
    is also included for callers that want it.

    Returns `{"direction", "entry_price", "targets": [...]}` -- `targets`
    is `[]`, never `None`, when no candidate qualifies (this function
    never rejects the trade; it only ever reports what it found).
    """
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")

    candidates: list[tuple[float, str, str]] = []

    if direction == "long":
        for zone in detect_equal_highs(candles):
            if zone["level"] > entry_price:
                candidates.append(
                    (zone["level"], "equal_highs", f"equal highs liquidity pool at {zone['level']}")
                )
    else:
        for zone in detect_equal_lows(candles):
            if zone["level"] < entry_price:
                candidates.append(
                    (zone["level"], "equal_lows", f"equal lows liquidity pool at {zone['level']}")
                )

    if direction == "long":
        previous_high = find_previous_swing_high(candles)
        if previous_high is not None and previous_high["price"] > entry_price:
            candidates.append(
                (previous_high["price"], "previous_swing_high",
                 f"previous swing high at {previous_high['price']}")
            )
    else:
        previous_low = find_previous_swing_low(candles)
        if previous_low is not None and previous_low["price"] < entry_price:
            candidates.append(
                (previous_low["price"], "previous_swing_low",
                 f"previous swing low at {previous_low['price']}")
            )

    premium_discount = calculate_premium_discount(candles)
    if premium_discount is not None:
        equilibrium = premium_discount["equilibrium"]
        if direction == "long":
            if equilibrium > entry_price:
                candidates.append(
                    (equilibrium, "equilibrium", f"premium/discount equilibrium at {equilibrium}")
                )
            if premium_discount["top"] > entry_price:
                candidates.append(
                    (premium_discount["top"], "range_extreme",
                     f"opposite extreme of the current range at {premium_discount['top']}")
                )
        else:
            if equilibrium < entry_price:
                candidates.append(
                    (equilibrium, "equilibrium", f"premium/discount equilibrium at {equilibrium}")
                )
            if premium_discount["bottom"] < entry_price:
                candidates.append(
                    (premium_discount["bottom"], "range_extreme",
                     f"opposite extreme of the current range at {premium_discount['bottom']}")
                )

    candidates.sort(key=lambda c: c[0] if direction == "long" else -c[0])

    targets = []
    for i, (level, source, reason) in enumerate(candidates, start=1):
        buffered_level = level * (1 - _STOP_BUFFER) if direction == "long" else level * (1 + _STOP_BUFFER)
        targets.append({
            "label": f"TP{i}",
            "level": buffered_level,
            "raw_level": level,
            "source": source,
            "reason": reason,
        })

    return {"direction": direction, "entry_price": entry_price, "targets": targets}
