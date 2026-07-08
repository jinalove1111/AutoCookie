"""Abstract base exchange contract.

Real types-first contract for all future exchange implementations
(OKX, OrangeX, etc). No network calls happen here — this is a pure
interface definition.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseExchange(ABC):
    """Common interface every concrete exchange client must implement."""

    @abstractmethod
    def fetch_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> list[list[float]]:
        """Fetch OHLCV candles for a symbol/timeframe."""
        ...

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: float,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Place an order on the exchange and return the raw order response."""
        ...

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an existing order by id."""
        ...

    @abstractmethod
    def get_balance(self) -> dict[str, float]:
        """Return account balances keyed by asset."""
        ...

    @abstractmethod
    def get_open_positions(self) -> list[dict[str, Any]]:
        """Return the list of currently open positions."""
        ...
