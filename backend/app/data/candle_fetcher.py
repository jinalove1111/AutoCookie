"""
Milestone 2: real candle (OHLCV) fetching from OKX's PUBLIC market-data REST
endpoint. No authentication/API key is used or required — this only hits
OKX's public `/api/v5/market/candles` endpoint.

Symbol/timeframe conversion helpers translate the project's `.env` style
config (e.g. `BTCUSDT`, `5m`, `4h`) into OKX's expected wire format
(e.g. `BTC-USDT`, `5m`, `4H`).
"""

from __future__ import annotations

from typing import Optional

import httpx

from .data_normalizer import normalize_candles

OKX_PUBLIC_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"

# OKX caps `limit` at 300 per call for this endpoint.
OKX_MAX_LIMIT = 300

# Known quote currencies used to split a concatenated symbol like BTCUSDT
# into base/quote for OKX's hyphenated instId format (e.g. BTC-USDT).
KNOWN_QUOTE_CURRENCIES = ("USDT", "USDC", "USD", "BTC", "ETH")


def to_okx_symbol(symbol: str) -> str:
    """
    Convert a project-style symbol (e.g. `BTCUSDT`) into OKX's hyphenated
    instId format (e.g. `BTC-USDT`).

    If the symbol already contains a hyphen, it is returned unchanged
    (assumed to already be in OKX format).
    """
    if "-" in symbol:
        return symbol.upper()

    upper_symbol = symbol.upper()
    for quote in KNOWN_QUOTE_CURRENCIES:
        if upper_symbol.endswith(quote) and len(upper_symbol) > len(quote):
            base = upper_symbol[: -len(quote)]
            return f"{base}-{quote}"

    raise ValueError(
        f"Could not determine base/quote split for symbol {symbol!r}; "
        f"expected it to end with one of {KNOWN_QUOTE_CURRENCIES} or already "
        f"contain a hyphen."
    )


def to_okx_timeframe(timeframe: str) -> str:
    """
    Convert a project-style timeframe (e.g. `5m`, `4h`, `1d`) into OKX's
    `bar` parameter format (e.g. `5m`, `4H`, `1D`).

    OKX uses lowercase for sub-hour bars (`1m`, `3m`, `5m`, `15m`, `30m`)
    and an uppercase unit letter for hour-and-above bars (`1H`, `4H`, `1D`,
    `1W`, `1M`).
    """
    tf = timeframe.strip()
    if not tf:
        raise ValueError("timeframe must be a non-empty string")

    unit = tf[-1].lower()
    amount = tf[:-1]
    if not amount.isdigit():
        raise ValueError(f"Unsupported timeframe format: {timeframe!r}")

    if unit == "m":
        return f"{amount}m"
    if unit in ("h", "d", "w"):
        return f"{amount}{unit.upper()}"

    raise ValueError(f"Unsupported timeframe unit in {timeframe!r}: {unit!r}")


class CandleFetcher:
    """Fetches real OHLCV candle data from OKX's public market-data REST API."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None,
        limit: int = 500,
    ) -> list:
        """
        Fetch OHLCV candles for a symbol/timeframe from OKX's public REST
        endpoint, normalize them into the internal candle schema, and
        return them sorted oldest -> newest.

        `since` (if provided) is treated as a millisecond epoch timestamp
        and passed as OKX's `before` param (fetch candles after this ts,
        per OKX's semantics of returning records earlier than `after` /
        newer than `before`). Left as an optional passthrough since OKX's
        pagination semantics for this endpoint are cursor-based, not a
        simple `since`.

        NOTE: OKX caps `limit` at 300 per call for this endpoint; requests
        for more are clamped to 300.
        """
        okx_symbol = to_okx_symbol(symbol)
        okx_bar = to_okx_timeframe(timeframe)
        clamped_limit = min(limit, OKX_MAX_LIMIT)

        params: dict = {
            "instId": okx_symbol,
            "bar": okx_bar,
            "limit": str(clamped_limit),
        }
        if since is not None:
            params["before"] = str(since)

        try:
            response = httpx.get(
                OKX_PUBLIC_CANDLES_URL, params=params, timeout=self._timeout
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ConnectionError(
                f"Failed to fetch OHLCV from OKX for {okx_symbol}/{okx_bar}: {exc}"
            ) from exc

        payload = response.json()
        if payload.get("code") != "0":
            raise RuntimeError(
                f"OKX candles request failed for {okx_symbol}/{okx_bar}: "
                f"code={payload.get('code')!r} msg={payload.get('msg')!r}"
            )

        raw_candles = payload.get("data", [])
        return normalize_candles(
            raw_candles, exchange="okx", symbol=symbol, timeframe=timeframe
        )

    def fetch_latest(self, symbol: str, timeframe: str) -> Optional[dict]:
        """Fetch the single most recent candle for a symbol/timeframe."""
        candles = self.fetch_ohlcv(symbol, timeframe, limit=1)
        return candles[-1] if candles else None

    def get_supported_timeframes(self) -> list:
        """Return the list of timeframe strings this fetcher/exchange supports."""
        return ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]

    def get_exchange_name(self) -> str:
        """Return the identifying name of the exchange this fetcher targets."""
        return "okx"
