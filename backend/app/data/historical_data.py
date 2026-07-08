"""
Milestone 1 skeleton: storage/retrieval of historical candle data. Will read
from and write to the project's database layer (the `candles` table) once
that layer is wired up — no DB I/O happens yet.
"""

from typing import Optional


def save_candles(candles: list, symbol: str, timeframe: str, exchange: str) -> int:
    """Persist a batch of normalized candles to the database, returning rows written."""
    raise NotImplementedError


def load_candles(
    symbol: str,
    timeframe: str,
    exchange: str,
    start: Optional[int] = None,
    end: Optional[int] = None,
) -> list:
    """Load stored candles for a symbol/timeframe/exchange within an optional time range."""
    raise NotImplementedError


def delete_candles(symbol: str, timeframe: str, exchange: str) -> int:
    """Delete stored candles for a given symbol/timeframe/exchange, returning rows removed."""
    raise NotImplementedError


def get_latest_stored_timestamp(symbol: str, timeframe: str, exchange: str) -> Optional[int]:
    """Return the timestamp of the most recently stored candle, or None if absent."""
    raise NotImplementedError
