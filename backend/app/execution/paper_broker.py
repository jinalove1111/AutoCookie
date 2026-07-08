"""Paper broker.

Part of the Execution layer. Simulates fills for entry/SL/TP without
touching a real exchange. No real HTTP/exchange calls anywhere in this
module.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

# Unfavorable slippage applied to simulated entry fills (~0.02%).
SLIPPAGE_PERCENT = 0.0002

# Simulated flat taker fee percent applied to fills.
FEE_PERCENT = 0.05


class PaperBroker:
    """Simulated broker matching the future live broker's interface shape."""

    def fill_entry(self, signal) -> dict:
        """Simulate filling an entry order for `signal`.

        `signal` is duck-typed (e.g. a TradeSignal dataclass) and must
        expose at least: symbol, direction ("long"/"short"), entry_price,
        stop_loss, take_profit. This module does not import or depend on
        the strategy package.
        """
        direction = getattr(signal, "direction", None)
        entry_price = getattr(signal, "entry_price")

        if direction == "long":
            fill_price = entry_price * (1 + SLIPPAGE_PERCENT)
        else:
            # "short" (or any non-"long" direction): unfavorable = lower fill
            fill_price = entry_price * (1 - SLIPPAGE_PERCENT)

        return {
            "order_id": uuid.uuid4().hex,
            "fill_price": fill_price,
            "fee_percent": FEE_PERCENT,
            "filled_at": datetime.now(timezone.utc),
        }

    def check_exit(self, position: dict, current_price: float) -> dict | None:
        """Check whether `current_price` triggers a stop-loss or take-profit
        exit for `position`. Returns None if neither is triggered.

        `position` must expose at least: direction, stop_loss, take_profit.
        """
        direction = position.get("direction")
        stop_loss = position.get("stop_loss")
        take_profit = position.get("take_profit")

        if direction == "long":
            if current_price <= stop_loss:
                return {"exit_price": stop_loss, "reason": "stop_loss"}
            if current_price >= take_profit:
                return {"exit_price": take_profit, "reason": "take_profit"}
            return None

        # "short" (mirrored): stop_loss is above entry, take_profit below.
        if current_price >= stop_loss:
            return {"exit_price": stop_loss, "reason": "stop_loss"}
        if current_price <= take_profit:
            return {"exit_price": take_profit, "reason": "take_profit"}
        return None
