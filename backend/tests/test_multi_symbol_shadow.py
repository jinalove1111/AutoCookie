"""Tests for `scripts/run_paper.py`'s Milestone 17a multi-symbol shadow
collection (`_maybe_record_extra_symbol_shadow_passes` and its wiring into
`_maybe_record_shadow_pass`) -- see docs/REGIME_PERFORMANCE_ANALYSIS.md
(evidence accumulation identified as this platform's binding constraint)
and app/config.py's `SHADOW_SYMBOLS` docstring for the full motivation.

`scripts/` is a sibling directory to `backend/`, not a package under it --
added to `sys.path` explicitly here, same convention `test_shadow_status.py`
/ `test_run_backtest.py` already established (only TEST files reach across
that boundary, never production `app` code).

Every DB-touching name `run_paper` calls at runtime (`CandleFetcher`,
`detect_market_regime`, `record_shadow_pass`, `resolve_open_shadow_
signals`) is monkeypatched at the module-attribute level in every test
below (the same pattern `test_shadow_recorder.py` uses for
`shadow_recorder.all_strategies`) -- these tests prove the CALL-SITE
wiring (which symbols get fetched/resolved/recorded, with what
`active_strategy_name`, and that one symbol's failure never blocks
another's), not `shadow_recorder`/`shadow_resolver`'s own internals
(already covered by `test_shadow_recorder.py`/`test_shadow_resolver.py`).
Real DB/model coverage of `record_shadow_pass`/`resolve_open_shadow_signals`
is intentionally out of scope for this module (owned elsewhere; not to be
duplicated here).

`run_paper` itself, however, imports `app.portfolio.journal` (and
transitively `app.database.session`) at MODULE level, which constructs a
real SQLAlchemy engine bound to `settings.DATABASE_URL` at IMPORT time
(see `conftest.py`'s module docstring) -- it cannot simply be imported
once at this file's module level like `test_shadow_status.py`/
`test_run_backtest.py` do for their much lighter scripts. `run_paper` is
therefore (re-)imported FRESH inside the `run_paper_module` fixture below,
after `conftest.py`'s `fresh_app_env` fixture has pointed `DATABASE_URL`
at an isolated per-test temp sqlite file and purged every cached `app.*`
module -- this guarantees a syntactically valid, always-isolated URL
regardless of collection order or the ambient environment, and, combined
with every DB-touching call being monkeypatched away, guarantees this
module never reaches -- let alone writes to -- `backend/paper_
validation.db` (a live paper trader may be running against it).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# A lightweight stand-in for `app.regime.regime_detector.MarketRegime`.
# Every test here monkeypatches `record_shadow_pass`/`resolve_open_shadow_
# signals`/`detect_market_regime` themselves, so nothing downstream ever
# actually inspects this object's shape -- it only needs to be a stable,
# comparable identity passed through the call chain untouched.
_FAKE_REGIME = object()


@pytest.fixture()
def run_paper_module(fresh_app_env):
    """Import `run_paper` fresh, bound to this test's isolated temp
    sqlite DB (see module docstring). `fresh_app_env` (from `conftest.py`)
    already purges every cached `app.*` module and points `DATABASE_URL`
    at a brand-new temp file; `run_paper` itself is popped from
    `sys.modules` here too (conftest's purge only covers `app`/`app.*`
    names, not this sibling-directory script) so its own `from app.config
    import settings` import re-binds to the fresh module, not a
    previous test's cached instance.
    """
    sys.modules.pop("run_paper", None)
    import run_paper as _run_paper

    yield _run_paper
    sys.modules.pop("run_paper", None)


def _candles(symbol: str, n: int = 3) -> list[dict]:
    return [
        {
            "timestamp": datetime(2026, 7, 16, 0, i, 0, tzinfo=timezone.utc),
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "volume": 10.0,
            "symbol": symbol,
        }
        for i in range(n)
    ]


def _make_fake_candle_fetcher(call_log: list, raise_for=(), empty_for=()):
    """Build a fake `CandleFetcher` replacement class. `call_log` collects
    `(symbol, timeframe, limit)` for every `fetch_ohlcv` call across every
    instance (mirroring `CandleFetcher()` being constructed fresh per call
    in `run_paper.py`). `raise_for`/`empty_for` simulate a per-symbol fetch
    failure / an empty-candles response, respectively.
    """
    raise_for = set(raise_for)
    empty_for = set(empty_for)

    class _FakeCandleFetcher:
        def fetch_ohlcv(self, symbol, timeframe, limit=300):
            call_log.append((symbol, timeframe, limit))
            if symbol in raise_for:
                raise RuntimeError(f"simulated fetch failure for {symbol}")
            if symbol in empty_for:
                return []
            return _candles(symbol)

    return _FakeCandleFetcher


def _install_default_record_and_resolve(monkeypatch, rp, record_calls=None, resolve_calls=None):
    """Wire simple, non-raising fakes for `record_shadow_pass`/
    `resolve_open_shadow_signals` that log their call args (symbol +
    active_strategy_name / symbol) into the provided lists.
    """
    record_calls = record_calls if record_calls is not None else []
    resolve_calls = resolve_calls if resolve_calls is not None else []

    def fake_record(symbol, timeframe, ltf_candles, htf_candles, regime, active_strategy_name):
        record_calls.append((symbol, active_strategy_name))
        return {
            "snapshot_written": True,
            "shadow_signals_written": 2,
            "strategies_evaluated": 5,
            "errors": 0,
        }

    def fake_resolve(symbol, candles):
        resolve_calls.append(symbol)
        return {
            "examined": 1,
            "resolved_tp": 0,
            "resolved_sl": 0,
            "expired": 0,
            "still_open": 1,
        }

    monkeypatch.setattr(rp, "record_shadow_pass", fake_record)
    monkeypatch.setattr(rp, "resolve_open_shadow_signals", fake_resolve)
    return record_calls, resolve_calls


# --- (a) SHADOW_SYMBOLS empty -> zero extra fetch/record calls ---


def test_empty_shadow_symbols_makes_zero_extra_calls(run_paper_module, monkeypatch):
    rp = run_paper_module
    monkeypatch.setattr(rp.settings, "SYMBOL", "BTCUSDT")
    monkeypatch.setattr(rp.settings, "SHADOW_SYMBOLS", "")

    call_log: list = []
    monkeypatch.setattr(rp, "CandleFetcher", _make_fake_candle_fetcher(call_log))
    monkeypatch.setattr(rp, "detect_market_regime", lambda candles: _FAKE_REGIME)
    record_calls, resolve_calls = _install_default_record_and_resolve(monkeypatch, rp)

    result = rp._maybe_record_extra_symbol_shadow_passes()

    assert result == {}
    assert call_log == []
    assert record_calls == []
    assert resolve_calls == []


# --- (b) three extra symbols -> per-symbol resolver+recorder called ---


def test_three_extra_symbols_all_processed(run_paper_module, monkeypatch):
    rp = run_paper_module
    monkeypatch.setattr(rp.settings, "SYMBOL", "BTCUSDT")
    monkeypatch.setattr(rp.settings, "SHADOW_SYMBOLS", "ETHUSDT,SOLUSDT,XRPUSDT")
    monkeypatch.setattr(rp.settings, "DEFAULT_TIMEFRAME", "5m")
    monkeypatch.setattr(rp.settings, "HTF_TIMEFRAME", "4h")

    call_log: list = []
    monkeypatch.setattr(rp, "CandleFetcher", _make_fake_candle_fetcher(call_log))
    monkeypatch.setattr(rp, "detect_market_regime", lambda candles: _FAKE_REGIME)
    record_calls, resolve_calls = _install_default_record_and_resolve(monkeypatch, rp)

    result = rp._maybe_record_extra_symbol_shadow_passes()

    assert set(result.keys()) == {"ETHUSDT", "SOLUSDT", "XRPUSDT"}
    for symbol in ("ETHUSDT", "SOLUSDT", "XRPUSDT"):
        assert result[symbol]["snapshot_written"] is True
        assert result[symbol]["shadow_signals_written"] == 2
        assert result[symbol]["resolution"] == {
            "examined": 1,
            "resolved_tp": 0,
            "resolved_sl": 0,
            "expired": 0,
            "still_open": 1,
        }

    # Every extra symbol is shadow-evaluated with NO strategy excluded
    # (active_strategy_name=None -- see _maybe_record_extra_symbol_shadow_
    # passes's docstring for why None correctly means "exclude none"
    # against record_shadow_pass's `strategy_name == active_strategy_name`
    # contract).
    assert set(record_calls) == {
        ("ETHUSDT", None),
        ("SOLUSDT", None),
        ("XRPUSDT", None),
    }
    assert set(resolve_calls) == {"ETHUSDT", "SOLUSDT", "XRPUSDT"}

    # Two fetches (LTF + HTF) per symbol, fresh -- not reused from the
    # active symbol's own candles.
    assert len(call_log) == 6
    assert {c[0] for c in call_log} == {"ETHUSDT", "SOLUSDT", "XRPUSDT"}
    assert {c[1] for c in call_log} == {"5m", "4h"}


# --- (c) one symbol's fetch raising -> WARN path, others still processed ---


def test_one_symbol_fetch_failure_is_isolated(run_paper_module, monkeypatch, capsys):
    rp = run_paper_module
    monkeypatch.setattr(rp.settings, "SYMBOL", "BTCUSDT")
    monkeypatch.setattr(rp.settings, "SHADOW_SYMBOLS", "ETHUSDT,SOLUSDT,XRPUSDT")
    monkeypatch.setattr(rp.settings, "DEFAULT_TIMEFRAME", "5m")
    monkeypatch.setattr(rp.settings, "HTF_TIMEFRAME", "4h")

    call_log: list = []
    monkeypatch.setattr(
        rp, "CandleFetcher", _make_fake_candle_fetcher(call_log, raise_for={"SOLUSDT"})
    )
    monkeypatch.setattr(rp, "detect_market_regime", lambda candles: _FAKE_REGIME)
    record_calls, resolve_calls = _install_default_record_and_resolve(monkeypatch, rp)

    result = rp._maybe_record_extra_symbol_shadow_passes()

    assert set(result.keys()) == {"ETHUSDT", "SOLUSDT", "XRPUSDT"}
    assert "error" in result["SOLUSDT"]
    assert result["ETHUSDT"]["snapshot_written"] is True
    assert result["XRPUSDT"]["snapshot_written"] is True

    # The failing symbol never reaches resolve/record; the other two do.
    assert set(record_calls) == {("ETHUSDT", None), ("XRPUSDT", None)}
    assert set(resolve_calls) == {"ETHUSDT", "XRPUSDT"}

    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "SOLUSDT" in captured.out


# --- (d) symbol equal to active symbol is skipped ---


def test_active_symbol_is_skipped(run_paper_module, monkeypatch):
    rp = run_paper_module
    monkeypatch.setattr(rp.settings, "SYMBOL", "BTCUSDT")
    monkeypatch.setattr(rp.settings, "SHADOW_SYMBOLS", "BTCUSDT,ETHUSDT")
    monkeypatch.setattr(rp.settings, "DEFAULT_TIMEFRAME", "5m")
    monkeypatch.setattr(rp.settings, "HTF_TIMEFRAME", "4h")

    call_log: list = []
    monkeypatch.setattr(rp, "CandleFetcher", _make_fake_candle_fetcher(call_log))
    monkeypatch.setattr(rp, "detect_market_regime", lambda candles: _FAKE_REGIME)
    record_calls, resolve_calls = _install_default_record_and_resolve(monkeypatch, rp)

    result = rp._maybe_record_extra_symbol_shadow_passes()

    assert set(result.keys()) == {"ETHUSDT"}
    assert all(symbol != "BTCUSDT" for symbol, _tf, _limit in call_log)
    assert all(symbol != "BTCUSDT" for symbol, _active in record_calls)
    assert "BTCUSDT" not in resolve_calls


# --- (e) whitespace/empty entries tolerated ---


def test_whitespace_and_blank_entries_tolerated(run_paper_module, monkeypatch):
    rp = run_paper_module
    monkeypatch.setattr(rp.settings, "SYMBOL", "BTCUSDT")
    monkeypatch.setattr(rp.settings, "SHADOW_SYMBOLS", " ETHUSDT , , SOLUSDT ,  ")
    monkeypatch.setattr(rp.settings, "DEFAULT_TIMEFRAME", "5m")
    monkeypatch.setattr(rp.settings, "HTF_TIMEFRAME", "4h")

    call_log: list = []
    monkeypatch.setattr(rp, "CandleFetcher", _make_fake_candle_fetcher(call_log))
    monkeypatch.setattr(rp, "detect_market_regime", lambda candles: _FAKE_REGIME)
    _install_default_record_and_resolve(monkeypatch, rp)

    result = rp._maybe_record_extra_symbol_shadow_passes()

    assert set(result.keys()) == {"ETHUSDT", "SOLUSDT"}


# --- Wiring into _maybe_record_shadow_pass ---


def test_maybe_record_shadow_pass_wires_extra_symbols_under_summary(run_paper_module, monkeypatch):
    """The `run_paper` helper (called by `run_once`) wiring: with the flag
    on, `summary["shadow"]["extra_symbols"]` collects one entry per extra
    symbol, alongside the active symbol's own existing "resolution" key.
    """
    rp = run_paper_module
    monkeypatch.setattr(rp.settings, "ENABLE_SHADOW_STRATEGY_SIGNALS", True)
    monkeypatch.setattr(rp.settings, "SYMBOL", "BTCUSDT")
    monkeypatch.setattr(rp.settings, "SHADOW_SYMBOLS", "ETHUSDT")
    monkeypatch.setattr(rp.settings, "USE_JADE_ENGINE", False)
    monkeypatch.setattr(rp.settings, "DEFAULT_TIMEFRAME", "5m")
    monkeypatch.setattr(rp.settings, "HTF_TIMEFRAME", "4h")

    call_log: list = []
    monkeypatch.setattr(rp, "CandleFetcher", _make_fake_candle_fetcher(call_log))
    monkeypatch.setattr(rp, "detect_market_regime", lambda candles: _FAKE_REGIME)
    record_calls, resolve_calls = _install_default_record_and_resolve(monkeypatch, rp)

    summary: dict = {}
    rp._maybe_record_shadow_pass(
        summary, _candles("BTCUSDT"), _candles("BTCUSDT"), regime=_FAKE_REGIME
    )

    assert summary["shadow"] is not None
    assert "resolution" in summary["shadow"]
    assert "extra_symbols" in summary["shadow"]
    assert set(summary["shadow"]["extra_symbols"].keys()) == {"ETHUSDT"}

    # Active symbol keeps its real "legacy" active_strategy_name; the
    # extra symbol gets None (exclude nothing -- nothing trades it).
    assert ("BTCUSDT", "legacy") in record_calls
    assert ("ETHUSDT", None) in record_calls
    assert "BTCUSDT" in resolve_calls
    assert "ETHUSDT" in resolve_calls

    # Active symbol's candles were passed in directly -- CandleFetcher is
    # only used for the extra symbol.
    assert all(c[0] == "ETHUSDT" for c in call_log)
    assert len(call_log) == 2


def test_flag_off_summary_untouched_and_no_extra_symbol_calls(run_paper_module, monkeypatch):
    """Hard rule: ENABLE_SHADOW_STRATEGY_SIGNALS False is byte-identical to
    prior behavior no matter what SHADOW_SYMBOLS is set to -- the entire
    shadow block (including the new extra-symbols step) never runs.
    """
    rp = run_paper_module
    monkeypatch.setattr(rp.settings, "ENABLE_SHADOW_STRATEGY_SIGNALS", False)
    monkeypatch.setattr(rp.settings, "SHADOW_SYMBOLS", "ETHUSDT,SOLUSDT")

    call_log: list = []
    monkeypatch.setattr(rp, "CandleFetcher", _make_fake_candle_fetcher(call_log))

    summary: dict = {}
    rp._maybe_record_shadow_pass(summary, _candles("BTCUSDT"), _candles("BTCUSDT"))

    assert summary == {}
    assert call_log == []


def test_flag_on_empty_shadow_symbols_only_active_symbol_processed(run_paper_module, monkeypatch):
    """Flag on, SHADOW_SYMBOLS empty -> extra_symbols is an empty dict and
    no extra CandleFetcher calls happen; only the active symbol is
    resolved/recorded (matches this milestone's real-DB smoke test).
    """
    rp = run_paper_module
    monkeypatch.setattr(rp.settings, "ENABLE_SHADOW_STRATEGY_SIGNALS", True)
    monkeypatch.setattr(rp.settings, "SYMBOL", "BTCUSDT")
    monkeypatch.setattr(rp.settings, "SHADOW_SYMBOLS", "")
    monkeypatch.setattr(rp.settings, "USE_JADE_ENGINE", False)
    monkeypatch.setattr(rp.settings, "DEFAULT_TIMEFRAME", "5m")
    monkeypatch.setattr(rp.settings, "HTF_TIMEFRAME", "4h")

    call_log: list = []
    monkeypatch.setattr(rp, "CandleFetcher", _make_fake_candle_fetcher(call_log))
    monkeypatch.setattr(rp, "detect_market_regime", lambda candles: _FAKE_REGIME)
    record_calls, resolve_calls = _install_default_record_and_resolve(monkeypatch, rp)

    summary: dict = {}
    rp._maybe_record_shadow_pass(
        summary, _candles("BTCUSDT"), _candles("BTCUSDT"), regime=_FAKE_REGIME
    )

    assert summary["shadow"]["extra_symbols"] == {}
    assert record_calls == [("BTCUSDT", "legacy")]
    assert resolve_calls == ["BTCUSDT"]
    assert call_log == []


def test_active_symbol_failure_skips_extra_symbols_this_pass(run_paper_module, monkeypatch):
    """Documented Milestone 17a design call: extra-symbol processing runs
    only after the active symbol's own resolve/record steps succeed
    (both live inside `_maybe_record_shadow_pass`'s single outer
    try/except) -- if the active symbol's own shadow step raises, the
    whole `"shadow"` entry becomes None (unchanged prior behavior) and
    extra symbols are simply skipped THIS pass, retried clean next pass.
    """
    rp = run_paper_module
    monkeypatch.setattr(rp.settings, "ENABLE_SHADOW_STRATEGY_SIGNALS", True)
    monkeypatch.setattr(rp.settings, "SYMBOL", "BTCUSDT")
    monkeypatch.setattr(rp.settings, "SHADOW_SYMBOLS", "ETHUSDT")
    monkeypatch.setattr(rp.settings, "DEFAULT_TIMEFRAME", "5m")
    monkeypatch.setattr(rp.settings, "HTF_TIMEFRAME", "4h")

    call_log: list = []
    monkeypatch.setattr(rp, "CandleFetcher", _make_fake_candle_fetcher(call_log))
    monkeypatch.setattr(rp, "resolve_open_shadow_signals", lambda symbol, candles: {
        "examined": 0, "resolved_tp": 0, "resolved_sl": 0, "expired": 0, "still_open": 0,
    })

    def raising_record(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(rp, "record_shadow_pass", raising_record)

    summary: dict = {}
    rp._maybe_record_shadow_pass(
        summary, _candles("BTCUSDT"), _candles("BTCUSDT"), regime=_FAKE_REGIME
    )

    assert summary["shadow"] is None
    assert call_log == []  # the extra-symbols loop was never reached
