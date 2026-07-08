"""
Milestone 1 skeleton: live market data feed handler. Will manage exchange
websocket connections or live polling loops in a later milestone — no real
network connections are established here.
"""

from typing import Callable, Optional


class LiveFeed:
    """Handles a live market data feed (websocket or polling) for one exchange."""

    def connect(self) -> None:
        """Establish the live connection (websocket handshake or polling startup)."""
        raise NotImplementedError

    def disconnect(self) -> None:
        """Tear down the live connection and release any held resources."""
        raise NotImplementedError

    def subscribe(self, symbol: str, timeframe: str) -> None:
        """Subscribe to live candle updates for a given symbol/timeframe."""
        raise NotImplementedError

    def unsubscribe(self, symbol: str, timeframe: str) -> None:
        """Unsubscribe from live candle updates for a given symbol/timeframe."""
        raise NotImplementedError

    def on_candle(self, callback: Callable[[dict], None]) -> None:
        """Register a callback to be invoked whenever a new live candle arrives."""
        raise NotImplementedError

    def is_connected(self) -> bool:
        """Return whether the live feed connection is currently active."""
        raise NotImplementedError
