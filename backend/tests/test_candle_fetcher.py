"""Tests for app.data.candle_fetcher: symbol/timeframe conversion (pure,
no network) and OKX pagination (network mocked via a fake httpx.get --
`fetch_ohlcv_history` didn't exist before this round; nothing in this
module had ANY test coverage previously, verified only via live manual
runs against the real OKX API).

The mocked responses mirror OKX's real documented + empirically-confirmed
shape/ordering (see candle_fetcher.py's own docstrings, which record the
exact empirical pagination probe this suite's fakes are modeled on):
newest-first within a page, `after=<ts>` returns strictly older records.
"""

from __future__ import annotations

import pytest

from datetime import timedelta

from app.data.candle_fetcher import (
    OKX_HISTORY_CANDLES_URL,
    OKX_MAX_LIMIT,
    OKX_PUBLIC_CANDLES_URL,
    CandleFetcher,
    timeframe_to_timedelta,
    to_okx_symbol,
    to_okx_timeframe,
)

# --- Pure conversion helpers (no network) -----------------------------------


def test_to_okx_symbol_splits_known_quote_currencies():
    assert to_okx_symbol("BTCUSDT") == "BTC-USDT"
    assert to_okx_symbol("ethusdc") == "ETH-USDC"


def test_to_okx_symbol_passes_through_already_hyphenated():
    assert to_okx_symbol("BTC-USDT") == "BTC-USDT"


def test_to_okx_symbol_raises_for_unknown_quote():
    with pytest.raises(ValueError, match="Could not determine base/quote"):
        to_okx_symbol("BTCXYZ")


def test_to_okx_timeframe_lowercase_for_sub_hour():
    assert to_okx_timeframe("5m") == "5m"
    assert to_okx_timeframe("1m") == "1m"


def test_to_okx_timeframe_uppercase_for_hour_and_above():
    assert to_okx_timeframe("4h") == "4H"
    assert to_okx_timeframe("1d") == "1D"
    assert to_okx_timeframe("1w") == "1W"


def test_to_okx_timeframe_raises_for_bad_format():
    with pytest.raises(ValueError, match="Unsupported timeframe format"):
        to_okx_timeframe("abc")
    with pytest.raises(ValueError, match="Unsupported timeframe unit"):
        to_okx_timeframe("5x")


def test_timeframe_to_timedelta_converts_every_unit():
    assert timeframe_to_timedelta("15m") == timedelta(minutes=15)
    assert timeframe_to_timedelta("4h") == timedelta(hours=4)
    assert timeframe_to_timedelta("1d") == timedelta(days=1)
    assert timeframe_to_timedelta("2w") == timedelta(weeks=2)


def test_timeframe_to_timedelta_raises_for_bad_format():
    with pytest.raises(ValueError, match="Unsupported timeframe format"):
        timeframe_to_timedelta("abc")
    with pytest.raises(ValueError, match="Unsupported timeframe unit"):
        timeframe_to_timedelta("5x")


# --- Network-mocked pagination tests ----------------------------------------

_STEP_MS = 3_600_000  # 1H bar, matches OKX's ms-epoch ts convention
_BASE_MS = 1_800_000_000_000  # arbitrary fixed "now" for deterministic tests


def _raw_row(ts_ms: int) -> list:
    return [str(ts_ms), "100", "101", "99", "100.5", "10", "10", "10", "1"]


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _make_fake_history(total_available: int, limit_per_page: int = OKX_MAX_LIMIT):
    """Returns a fake `httpx.get` that serves `total_available` descending
    (newest-first) synthetic candles from OKX_HISTORY_CANDLES_URL, honoring
    `after`-cursor pagination exactly like the real endpoint (confirmed
    empirically): `after=<ts>` returns the next page of candles strictly
    older than `ts`, page size clamped to `limit`, an empty page once
    exhausted. Also records every call's params for assertions.
    """
    # Newest-first full history: index 0 is newest.
    all_ts_desc = [_BASE_MS - i * _STEP_MS for i in range(total_available)]
    calls: list[dict] = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params or {}))
        assert url == OKX_HISTORY_CANDLES_URL

        limit = int(params["limit"])
        after = params.get("after")
        if after is None:
            start_idx = 0
        else:
            after_ts = int(after)
            # First index whose ts is strictly older than after_ts.
            start_idx = next(
                (i for i, ts in enumerate(all_ts_desc) if ts < after_ts),
                len(all_ts_desc),
            )

        page_ts = all_ts_desc[start_idx : start_idx + limit]
        data = [_raw_row(ts) for ts in page_ts]
        return _FakeResponse({"code": "0", "msg": "", "data": data})

    return fake_get, calls


def test_fetch_ohlcv_history_assembles_multiple_pages_oldest_to_newest(monkeypatch):
    import app.data.candle_fetcher as candle_fetcher_module

    fake_get, calls = _make_fake_history(total_available=650)
    monkeypatch.setattr(candle_fetcher_module.httpx, "get", fake_get)

    candles = CandleFetcher().fetch_ohlcv_history(
        "BTCUSDT", "1h", total_candles=650, sleep_seconds=0
    )

    assert len(candles) == 650
    # Strictly oldest -> newest across the ENTIRE assembled series, not
    # just within a page -- the real regression this endpoint/method fixes.
    timestamps = [c["timestamp"] for c in candles]
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == 650  # no duplicates across page boundaries
    # 650 candles at 300/page requires 3 calls (300 + 300 + 50).
    assert len(calls) == 3
    assert "after" not in calls[0]
    assert calls[1]["after"] is not None
    assert calls[2]["after"] is not None


def test_fetch_ohlcv_history_stops_early_when_okx_history_runs_out(monkeypatch):
    """OKX genuinely has fewer candles than requested (e.g. a young listing)
    -- must return what's available, not error or hang.
    """
    import app.data.candle_fetcher as candle_fetcher_module

    fake_get, calls = _make_fake_history(total_available=120)
    monkeypatch.setattr(candle_fetcher_module.httpx, "get", fake_get)

    candles = CandleFetcher().fetch_ohlcv_history(
        "BTCUSDT", "1h", total_candles=1000, sleep_seconds=0
    )

    assert len(candles) == 120
    assert len(calls) == 1  # short page (120 < limit) ends pagination immediately


def test_fetch_ohlcv_history_trims_excess_to_the_newest_total_candles(monkeypatch):
    """900 requested with 300/page needs 3 full pages (900 available) --
    must return exactly 900, keeping the NEWEST 900 (nothing to trim here
    since it divides evenly, but this pins the "keep newest" contract via
    an uneven request below too).
    """
    import app.data.candle_fetcher as candle_fetcher_module

    fake_get, calls = _make_fake_history(total_available=1000)
    monkeypatch.setattr(candle_fetcher_module.httpx, "get", fake_get)

    candles = CandleFetcher().fetch_ohlcv_history(
        "BTCUSDT", "1h", total_candles=650, sleep_seconds=0
    )

    assert len(candles) == 650
    # The newest candle overall must be the actual newest available one
    # (index 0 of the fake's descending series -> _BASE_MS).
    from datetime import datetime, timezone

    assert candles[-1]["timestamp"] == datetime.fromtimestamp(
        _BASE_MS / 1000, tz=timezone.utc
    )


def test_fetch_ohlcv_history_zero_or_negative_returns_empty_without_a_call(monkeypatch):
    import app.data.candle_fetcher as candle_fetcher_module

    calls_made = []
    monkeypatch.setattr(
        candle_fetcher_module.httpx,
        "get",
        lambda *a, **k: calls_made.append(1),
    )

    assert CandleFetcher().fetch_ohlcv_history("BTCUSDT", "1h", total_candles=0) == []
    assert CandleFetcher().fetch_ohlcv_history("BTCUSDT", "1h", total_candles=-5) == []
    assert calls_made == []


def test_fetch_ohlcv_history_respects_max_pages_safety_cap(monkeypatch):
    """Even if total_candles is huge, max_pages independently bounds the
    number of HTTP calls -- a hard safety net against a pagination bug
    turning into a runaway loop."""
    import app.data.candle_fetcher as candle_fetcher_module

    fake_get, calls = _make_fake_history(total_available=100_000)
    monkeypatch.setattr(candle_fetcher_module.httpx, "get", fake_get)

    candles = CandleFetcher().fetch_ohlcv_history(
        "BTCUSDT", "1h", total_candles=100_000, max_pages=5, sleep_seconds=0
    )

    assert len(calls) == 5
    assert len(candles) == 5 * OKX_MAX_LIMIT


def test_fetch_ohlcv_since_param_now_sent_as_after_not_before(monkeypatch):
    """Regression pin for the exact bug fixed this round: `since` must map
    to OKX's `after` param (confirmed empirically to page backward/older),
    not `before` (confirmed empirically to page forward/newer, which
    silently could never deepen a historical sample).
    """
    import app.data.candle_fetcher as candle_fetcher_module

    captured_params = {}

    def fake_get(url, params=None, timeout=None):
        assert url == OKX_PUBLIC_CANDLES_URL
        captured_params.update(params or {})
        return _FakeResponse({"code": "0", "msg": "", "data": [_raw_row(_BASE_MS)]})

    monkeypatch.setattr(candle_fetcher_module.httpx, "get", fake_get)

    CandleFetcher().fetch_ohlcv("BTCUSDT", "1h", since=_BASE_MS, limit=10)

    assert captured_params.get("after") == str(_BASE_MS)
    assert "before" not in captured_params
