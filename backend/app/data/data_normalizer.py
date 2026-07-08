"""
Normalizes raw, exchange-specific candle payloads into the project's
internal candle schema (matching the `candles` DB table: symbol, timeframe,
timestamp, open, high, low, close, volume, exchange).

Milestone 2: implemented against OKX's public candles REST response shape:
    ["ts_ms", "open", "high", "low", "close", "vol", "volCcy", "volCcyQuote", "confirm"]
OKX returns candles newest-first; `normalize_candles` reverses them to the
project convention of oldest-first.
"""

from __future__ import annotations

from datetime import datetime, timezone

REQUIRED_CANDLE_FIELDS = (
    "symbol",
    "timeframe",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "exchange",
)


def normalize_candle(raw: list, exchange: str, symbol: str, timeframe: str) -> dict:
    """
    Convert one raw OKX candle array into the internal candle schema dict.

    `raw` is expected in OKX's documented order:
    [ts_ms, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    Only the first 6 fields are required/used.
    """
    if raw is None or len(raw) < 6:
        raise ValueError(f"raw candle must have at least 6 fields, got: {raw!r}")

    ts_ms, o, h, l, c, vol = raw[0], raw[1], raw[2], raw[3], raw[4], raw[5]

    timestamp = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": timestamp,
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": float(vol),
        "exchange": exchange,
    }


def normalize_candles(
    raw_list: list, exchange: str, symbol: str, timeframe: str
) -> list:
    """
    Convert a list of raw OKX candle arrays into internal schema dicts,
    sorted oldest -> newest (OKX returns them newest-first, so we reverse).
    """
    normalized = [
        normalize_candle(raw, exchange=exchange, symbol=symbol, timeframe=timeframe)
        for raw in raw_list
    ]
    normalized.reverse()
    return normalized


def validate_candle_schema(candle: dict) -> bool:
    """Check that a normalized candle dict contains all required schema fields."""
    return all(field in candle for field in REQUIRED_CANDLE_FIELDS)
