"""Tests for Milestone 21 (2026-07-17): consecutive candle-fetch-failure
alerting in scripts/run_paper.py's loop mode.

scripts/ is a sibling directory to backend/, not a package under it, so
it's added to sys.path explicitly here, mirroring
tests/test_run_backtest.py's existing pattern for testing scripts/*.py
helpers. Unlike run_backtest.py, run_paper.py imports app.portfolio.*
modules at module level, which transitively import app.database.session
-- and that module calls `create_engine(settings.DATABASE_URL)` at IMPORT
time (see app/database/session.py), which raises immediately if
DATABASE_URL is empty (the bare-env default with no .env file, as in this
sandbox). The `run_paper_module` fixture below points DATABASE_URL at a
throwaway temp sqlite path and purges cached `app.*`/`run_paper` modules
before importing, mirroring tests/conftest.py's `fresh_app_env` pattern.
None of these tests ever execute a real query against that DB -- every
DB-facing seam (`run_once`, `PersistentCircuitBreaker`'s load/save hooks)
is monkeypatched in every test below -- so the file need not exist or be
migrated.

Two layers of coverage:

  1. `_FetchFailureAlerter` unit tests -- the class that owns the
     dedup/recovery/threshold-disable logic in isolation, driven directly
     with stubbed `run_once()`-shaped summary dicts (no CLI, no DB, no
     circuit breaker). This is the primary coverage for the milestone's
     dedup contract (Hard Rule 2).

  2. Two end-to-end `main()` loop tests -- `run_once`,
     `load_circuit_breaker_state`/`save_circuit_breaker_state` (so
     `PersistentCircuitBreaker` never touches a real DB), and
     `send_telegram_alert`/`send_discord_alert` are all monkeypatched on
     the `run_paper` module object, and `main()` is driven via a
     monkeypatched `sys.argv` -- confirming the class is actually wired
     into the real loop (and that single-pass mode never constructs it).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _purge_app_and_script_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app.") or name == "run_paper":
            del sys.modules[name]


@pytest.fixture()
def run_paper_module(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Fresh import of scripts/run_paper.py bound to a throwaway temp
    SQLite DATABASE_URL. See module docstring for why this is necessary."""
    db_file = tmp_path / "run_paper_fetch_failure_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    _purge_app_and_script_modules()

    import run_paper as rp

    yield rp

    _purge_app_and_script_modules()


def _summary(fetch_failed: bool, error: str | None = None) -> dict:
    """Minimal stand-in for a run_once() summary dict -- _FetchFailureAlerter
    only ever reads "fetch_failed" and "error"."""
    return {"fetch_failed": fetch_failed, "error": error, "exit_code": 1 if fetch_failed else 0}


class _AlertRecorder:
    """Records every send_telegram_alert/send_discord_alert call so tests
    can assert exact call counts and message content."""

    def __init__(self) -> None:
        self.telegram_calls: list[str] = []
        self.discord_calls: list[str] = []

    def telegram(self, message: str) -> None:
        self.telegram_calls.append(message)

    def discord(self, message: str) -> None:
        self.discord_calls.append(message)

    @property
    def total_alerts(self) -> int:
        # Both channels always fire together (_send calls both), so this is
        # just telegram_calls (equivalently discord_calls) treated as "one
        # alert dispatch".
        assert len(self.telegram_calls) == len(self.discord_calls)
        return len(self.telegram_calls)


@pytest.fixture()
def alert_recorder(monkeypatch: pytest.MonkeyPatch, run_paper_module) -> _AlertRecorder:
    recorder = _AlertRecorder()
    monkeypatch.setattr(run_paper_module, "send_telegram_alert", recorder.telegram)
    monkeypatch.setattr(run_paper_module, "send_discord_alert", recorder.discord)
    return recorder


# ---------------------------------------------------------------------------
# 1. _FetchFailureAlerter unit tests
# ---------------------------------------------------------------------------


def test_threshold_crossing_fires_exactly_one_alert(run_paper_module, alert_recorder):
    alerter = run_paper_module._FetchFailureAlerter(threshold=3)

    alerter.observe(_summary(True, "getaddrinfo failed"))
    assert alert_recorder.total_alerts == 0
    alerter.observe(_summary(True, "getaddrinfo failed"))
    assert alert_recorder.total_alerts == 0
    alerter.observe(_summary(True, "getaddrinfo failed"))  # reaches threshold=3

    assert alert_recorder.total_alerts == 1
    assert alerter.alerted is True
    message = alert_recorder.telegram_calls[0]
    assert "3" in message
    assert "getaddrinfo failed" in message


def test_continued_failures_do_not_re_alert(run_paper_module, alert_recorder):
    alerter = run_paper_module._FetchFailureAlerter(threshold=3)

    for _ in range(3):
        alerter.observe(_summary(True, "err"))
    assert alert_recorder.total_alerts == 1

    # Keep failing well past the threshold.
    for _ in range(5):
        alerter.observe(_summary(True, "err"))

    assert alert_recorder.total_alerts == 1
    assert alerter.consecutive_failures == 8


def test_recovery_fires_exactly_one_alert_after_alerted_streak(run_paper_module, alert_recorder):
    alerter = run_paper_module._FetchFailureAlerter(threshold=3)

    for _ in range(3):
        alerter.observe(_summary(True, "err"))
    assert alert_recorder.total_alerts == 1

    alerter.observe(_summary(False))  # first success after an alerted streak

    assert alert_recorder.total_alerts == 2
    recovery_message = alert_recorder.telegram_calls[1]
    assert "recovered" in recovery_message.lower()
    assert alerter.alerted is False
    assert alerter.consecutive_failures == 0

    # A further success must not re-fire a recovery alert.
    alerter.observe(_summary(False))
    assert alert_recorder.total_alerts == 2


def test_sub_threshold_blip_fires_nothing(run_paper_module, alert_recorder):
    alerter = run_paper_module._FetchFailureAlerter(threshold=3)

    alerter.observe(_summary(True, "transient DNS blip"))
    alerter.observe(_summary(True, "transient DNS blip"))
    alerter.observe(_summary(False))  # recovers before ever reaching threshold=3

    assert alert_recorder.total_alerts == 0
    assert alerter.consecutive_failures == 0
    assert alerter.alerted is False


def test_threshold_zero_never_alerts(run_paper_module, alert_recorder):
    alerter = run_paper_module._FetchFailureAlerter(threshold=0)

    for _ in range(10):
        alerter.observe(_summary(True, "persistent outage"))
    alerter.observe(_summary(False))

    assert alert_recorder.total_alerts == 0
    assert alerter.alerted is False


def test_alert_function_raising_does_not_propagate(
    monkeypatch: pytest.MonkeyPatch, run_paper_module
):
    def _raise_telegram(message: str) -> None:
        raise RuntimeError("telegram is down")

    def _raise_discord(message: str) -> None:
        raise RuntimeError("discord is down")

    monkeypatch.setattr(run_paper_module, "send_telegram_alert", _raise_telegram)
    monkeypatch.setattr(run_paper_module, "send_discord_alert", _raise_discord)

    alerter = run_paper_module._FetchFailureAlerter(threshold=2)

    # Must not raise despite both alert functions blowing up.
    alerter.observe(_summary(True, "err"))
    alerter.observe(_summary(True, "err"))  # crosses threshold -> _send -> raises internally

    assert alerter.alerted is True  # state still updates correctly despite the alert failure

    # Recovery path must also survive a raising alert function.
    alerter.observe(_summary(False))
    assert alerter.alerted is False


def test_default_threshold_reads_from_settings(
    monkeypatch: pytest.MonkeyPatch, run_paper_module
):
    monkeypatch.setattr(run_paper_module.settings, "FETCH_FAILURE_ALERT_THRESHOLD", 5)
    alerter = run_paper_module._FetchFailureAlerter()
    assert alerter.threshold == 5


# ---------------------------------------------------------------------------
# 2. End-to-end main() loop tests
# ---------------------------------------------------------------------------


def test_main_loop_wires_fetch_alerter_correctly(
    monkeypatch: pytest.MonkeyPatch, run_paper_module, alert_recorder
):
    """Drives the real main() loop (--iterations 6) with run_once stubbed to
    return a scripted sequence of summaries, and the circuit breaker's DB
    hooks faked out (never touches a real database). Confirms
    _FetchFailureAlerter is genuinely wired into the loop, not just correct
    in isolation.

    Sequence (threshold=3):
      iter 1: fail (1)
      iter 2: fail (2)
      iter 3: fail (3) -> alert fires
      iter 4: fail (4) -> no re-alert
      iter 5: success -> recovery alert fires
      iter 6: success -> nothing further
    """
    monkeypatch.setattr(run_paper_module.settings, "FETCH_FAILURE_ALERT_THRESHOLD", 3)

    # Fake out PersistentCircuitBreaker's DB-backed hooks -- these are the
    # module-level names run_paper.py imported, so patching them here means
    # PersistentCircuitBreaker(state_loader=..., state_saver=...) inside
    # main() uses the fakes below instead of any real database.
    monkeypatch.setattr(
        run_paper_module,
        "load_circuit_breaker_state",
        lambda: {"tripped": False, "reason": None, "tripped_at": None},
    )
    monkeypatch.setattr(run_paper_module, "save_circuit_breaker_state", lambda *a, **k: None)

    outcomes = [True, True, True, True, False, False]
    calls = {"n": 0}

    def fake_run_once(circuit_breaker=None):
        idx = calls["n"]
        calls["n"] += 1
        failed = outcomes[idx]
        return _summary(failed, error="getaddrinfo failed" if failed else None)

    monkeypatch.setattr(run_paper_module, "run_once", fake_run_once)
    monkeypatch.setattr(run_paper_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        sys, "argv", ["run_paper.py", "--iterations", "6", "--interval-seconds", "0"]
    )

    exit_code = run_paper_module.main()

    assert exit_code == 0
    assert calls["n"] == 6
    # One failure alert (iter 3) + one recovery alert (iter 5) = 2 total.
    assert alert_recorder.total_alerts == 2
    assert "3" in alert_recorder.telegram_calls[0]
    assert "recovered" in alert_recorder.telegram_calls[1].lower()


def test_single_pass_mode_never_constructs_alerter(
    monkeypatch: pytest.MonkeyPatch, run_paper_module
):
    """--iterations 1 (the default) must take the exact Milestone-3
    single-pass path -- no _FetchFailureAlerter is ever constructed, no
    circuit breaker, no loop. Documents/confirms the module docstring's
    "single-pass mode is untouched" claim."""

    def fake_run_once(circuit_breaker=None):
        assert circuit_breaker is None  # the untouched single-pass call shape
        return _summary(True, error="getaddrinfo failed")

    monkeypatch.setattr(run_paper_module, "run_once", fake_run_once)

    def _fail_if_constructed(*args, **kwargs):
        raise AssertionError("_FetchFailureAlerter must not be constructed in single-pass mode")

    monkeypatch.setattr(run_paper_module, "_FetchFailureAlerter", _fail_if_constructed)
    monkeypatch.setattr(sys, "argv", ["run_paper.py"])

    exit_code = run_paper_module.main()

    assert exit_code == 1  # fetch_failed summary's exit_code, unaffected by this milestone
