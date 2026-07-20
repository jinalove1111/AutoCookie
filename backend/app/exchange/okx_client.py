"""OKX exchange client.

Milestone 37 (Priority 1, Phase 0 of `docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md`):
implements the BaseExchange contract's READ-ONLY methods
(`fetch_ohlcv`/`get_balance`/`get_open_positions`) against OKX's real v5
REST API, with the private (authenticated) request/signing plumbing built
and tested against mocked HTTP responses only -- no real network call has
ever been made by this module or its tests.

Phase 1 (this addition): implements `place_order`/`cancel_order` (demo-
only order placement/cancellation) plus a new, OKX-specific
`get_order_status` method (not part of `BaseExchange`'s abstract
contract). Still tested against mocked HTTP responses only -- no real
network call is made by this module or its tests; the separate demo-
account verification step is out of scope for this change. Idempotency
(client-generated `clOrdId`, no blind retry on order-mutating POSTs, and
safe-no-op cancellation of an already-filled/canceled/nonexistent order)
follows `docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md` sections 3 and 6
-- see the per-method docstrings below for the specifics.

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
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.data.candle_fetcher import CandleFetcher, to_okx_symbol

from .base_exchange import BaseExchange

OKX_BASE_URL = "https://www.okx.com"
OKX_BALANCE_PATH = "/api/v5/account/balance"
OKX_POSITIONS_PATH = "/api/v5/account/positions"

# Phase 1 (order lifecycle) paths. Confirmed against OKX's real v5 API
# reference at implementation time, not guessed:
#   POST /api/v5/trade/order          -- place order
#   POST /api/v5/trade/cancel-order   -- cancel order
#   GET  /api/v5/trade/order          -- get order details (same path as
#                                         placement, different HTTP verb)
OKX_PLACE_ORDER_PATH = "/api/v5/trade/order"
OKX_CANCEL_ORDER_PATH = "/api/v5/trade/cancel-order"

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
    """OKX-specific implementation of the BaseExchange contract (Phase 0
    read-only methods plus Phase 1 order lifecycle: place/cancel/status)."""

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

    def _private_post(self, request_path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST a JSON body to a private OKX endpoint.

        The body is serialized to a string exactly once, and that same
        string is both signed (`_sign`'s `body` parameter, per OKX's
        `timestamp + method + requestPath + body` signing spec) and sent
        on the wire -- they must match byte-for-byte or OKX rejects the
        signature.

        Deliberately NO retry here, unlike `_private_get`. Per
        docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md section 6: a lost
        response to a POST that mutates exchange state (order placement,
        cancellation) is ambiguous -- the order may or may not have
        reached OKX -- so a blind retry risks a duplicate order/cancel.
        Safe retry would require checking order status first via
        `get_order_status`, which this phase does not wire up
        automatically. Do not "fix" this into a retry loop.
        """
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        headers = self._private_headers("POST", request_path, body_str)
        try:
            response = httpx.post(
                f"{OKX_BASE_URL}{request_path}",
                headers=headers,
                content=body_str,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ConnectionError(
                f"Failed to reach OKX private endpoint {request_path}: {exc}"
            ) from exc

        payload = response.json()
        if payload.get("code") != "0":
            raise RuntimeError(
                f"OKX private request failed for {request_path}: "
                f"code={payload.get('code')!r} msg={payload.get('msg')!r}"
            )
        return payload

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

    # Order-type mapping for `place_order`'s `order_type` -> OKX's `ordType`.
    _ORD_TYPE_MAP = {"limit": "limit", "market": "market"}

    # Per-order `sCode` values OKX's cancel-order endpoint returns when
    # there is nothing left to cancel (order doesn't exist / already
    # canceled / already fully filled). Confirmed against OKX's v5 order-
    # management error code reference (cancellation error range, 514xx).
    # Any of these must be a safe no-op (`False`), not a raised exception
    # -- docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md section 3.
    _CANCEL_NOOP_SCODES = {
        "51400",  # Cancellation failed as the order does not exist.
        "51401",  # Cancellation failed as the order is already canceled.
        "51402",  # Cancellation failed as the order is already completed (filled).
    }

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: float,
        price: float | None = None,
        client_order_id: str | None = None,
        td_mode: str = "cash",
    ) -> dict[str, Any]:
        """Place an order on OKX (Phase 1, demo-only in this session).

        POSTs `OKX_PLACE_ORDER_PATH`. `td_mode` defaults to `"cash"`
        (spot, no margin) -- matches this demo account's actual holdings
        (BTC/ETH/OKB/USDT spot balances, confirmed against real OKX demo
        data this session).

        Idempotency (docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md
        section 3, "the single most important correctness property of
        the entire order-lifecycle design"): if `client_order_id` is not
        supplied, one is generated here via `uuid.uuid4().hex` -- 32
        lowercase-hex characters, satisfying OKX's `clOrdId` constraint
        of up to 32 alphanumeric characters (confirmed against OKX's v5
        place-order docs) -- and always sent as `clOrdId`. This lets a
        retried/ambiguous request be matched back to the same intended
        order via `get_order_status` afterward, instead of risking a
        duplicate fill from a blind retry.

        No retry on failure: see `_private_post`'s docstring and roadmap
        section 6 -- a POST that mutates exchange state must not be
        blindly retried from here.
        """
        if order_type not in self._ORD_TYPE_MAP:
            raise ValueError(
                f"OkxClient.place_order: unsupported order_type {order_type!r} "
                f"(expected one of {sorted(self._ORD_TYPE_MAP)})"
            )

        used_client_order_id = (
            client_order_id if client_order_id is not None else uuid.uuid4().hex
        )

        body: dict[str, Any] = {
            "instId": to_okx_symbol(symbol),
            "tdMode": td_mode,
            "side": side,
            "ordType": self._ORD_TYPE_MAP[order_type],
            "sz": str(size),
            "clOrdId": used_client_order_id,
        }
        if order_type == "limit":
            if price is None:
                raise ValueError("OkxClient.place_order: price is required for limit orders")
            body["px"] = str(price)

        payload = self._private_post(OKX_PLACE_ORDER_PATH, body)
        data = payload.get("data", [])
        if not data:
            raise RuntimeError(
                f"OKX place_order returned no order data for "
                f"clOrdId={used_client_order_id!r}: {payload!r}"
            )

        result = dict(data[0])
        if result.get("sCode") != "0":
            raise RuntimeError(
                f"OKX place_order failed for clOrdId={used_client_order_id!r}: "
                f"sCode={result.get('sCode')!r} sMsg={result.get('sMsg')!r}"
            )
        # Ensure the clOrdId actually used is recoverable from the return
        # value even if OKX's echo were ever absent -- Phase 1's separate
        # verification script needs this to look up order status after.
        result.setdefault("clOrdId", used_client_order_id)
        return result

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an existing OKX order by id (Phase 1).

        POSTs `OKX_CANCEL_ORDER_PATH`. Idempotent per
        docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md section 3:
        cancelling an order that's already filled, already canceled, or
        unknown to OKX is a safe no-op (`False`), not a raised exception
        that would propagate as a pipeline failure. Genuinely unexpected
        errors (auth failure, network failure, malformed request) still
        raise -- those come from `_private_post`'s top-level `code` check
        or `OkxAuthError`/`ConnectionError`, unmodified here.
        """
        body = {"instId": to_okx_symbol(symbol), "ordId": order_id}
        payload = self._private_post(OKX_CANCEL_ORDER_PATH, body)
        data = payload.get("data", [])
        if not data:
            raise RuntimeError(
                f"OKX cancel_order returned no data for ordId={order_id!r}: {payload!r}"
            )

        result = data[0]
        s_code = result.get("sCode")
        if s_code == "0":
            return True
        if s_code in self._CANCEL_NOOP_SCODES:
            return False
        raise RuntimeError(
            f"OKX cancel_order failed for ordId={order_id!r}: "
            f"sCode={s_code!r} sMsg={result.get('sMsg')!r}"
        )

    def get_order_status(self, symbol: str, order_id: str) -> dict[str, Any]:
        """Return OKX's raw order-status dict for a given order (Phase 1).

        Not part of `BaseExchange`'s abstract contract -- an OKX-specific
        concrete addition (adding it to the shared abstract contract
        would force an unrelated change onto `OrangexClient`'s stub, out
        of scope here).

        GETs `OKX_PLACE_ORDER_PATH` (OKX v5 reuses the same path for
        POST-place and GET-status, confirmed against OKX's docs), reusing
        `_private_get` unmodified. Includes OKX's `state` field
        (`"live"`, `"filled"`, `"canceled"`, etc).
        """
        inst_id = to_okx_symbol(symbol)
        request_path = f"{OKX_PLACE_ORDER_PATH}?instId={inst_id}&ordId={order_id}"
        payload = self._private_get(request_path)
        data = payload.get("data", [])
        if not data:
            raise RuntimeError(
                f"OKX get_order_status returned no data for ordId={order_id!r}: {payload!r}"
            )
        return data[0]

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
