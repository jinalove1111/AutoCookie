"""OrangeX exchange client stub.

Implements the BaseExchange contract for OrangeX. No real OrangeX SDK
import and no real API calls happen in this milestone.
"""

from __future__ import annotations

from typing import Any

from .base_exchange import BaseExchange


class OrangexClient(BaseExchange):
    """OrangeX-specific implementation of the BaseExchange contract."""

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> list[list[float]]:
        """Fetch OHLCV candles from OrangeX for a symbol/timeframe."""
        raise NotImplementedError

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: float,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Place an order on OrangeX and return the raw order response."""
        raise NotImplementedError

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an existing OrangeX order by id."""
        raise NotImplementedError

    def get_balance(self) -> dict[str, float]:
        """Return OrangeX account balances keyed by asset."""
        raise NotImplementedError

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Return the list of currently open OrangeX positions."""
        raise NotImplementedError
