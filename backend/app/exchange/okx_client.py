"""OKX exchange client.

Milestone 37 (Priority 1, Phase 0 of `docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md`):
implements the BaseExchange contract's READ-ONLY methods
(`fetch_ohlcv`/`get_balance`/`get_open_positions`) against OKX's real v5
REST API, with the private (authenticated) request/signing plumbing built
and tested against mocked HTTP responses only -- no real network call has
ever been made by this module or its tests. `place_order`/`cancel_order`
remain `NotImplementedError` on purpose: they are Phase 1 scope (a
separate approval gate in the roadmap), not implemented here.

Authentication scheme confirmed against OKX's own v5 API docs (not
guessed) at implementation time: `OK-ACCESS-KEY` / `OK-ACCESS-SIGN`
(base64 HMAC-SHA256 of `timestamp + method + requestPath + body`) /
`OK-ACCESS-TIMESTAMP` (ISO-8601 UTC, millisecond precision, `Z` suffix) /
`OK-ACCESS-PASSPHRASE` headers on every private call, plus
`x-simulated-trading: 1` to route a request at OKX's demo-trading
environment instead of real capital -- omitted entirely for real trading,
never sent as `"0"`.

This class alone does not place this platform on OKX in any way: nothing
in `scripts/run_paper.py` or any other live-trading path imports or
constructs an `OkxClient` yet -- that wiring is explicit Phase 2 scope,
its own approval gate. Constructing this client with real credentials
and calling `get_balance()`/`get_open_positions()` against OKX's demo
endpoint (Phase 0's actual "readiness" step) still requires operator-
supplied `OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSPHRASE` values,
which this milestone does not have and does not fabricate.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.data.candle_fetcher import CandleFetcher

from .base_exchange import BaseExchange

OKX_BASE_URL = "https://www.okx.com"
OKX_BALANCE_PATH = "/api/v5/account/balance"
OKX_POSITIONS_PATH = "/api/v5/account/positions"

# Applied only to the new private (authenticated) read calls this module
# adds -- deliberately NOT applied to CandleFetcher's existing public-data
# fetch_ohlcv call, which this class delegates to unmodified (see
# docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md section 6: CandleFetcher's
# own retry gap is a real, separately-flagged issue, not silently folded
# into this change).
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.2


class OkxAuthError(RuntimeError):
    """Raised when a private OKX call is attempted without credentials configured."""


class OkxClient(BaseExchange):
    """OKX-specific implementation of the BaseExchange contract (Phase 0: read-only)."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        passphrase: str | None = None,
        demo: bool = True,
        timeout: float = 10.0,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_base_delay_seconds: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
    ) -> None:
        # Fail-closed toward demo, mirroring LIVE_TRADING_ENABLED's existing
        # "must deliberately opt in" pattern -- see module docstring and
        # docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md section 2.
        self._api_key = api_key if api_key is not None else settings.OKX_API_KEY
        self._api_secret = api_secret if api_secret is not None else settings.OKX_API_SECRET
        self._passphrase = passphrase if passphrase is not None else settings.OKX_API_PASSPHRASE
        self._demo = demo
        self._timeout = timeout
        self._retry_attempts = retry_attempts
        self._retry_base_delay_seconds = retry_base_delay_seconds

    def _has_credentials(self) -> bool:
        return bool(self._api_key and self._api_secret and self._passphrase)

    @staticmethod
    def _timestamp() -> str:
        """ISO-8601 UTC, millisecond precision, `Z` suffix -- OKX's required format."""
        return (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        prehash = f"{timestamp}{method.upper()}{request_path}{body}"
        digest = hmac.new(
            self._api_secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _private_headers(self, method: str, request_path: str, body: str = "") -> dict[str, str]:
        if not self._has_credentials():
            # Never echo partial/empty credential state into the message --
            # docs/api_keys_security.md's "must never appear in logs, error
            # messages, stack traces" rule applies to this new call site too.
            raise OkxAuthError(
                "OkxClient: private endpoint called without OKX_API_KEY/"
                "OKX_API_SECRET/OKX_API_PASSPHRASE configured."
            )
        timestamp = self._timestamp()
        headers = {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": self._sign(timestamp, method, request_path, body),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
            "Content-Type": "application/json",
        }
        if self._demo:
            headers["x-simulated-trading"] = "1"
        return headers

    def _private_get(self, request_path_with_query: str) -> dict[str, Any]:
        """GET a private OKX endpoint (path + query string already combined,
        matching what OKX's signing scheme expects as `requestPath`), with a
        small bounded retry/backoff on transient HTTP errors -- read
        operations are safe to retry (idempotent by construction, no
        capital at risk on this Phase-0 read-only path)."""
        last_exc: Exception | None = None
        for attempt in range(self._retry_attempts):
            headers = self._private_headers("GET", request_path_with_query)
            try:
                response = httpx.get(
                    f"{OKX_BASE_URL}{request_path_with_query}",
                    headers=headers,
                    timeout=self._timeout,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < self._retry_attempts - 1:
                    time.sleep(self._retry_base_delay_seconds * (2**attempt))
                    continue
                raise ConnectionError(
                    f"Failed to reach OKX private endpoint {request_path_with_query}: {exc}"
                ) from exc

            payload = response.json()
            if payload.get("code") != "0":
                raise RuntimeError(
                    f"OKX private request failed for {request_path_with_query}: "
                    f"code={payload.get('code')!r} msg={payload.get('msg')!r}"
                )
            return payload

        # Unreachable in practice (the loop above always returns or raises),
        # kept only to satisfy static analysis of the return type.
        raise ConnectionError(
            f"Failed to reach OKX private endpoint {request_path_with_query}: {last_exc}"
        )

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV candles from OKX's public market-data endpoint.

        Delegates to the already-working, already-tested `CandleFetcher`
        rather than reimplementing candle fetching -- per
        docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md Phase 0: "fetch_ohlcv
        delegates to the already-working CandleFetcher." Public endpoint,
        no authentication needed or used. Returns the same normalized
        candle-dict shape CandleFetcher already returns everywhere else in
        this codebase (BaseExchange's `list[list[float]]` type hint
        predates this implementation and does not reflect the project's
        actual candle schema; not changed here to avoid touching the
        shared abstract contract for an unrelated reason).
        """
        return CandleFetcher(timeout=self._timeout).fetch_ohlcv(symbol, timeframe, limit=limit)

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: float,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Place an order on OKX. Phase 1 scope (its own approval gate) -- not implemented."""
        raise NotImplementedError(
            "OkxClient.place_order is Phase 1 scope "
            "(docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md); not implemented in Phase 0."
        )

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an existing OKX order by id. Phase 1 scope -- not implemented."""
        raise NotImplementedError(
            "OkxClient.cancel_order is Phase 1 scope "
            "(docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md); not implemented in Phase 0."
        )

    def get_balance(self) -> dict[str, float]:
        """Return OKX account balances keyed by asset (real, authenticated call).

        Calls GET /api/v5/account/balance and parses the nested
        `details[].{ccy,availBal}` shape OKX's v5 API documents into a
        flat `{ccy: available_balance}` dict.
        """
        payload = self._private_get(OKX_BALANCE_PATH)
        data = payload.get("data", [])
        balances: dict[str, float] = {}
        for account in data:
            for detail in account.get("details", []):
                ccy = detail.get("ccy")
                avail_bal = detail.get("availBal")
                if ccy is None or avail_bal is None:
                    continue
                balances[ccy] = float(avail_bal)
        return balances

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Return the list of currently open OKX positions (real, authenticated call).

        Calls GET /api/v5/account/positions and returns OKX's raw
        per-position dicts unmodified (translation into this project's own
        position/trade schema is Phase 1+ scope, alongside order-lifecycle
        wiring -- see docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md section 4).
        """
        payload = self._private_get(OKX_POSITIONS_PATH)
        return payload.get("data", [])

    def get_exchange_name(self) -> str:
        return "okx"
