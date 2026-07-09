"""
Milestone 2: real candle (OHLCV) fetching from OKX's PUBLIC market-data REST
endpoint. No authentication/API key is used or required — this only hits
OKX's public `/api/v5/market/candles` endpoint.

Symbol/timeframe conversion helpers translate the project's `.env` style
config (e.g. `BTCUSDT`, `5m`, `4h`) into OKX's expected wire format
(e.g. `BTC-USDT`, `5m`, `4H`).
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Optional

import httpx

from .data_normalizer import normalize_candles

OKX_PUBLIC_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"

# `/market/candles` only ever returns the most recent ~1440 candles
# regardless of pagination (confirmed empirically -- see
# fetch_ohlcv_history's docstring). `/market/history-candles` is OKX's
# separate endpoint for paging arbitrarily far back into older history,
# same request/response shape, same `after`/`before` cursor semantics.
OKX_HISTORY_CANDLES_URL = "https://www.okx.com/api/v5/market/history-candles"

# OKX caps `limit` at 300 per call for both of the above endpoints.
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


def timeframe_to_timedelta(timeframe: str) -> timedelta:
    """
    Convert a project-style timeframe (e.g. `5m`, `4h`, `1d`, `1w`) into
    the real-world duration of one candle, as a `timedelta`.

    Added to fix a real bug found while running a deep multi-period
    backtest: `scripts/run_backtest.py` was requesting the SAME candle
    COUNT for both the LTF and HTF fetch (`total_candles = --candles *
    --periods` for both), but a fixed candle count means wildly different
    real time spans across timeframes -- e.g. requesting 18000 candles at
    `4h` asks for ~8 years of history (vs. the ~187 days actually needed
    to match an 18000-candle `15m` LTF request), causing the HTF fetch to
    page through far more history than needed, taking many minutes and
    risking hitting `fetch_ohlcv_history`'s `max_pages` safety cap before
    ever getting real data back. Callers should instead size an HTF
    request off the REAL TIME SPAN the LTF request covers (see
    `scripts/run_backtest.py::_htf_candle_count_for_span`), using this
    helper to convert both timeframes' candle counts into comparable
    durations.
    """
    tf = timeframe.strip()
    if not tf:
        raise ValueError("timeframe must be a non-empty string")

    unit = tf[-1].lower()
    amount = tf[:-1]
    if not amount.isdigit():
        raise ValueError(f"Unsupported timeframe format: {timeframe!r}")
    amount = int(amount)

    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "w":
        return timedelta(weeks=amount)

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
        and passed as OKX's `after` param -- confirmed empirically (not
        assumed from docs alone) that `after=<ts>` returns candles OLDER
        than `ts` (paginating backward into history), while `before=<ts>`
        returns candles NEWER than `ts`. An earlier version of this method
        passed `since` to `before`, which silently could not page backward
        at all -- every caller requesting more than one page's worth of
        history got a shallower sample than requested with no error (see
        `fetch_ohlcv_history` below for the real deep-pagination path this
        enables).

        NOTE: OKX caps `limit` at 300 per call for this endpoint; requests
        for more are clamped to 300. `/market/candles` (used here) also
        has a hard total-history cap of ~1440 candles regardless of how
        many pages are fetched -- use `fetch_ohlcv_history` for real deep
        history.
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
            params["after"] = str(since)

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

    def fetch_ohlcv_history(
        self,
        symbol: str,
        timeframe: str,
        total_candles: int,
        page_limit: int = OKX_MAX_LIMIT,
        max_pages: int = 200,
        sleep_seconds: float = 0.25,
    ) -> list:
        """
        Assemble up to `total_candles` OHLCV candles for `symbol`/`timeframe`
        by paginating backward through OKX's `/market/history-candles`
        endpoint, sorted oldest -> newest.

        Why a separate endpoint/method rather than looping `fetch_ohlcv`:
        `/market/candles` (what `fetch_ohlcv` uses) has a hard total-history
        cap of ~1440 candles regardless of pagination -- confirmed
        empirically (not assumed): repeated `after`-cursor pagination
        against it returns an empty page after exactly 1440 candles, every
        time. `/market/history-candles` has the same request/response
        shape and the same `after=<ts>` (older-than-ts) cursor semantics,
        but pages back reliably far further -- confirmed empirically by
        paginating 3000 1H candles (~125 days) deep with no early cutoff.
        This is the real fix for the long-documented "backtest sample is
        shallower than requested" limitation (see prior
        `scripts/run_backtest.py` module docstring, now corrected).

        Returns candles capped at `total_candles` (may return FEWER if
        OKX's actual history for this instrument/timeframe genuinely runs
        out first, signaled by an empty or short page -- not an error, not
        retried). `max_pages` is an independent hard safety cap on the
        number of HTTP calls regardless of `total_candles`, protecting
        against a pagination bug turning into a runaway loop.
        `sleep_seconds` paces requests between pages to stay well under
        OKX's public rate limit for this endpoint.
        """
        if total_candles <= 0:
            return []

        okx_symbol = to_okx_symbol(symbol)
        okx_bar = to_okx_timeframe(timeframe)
        clamped_page_limit = min(page_limit, OKX_MAX_LIMIT)

        # Each entry is one page's candles, already normalized to
        # oldest->newest WITHIN that page. Pages themselves are collected
        # newest-page-first (each subsequent page strictly older than the
        # last) and reversed once at the end, rather than repeatedly
        # prepending to a single list on every iteration (O(n^2) for many
        # pages).
        pages: list[list] = []
        collected = 0
        after: str | None = None

        for _ in range(max_pages):
            if collected >= total_candles:
                break

            params: dict = {
                "instId": okx_symbol,
                "bar": okx_bar,
                "limit": str(clamped_page_limit),
            }
            if after is not None:
                params["after"] = after

            try:
                response = httpx.get(
                    OKX_HISTORY_CANDLES_URL, params=params, timeout=self._timeout
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ConnectionError(
                    "Failed to fetch historical OHLCV from OKX for "
                    f"{okx_symbol}/{okx_bar}: {exc}"
                ) from exc

            payload = response.json()
            if payload.get("code") != "0":
                raise RuntimeError(
                    f"OKX history-candles request failed for {okx_symbol}/{okx_bar}: "
                    f"code={payload.get('code')!r} msg={payload.get('msg')!r}"
                )

            raw_candles = payload.get("data", [])
            if not raw_candles:
                break  # genuinely out of history -- not an error

            page = normalize_candles(
                raw_candles, exchange="okx", symbol=symbol, timeframe=timeframe
            )
            pages.append(page)
            collected += len(page)

            # OKX returns each page newest-first, so raw_candles[-1] is the
            # oldest ts_ms in this page -- the correct cursor for the next
            # (older) page.
            after = raw_candles[-1][0]

            if len(raw_candles) < clamped_page_limit:
                break  # short page -- OKX is telling us this was the last one

            time.sleep(sleep_seconds)

        all_candles = [c for page in reversed(pages) for c in page]
        if len(all_candles) > total_candles:
            # Keep the NEWEST total_candles (trim excess from the oldest
            # end): all_candles is oldest->newest, so that's the tail slice.
            all_candles = all_candles[-total_candles:]
        return all_candles

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
