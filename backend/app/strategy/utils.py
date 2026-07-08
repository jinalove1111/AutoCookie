"""Shared candle-field accessor for the Strategy Engine sub-package.

Candles may arrive as plain dicts (the normal case, matching the `candles`
DB row) or as lightweight objects (e.g. ORM rows); this accessor lets every
detector in this package stay agnostic to the concrete candle type.
"""

from __future__ import annotations

from typing import Any


def cf(candle: Any, key: str) -> Any:
    """Read a single OHLCV field from a candle, whether dict-like or attribute-like."""
    if isinstance(candle, dict):
        return candle[key]
    return getattr(candle, key)
