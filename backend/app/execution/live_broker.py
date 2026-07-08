"""Live broker stub.

Part of the Execution layer. Must never be invoked unless
config.is_live_trading_allowed is True. This class performs no safety
checks itself — callers are responsible for gating.
"""

from __future__ import annotations


class LiveBroker:
    """Real-money broker matching the paper broker's interface shape."""

    def place_order(self, *args, **kwargs):
        """Place a real order on the connected exchange."""
        raise NotImplementedError

    def cancel_order(self, order_id: str):
        """Cancel a previously placed real order."""
        raise NotImplementedError

    def get_balance(self):
        """Return the real account balance from the exchange."""
        raise NotImplementedError

    def get_open_positions(self):
        """Return the real list of currently open positions."""
        raise NotImplementedError
