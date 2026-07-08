"""OKX exchange client stub.

Implements the BaseExchange contract for OKX. No real OKX SDK import and
no real API calls happen in this milestone.
"""

from __future__ import annotations

from typing import Any

from .base_exchange import BaseExchange


class OkxClient(BaseExchange):
    """OKX-specific implementation of the BaseExchange contract."""

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> list[list[float]]:
        """Fetch OHLCV candles from OKX for a symbol/timeframe."""
        raise NotImplementedError

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: float,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Place an order on OKX and return the raw order response."""
        raise NotImplementedError

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an existing OKX order by id."""
        raise NotImplementedError

    def get_balance(self) -> dict[str, float]:
        """Return OKX account balances keyed by asset."""
        raise NotImplementedError

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Return the list of currently open OKX positions."""
        raise NotImplementedError
