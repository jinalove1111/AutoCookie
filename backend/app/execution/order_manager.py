"""Order manager.

Part of the Execution layer. Places and manages entry, stop-loss, and
take-profit orders, including break-even moves and partial TP handling.
Delegates all actual fill/exit simulation to the broker it is constructed
with (duck-typed — any object exposing fill_entry/check_exit works).
"""

from __future__ import annotations

import copy


class OrderManager:
    """Manages the lifecycle of entry, SL, TP, and partial-close orders."""

    def __init__(self, broker) -> None:
        """`broker` is any object exposing fill_entry(signal) and
        check_exit(position, current_price) — duck-typed, not type-checked.
        """
        self.broker = broker

    def place_entry(self, signal) -> dict:
        """Place the entry order for an approved trade by delegating to the
        broker's fill simulation."""
        return self.broker.fill_entry(signal)

    def place_stop_loss(self, position: dict) -> None:
        """Place the stop-loss order for an open position.

        For brokers like PaperBroker, the stop-loss is enforced via
        check_exit rather than a standalone order, so this is a documented
        no-op that just logs. A real exchange broker would need a real
        order call here.
        """
        return None

    def place_take_profit(self, position: dict) -> None:
        """Place the take-profit order(s) for an open position.

        Same pattern as place_stop_loss: no-op/log only for brokers where
        TP is enforced via check_exit.
        """
        return None

    def move_to_breakeven(self, position: dict) -> dict:
        """Return a NEW position dict with stop_loss moved to the
        position's own entry_price. Does not mutate the input."""
        new_position = copy.copy(position)
        new_position["stop_loss"] = position.get("entry_price")
        return new_position

    def handle_partial_tp(self, position: dict, portion: float) -> dict:
        """Handle a partial take-profit close for `portion` (0 < portion < 1)
        of the position's size.

        Keeps a simple pnl calc against the position's entry_price and a
        current price (falls back to take_profit as a proxy if no current
        price field is present). This is a Milestone 3 simplification, not
        a full accounting system.
        """
        size = position.get("size", 1.0)
        entry_price = position.get("entry_price", 0.0)
        current_price = position.get("current_price", position.get("take_profit", entry_price))
        direction = position.get("direction")

        closed_size = size * portion
        remaining_size = size - closed_size

        if direction == "long":
            pnl_per_unit = current_price - entry_price
        else:
            pnl_per_unit = entry_price - current_price

        realized_pnl = pnl_per_unit * closed_size

        return {
            "closed_size": closed_size,
            "remaining_size": remaining_size,
            "realized_pnl": realized_pnl,
        }
