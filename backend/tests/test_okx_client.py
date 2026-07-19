"""Tests for app.exchange.okx_client.OkxClient (Milestone 37, Phase 0).

Every test here mocks httpx.get / CandleFetcher directly -- no test in
this file makes, or is capable of making, a real network call to OKX.
Auth/signing correctness is checked against an independently
hand-computed HMAC-SHA256 value, not by re-deriving it through the same
code path being tested.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import httpx
import pytest

from app.exchange import okx_client as okx_client_module
from app.exchange.okx_client import OkxAuthError, OkxClient


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://www.okx.com/fake")
            raise httpx.HTTPStatusError(
                "error", request=request, response=httpx.Response(self.status_code, request=request)
            )

    def json(self) -> dict:
        return self._json_data


# --- Signing correctness (independent hand-computation) --------------------


def test_sign_matches_independently_computed_hmac_sha256_base64():
    client = OkxClient(api_key="k", api_secret="s3cr3t", passphrase="p", demo=True)
    timestamp = "2026-07-19T12:00:00.000Z"
    method = "GET"
    request_path = "/api/v5/account/balance"

    actual = client._sign(timestamp, method, request_path, body="")

    prehash = f"{timestamp}{method}{request_path}"
    expected_digest = hmac.new(b"s3cr3t", prehash.encode("utf-8"), hashlib.sha256).digest()
    expected = base64.b64encode(expected_digest).decode("utf-8")

    assert actual == expected


def test_timestamp_format_is_iso8601_utc_milliseconds_with_z_suffix():
    ts = OkxClient._timestamp()
    assert ts.endswith("Z")
    assert "T" in ts
    assert "+" not in ts  # normalized to Z, not left as +00:00


# --- Header construction -----------------------------------------------


def test_private_headers_includes_all_four_required_okx_headers():
    client = OkxClient(api_key="mykey", api_secret="mysecret", passphrase="mypass", demo=True)
    headers = client._private_headers("GET", "/api/v5/account/balance")

    assert headers["OK-ACCESS-KEY"] == "mykey"
    assert headers["OK-ACCESS-PASSPHRASE"] == "mypass"
    assert "OK-ACCESS-SIGN" in headers
    assert "OK-ACCESS-TIMESTAMP" in headers


def test_private_headers_sets_simulated_trading_header_when_demo():
    client = OkxClient(api_key="k", api_secret="s", passphrase="p", demo=True)
    headers = client._private_headers("GET", "/api/v5/account/balance")
    assert headers["x-simulated-trading"] == "1"


def test_private_headers_omits_simulated_trading_header_when_not_demo():
    client = OkxClient(api_key="k", api_secret="s", passphrase="p", demo=False)
    headers = client._private_headers("GET", "/api/v5/account/balance")
    assert "x-simulated-trading" not in headers


def test_private_headers_raises_without_leaking_credential_state_when_missing():
    client = OkxClient(api_key="real-key-value", api_secret="real-secret-value", passphrase="", demo=True)
    with pytest.raises(OkxAuthError) as exc_info:
        client._private_headers("GET", "/api/v5/account/balance")
    message = str(exc_info.value)
    assert "real-key-value" not in message
    assert "real-secret-value" not in message


def test_get_balance_raises_okx_auth_error_without_credentials():
    client = OkxClient(api_key="", api_secret="", passphrase="", demo=True)
    with pytest.raises(OkxAuthError):
        client.get_balance()


# --- get_balance / get_open_positions parsing --------------------------


def test_get_balance_parses_nested_details_into_flat_ccy_dict(monkeypatch):
    fake_payload = {
        "code": "0",
        "data": [
            {
                "details": [
                    {"ccy": "USDT", "availBal": "1234.56"},
                    {"ccy": "BTC", "availBal": "0.5"},
                ]
            }
        ],
    }

    def fake_get(url, headers=None, timeout=None):
        assert "OK-ACCESS-KEY" in headers
        return _FakeResponse(fake_payload)

    monkeypatch.setattr(okx_client_module.httpx, "get", fake_get)

    client = OkxClient(api_key="k", api_secret="s", passphrase="p", demo=True)
    balances = client.get_balance()

    assert balances == {"USDT": 1234.56, "BTC": 0.5}


def test_get_open_positions_returns_raw_data_list(monkeypatch):
    fake_positions = [{"instId": "BTC-USDT-SWAP", "pos": "1.0"}]
    fake_payload = {"code": "0", "data": fake_positions}

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(fake_payload)

    monkeypatch.setattr(okx_client_module.httpx, "get", fake_get)

    client = OkxClient(api_key="k", api_secret="s", passphrase="p", demo=True)
    positions = client.get_open_positions()

    assert positions == fake_positions


def test_private_get_raises_runtime_error_on_nonzero_okx_response_code(monkeypatch):
    fake_payload = {"code": "50111", "msg": "Invalid OK-ACCESS-KEY"}

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(fake_payload)

    monkeypatch.setattr(okx_client_module.httpx, "get", fake_get)

    client = OkxClient(api_key="k", api_secret="s", passphrase="p", demo=True)
    with pytest.raises(RuntimeError, match="50111"):
        client.get_balance()


# --- Retry/backoff on transient HTTP errors -----------------------------


def test_private_get_retries_transient_http_errors_then_succeeds(monkeypatch):
    monkeypatch.setattr(okx_client_module.time, "sleep", lambda _seconds: None)

    call_count = {"n": 0}
    fake_payload = {"code": "0", "data": []}

    def fake_get(url, headers=None, timeout=None):
        call_count["n"] += 1
        if call_count["n"] < 3:
            request = httpx.Request("GET", url)
            raise httpx.ConnectError("boom", request=request)
        return _FakeResponse(fake_payload)

    monkeypatch.setattr(okx_client_module.httpx, "get", fake_get)

    client = OkxClient(
        api_key="k", api_secret="s", passphrase="p", demo=True, retry_attempts=3
    )
    result = client.get_balance()

    assert result == {}
    assert call_count["n"] == 3


def test_private_get_raises_connection_error_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(okx_client_module.time, "sleep", lambda _seconds: None)

    def fake_get(url, headers=None, timeout=None):
        request = httpx.Request("GET", url)
        raise httpx.ConnectError("boom", request=request)

    monkeypatch.setattr(okx_client_module.httpx, "get", fake_get)

    client = OkxClient(
        api_key="k", api_secret="s", passphrase="p", demo=True, retry_attempts=3
    )
    with pytest.raises(ConnectionError):
        client.get_balance()


# --- fetch_ohlcv delegation to CandleFetcher ----------------------------


def test_fetch_ohlcv_delegates_to_candle_fetcher(monkeypatch):
    expected_candles = [{"symbol": "BTCUSDT", "close": 50000.0}]
    captured_args = {}

    class _FakeCandleFetcher:
        def __init__(self, timeout=10.0):
            captured_args["timeout"] = timeout

        def fetch_ohlcv(self, symbol, timeframe, limit=500):
            captured_args["symbol"] = symbol
            captured_args["timeframe"] = timeframe
            captured_args["limit"] = limit
            return expected_candles

    monkeypatch.setattr(okx_client_module, "CandleFetcher", _FakeCandleFetcher)

    client = OkxClient(api_key="k", api_secret="s", passphrase="p", timeout=7.5)
    result = client.fetch_ohlcv("BTCUSDT", "15m", limit=200)

    assert result == expected_candles
    assert captured_args == {
        "timeout": 7.5,
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "limit": 200,
    }


# --- Phase 0 scope boundary: place_order/cancel_order stay unimplemented ---


def test_place_order_raises_not_implemented_phase_1_scope():
    client = OkxClient(api_key="k", api_secret="s", passphrase="p")
    with pytest.raises(NotImplementedError, match="Phase 1"):
        client.place_order("BTCUSDT", "buy", "market", 0.01)


def test_cancel_order_raises_not_implemented_phase_1_scope():
    client = OkxClient(api_key="k", api_secret="s", passphrase="p")
    with pytest.raises(NotImplementedError, match="Phase 1"):
        client.cancel_order("BTCUSDT", "some-order-id")


def test_get_exchange_name_returns_okx():
    client = OkxClient(api_key="k", api_secret="s", passphrase="p")
    assert client.get_exchange_name() == "okx"


# --- Credentials default to Settings when not passed explicitly --------


def test_defaults_to_settings_credentials_when_not_passed(monkeypatch):
    monkeypatch.setattr(okx_client_module.settings, "OKX_API_KEY", "settings-key")
    monkeypatch.setattr(okx_client_module.settings, "OKX_API_SECRET", "settings-secret")
    monkeypatch.setattr(okx_client_module.settings, "OKX_API_PASSPHRASE", "settings-pass")

    client = OkxClient()
    headers = client._private_headers("GET", "/api/v5/account/balance")

    assert headers["OK-ACCESS-KEY"] == "settings-key"
    assert headers["OK-ACCESS-PASSPHRASE"] == "settings-pass"
