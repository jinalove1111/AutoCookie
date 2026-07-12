"""Jade Trade Plan — composes the standalone Jade modules into one result.

`entry_point_engine`, `exit_point_engine`, and `htf_ltf_confluence` are
each independently built and independently tested (ENGINEERING_DECISIONS.md
#23/#24/#25), but until now had no caller connecting them -- a real
caller wanting a full trade plan (entry + targets + HTF confirmation)
had to invoke all three separately and stitch the results together
itself. `build_trade_plan` is that composition: it reuses all three
unmodified, in a fixed pipeline, and adds no detection logic of its own.

Deliberately still NOT wired into `SignalEngine`/paper trading -- same
"detection-only until a wiring decision is made deliberately" status as
every Jade module before it (see ENGINEERING_DECISIONS.md #23's
"Status" section). See ENGINEERING_DECISIONS.md #28 for why composition
happens here instead of inside `entry_point_engine.find_entry_point`
itself.
"""

from __future__ import annotations

from .entry_point_engine import find_entry_point
from .exit_point_engine import find_exit_targets
from .htf_ltf_confluence import evaluate_htf_ltf_confluence


def build_trade_plan(ltf_candles: list, htf_candles: list, bias: str) -> dict | None:
    """Build one full Jade trade plan, or `None` if no entry model finds
    a valid setup (`find_entry_point`'s own `None` case -- this function
    adds no additional rejection condition of its own).

    Pipeline (each step reuses its own module unmodified):
    1. `find_entry_point(ltf_candles, bias)` -- the entry candidate
       (direction, entry model, entry zone, stop loss, confidence, etc).
    2. `find_exit_targets(ltf_candles, direction, entry_price)` --
       take-profit targets, where `entry_price` is the entry zone's
       MIDPOINT (same convention `htf_ltf_confluence` already uses for
       the identical "a zone, but this function needs one price" need --
       see ENGINEERING_DECISIONS.md #25).
    3. `evaluate_htf_ltf_confluence(direction, entry_zone, htf_candles)`
       -- how much the HTF series confirms this specific entry.

    Returns the entry result dict (all of `find_entry_point`'s own
    fields, unchanged) with two additional keys: `exit_targets` (the
    list from `find_exit_targets`) and `htf_confluence` (the full dict
    from `evaluate_htf_ltf_confluence`).
    """
    entry = find_entry_point(ltf_candles, bias)
    if entry is None:
        return None

    entry_zone = entry["entry_zone"]
    entry_price = (entry_zone["top"] + entry_zone["bottom"]) / 2

    exit_targets = find_exit_targets(ltf_candles, entry["direction"], entry_price)["targets"]
    htf_confluence = evaluate_htf_ltf_confluence(entry["direction"], entry_zone, htf_candles)

    return {**entry, "exit_targets": exit_targets, "htf_confluence": htf_confluence}
