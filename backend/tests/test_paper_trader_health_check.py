"""Tests for scripts/paper_trader_health_check.py (Milestone 37, Priority 3).

Uses the same real `alembic upgrade head` temp-DB fixtures every other
`app.portfolio.*`-touching test in this suite already uses, then opens a
SEPARATE raw read-only sqlite3 connection to that same file -- exactly
how the script is actually invoked against a live `paper_validation.db`.
`scripts/` is a sibling directory to `backend/`, not a package under it,
so it's added to `sys.path` explicitly (same pattern
`test_run_paper_exit_check.py` already uses).
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _fresh_health_check():
    sys.modules.pop("paper_trader_health_check", None)
    import paper_trader_health_check

    return paper_trader_health_check


def _readonly_conn(db_file: Path) -> sqlite3.Connection:
    uri = f"file:{db_file.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# --- check_circuit_breaker -----------------------------------------------


def test_check_circuit_breaker_ok_when_untripped(migrated_db, tmp_path):
    from app.portfolio.positions import get_or_create_bot_state

    get_or_create_bot_state()
    hc = _fresh_health_check()
    conn = _readonly_conn(tmp_path / "jadecap_test.db")
    try:
        result = hc.check_circuit_breaker(conn)
    finally:
        conn.close()
    assert result["status"] == "OK"
    assert result["tripped"] is False


def test_check_circuit_breaker_tripped_when_breaker_persisted_as_tripped(migrated_db, tmp_path):
    from app.portfolio.positions import save_circuit_breaker_state

    save_circuit_breaker_state(True, "daily loss limit", datetime.now(timezone.utc))
    hc = _fresh_health_check()
    conn = _readonly_conn(tmp_path / "jadecap_test.db")
    try:
        result = hc.check_circuit_breaker(conn)
    finally:
        conn.close()
    assert result["status"] == "TRIPPED"
    assert result["reason"] == "daily loss limit"


# --- check_freshness -------------------------------------------------------


def test_check_freshness_no_snapshots_yet(migrated_db, tmp_path):
    hc = _fresh_health_check()
    conn = _readonly_conn(tmp_path / "jadecap_test.db")
    try:
        result = hc.check_freshness(conn, expected_interval_seconds=300)
    finally:
        conn.close()
    assert result["status"] == "NO_SNAPSHOTS_YET"


def test_check_freshness_fresh_when_recent_snapshot(migrated_db, tmp_path, db_session):
    from app.database.models import RegimeSnapshot

    db_session.add(
        RegimeSnapshot(
            captured_at=datetime.now(timezone.utc) - timedelta(seconds=30),
            symbol="BTCUSDT",
            timeframe="15m",
            trend="bullish",
            volatility="normal",
            breakout=False,
            mean_reversion=False,
            liquidity_sweep_environment=False,
        )
    )
    db_session.commit()

    hc = _fresh_health_check()
    conn = _readonly_conn(tmp_path / "jadecap_test.db")
    try:
        result = hc.check_freshness(conn, expected_interval_seconds=300)
    finally:
        conn.close()
    assert result["status"] == "FRESH"


def test_check_freshness_stale_when_old_snapshot(migrated_db, tmp_path, db_session):
    from app.database.models import RegimeSnapshot

    db_session.add(
        RegimeSnapshot(
            captured_at=datetime.now(timezone.utc) - timedelta(hours=2),
            symbol="BTCUSDT",
            timeframe="15m",
            trend="bullish",
            volatility="normal",
            breakout=False,
            mean_reversion=False,
            liquidity_sweep_environment=False,
        )
    )
    db_session.commit()

    hc = _fresh_health_check()
    conn = _readonly_conn(tmp_path / "jadecap_test.db")
    try:
        result = hc.check_freshness(conn, expected_interval_seconds=300)
    finally:
        conn.close()
    assert result["status"] == "STALE"


# --- check_open_positions ---------------------------------------------


def test_check_open_positions_ok_when_zero_open(migrated_db, tmp_path):
    hc = _fresh_health_check()
    conn = _readonly_conn(tmp_path / "jadecap_test.db")
    try:
        result = hc.check_open_positions(conn)
    finally:
        conn.close()
    assert result["status"] == "OK"
    assert result["count"] == 0


def test_check_open_positions_ok_when_exactly_one_open(migrated_db, tmp_path, db_session):
    from app.database.models import Trade

    db_session.add(
        Trade(
            symbol="BTCUSDT",
            direction="long",
            entry_price=50000.0,
            stop_loss=49000.0,
            take_profit=52000.0,
            size=0.01,
            status="open",
            mode="paper",
            opened_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    hc = _fresh_health_check()
    conn = _readonly_conn(tmp_path / "jadecap_test.db")
    try:
        result = hc.check_open_positions(conn)
    finally:
        conn.close()
    assert result["status"] == "OK"
    assert result["count"] == 1


def test_check_open_positions_anomaly_when_multiple_open(migrated_db, tmp_path, db_session):
    from app.database.models import Trade

    for _ in range(2):
        db_session.add(
            Trade(
                symbol="BTCUSDT",
                direction="long",
                entry_price=50000.0,
                stop_loss=49000.0,
                take_profit=52000.0,
                size=0.01,
                status="open",
                mode="paper",
                opened_at=datetime.now(timezone.utc),
            )
        )
    db_session.commit()

    hc = _fresh_health_check()
    conn = _readonly_conn(tmp_path / "jadecap_test.db")
    try:
        result = hc.check_open_positions(conn)
    finally:
        conn.close()
    assert result["status"] == "ANOMALY_MULTIPLE_OPEN_POSITIONS"
    assert result["count"] == 2


# --- _as_utc / _parse_timestamp (naive-vs-aware safety) -----------------


def test_as_utc_normalizes_naive_datetime():
    hc = _fresh_health_check()
    naive = datetime(2026, 7, 19, 12, 0, 0)
    result = hc._as_utc(naive)
    assert result.tzinfo is not None


def test_as_utc_leaves_aware_datetime_unchanged():
    hc = _fresh_health_check()
    aware = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
    assert hc._as_utc(aware) == aware


def test_as_utc_none_stays_none():
    hc = _fresh_health_check()
    assert hc._as_utc(None) is None


# --- main() overall verdict + exit code ----------------------------------


def test_main_returns_zero_and_healthy_for_a_clean_fresh_db(migrated_db, tmp_path, db_session, capsys):
    from app.database.models import RegimeSnapshot

    db_session.add(
        RegimeSnapshot(
            captured_at=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            timeframe="15m",
            trend="bullish",
            volatility="normal",
            breakout=False,
            mean_reversion=False,
            liquidity_sweep_environment=False,
        )
    )
    db_session.commit()

    hc = _fresh_health_check()
    exit_code = hc.main([str(tmp_path / "jadecap_test.db")])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Overall: HEALTHY" in captured.out


def test_main_returns_one_when_tripped(migrated_db, tmp_path, db_session):
    from app.database.models import RegimeSnapshot
    from app.portfolio.positions import save_circuit_breaker_state

    db_session.add(
        RegimeSnapshot(
            captured_at=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            timeframe="15m",
            trend="bullish",
            volatility="normal",
            breakout=False,
            mean_reversion=False,
            liquidity_sweep_environment=False,
        )
    )
    db_session.commit()
    save_circuit_breaker_state(True, "weekly loss limit", datetime.now(timezone.utc))

    hc = _fresh_health_check()
    exit_code = hc.main([str(tmp_path / "jadecap_test.db")])
    assert exit_code == 1


def test_main_fails_gracefully_on_missing_db_file(tmp_path):
    hc = _fresh_health_check()
    missing = tmp_path / "does_not_exist.db"
    exit_code = hc.main([str(missing)])
    assert exit_code == 1


# --- --watch mode: transition-only alert logging (Milestone 38) --------


def _fake_result(unhealthy: bool) -> dict:
    return {
        "breaker": {"status": "TRIPPED" if unhealthy else "OK", "tripped": unhealthy, "reason": None, "tripped_at": None},
        "freshness": {"status": "FRESH", "latest": "x", "staleness_seconds": 1.0, "stale_threshold_seconds": 900},
        "positions": {"status": "OK", "count": 0, "open_trades": []},
        "log_errors": {"status": "NOT_CHECKED", "error_count": 0, "warning_count": 0, "recent_errors": []},
    }


def test_run_watch_logs_a_line_only_on_transition_not_every_poll(monkeypatch, tmp_path):
    hc = _fresh_health_check()
    monkeypatch.setattr(hc.time, "sleep", lambda _s: None)

    # HEALTHY, HEALTHY, UNHEALTHY, UNHEALTHY, HEALTHY -- exactly 2 transitions.
    sequence = [False, False, True, True, False]
    calls = {"n": 0}

    def fake_check(db_path, expected_interval_seconds, log_path=None):
        unhealthy = sequence[calls["n"]]
        calls["n"] += 1
        return unhealthy, _fake_result(unhealthy)

    monkeypatch.setattr(hc, "run_single_check", fake_check)

    alert_log = tmp_path / "alerts.log"
    hc.run_watch(
        db_path=Path("unused.db"),
        expected_interval_seconds=300,
        poll_interval_seconds=1,
        heartbeat_every=0,  # disable heartbeats to isolate transition-only behavior
        max_checks=len(sequence),
        alert_log_path=alert_log,
    )

    lines = alert_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert "HEALTHY -> UNHEALTHY" in lines[0]
    assert "UNHEALTHY -> HEALTHY" in lines[1]


def test_run_watch_writes_heartbeat_at_configured_interval(monkeypatch, tmp_path):
    hc = _fresh_health_check()
    monkeypatch.setattr(hc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        hc, "run_single_check",
        lambda db_path, expected_interval_seconds, log_path=None: (False, _fake_result(False)),
    )

    alert_log = tmp_path / "alerts.log"
    hc.run_watch(
        db_path=Path("unused.db"),
        expected_interval_seconds=300,
        poll_interval_seconds=1,
        heartbeat_every=2,
        max_checks=6,
        alert_log_path=alert_log,
    )

    lines = alert_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3  # checks 2, 4, 6
    assert all("HEARTBEAT HEALTHY" in line for line in lines)


def test_run_watch_no_alert_on_first_check_with_no_prior_state(monkeypatch, tmp_path):
    hc = _fresh_health_check()
    monkeypatch.setattr(hc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        hc, "run_single_check",
        lambda db_path, expected_interval_seconds, log_path=None: (True, _fake_result(True)),
    )

    alert_log = tmp_path / "alerts.log"
    hc.run_watch(
        db_path=Path("unused.db"),
        expected_interval_seconds=300,
        poll_interval_seconds=1,
        heartbeat_every=0,
        max_checks=1,
        alert_log_path=alert_log,
    )

    assert not alert_log.exists()


def test_run_watch_treats_db_open_failure_as_unhealthy_not_a_crash(monkeypatch, tmp_path):
    hc = _fresh_health_check()
    monkeypatch.setattr(hc.time, "sleep", lambda _s: None)

    calls = {"n": 0}

    def flaky_check(db_path, expected_interval_seconds, log_path=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, _fake_result(False)
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(hc, "run_single_check", flaky_check)

    alert_log = tmp_path / "alerts.log"
    hc.run_watch(
        db_path=Path("unused.db"),
        expected_interval_seconds=300,
        poll_interval_seconds=1,
        heartbeat_every=0,
        max_checks=2,
        alert_log_path=alert_log,
    )

    lines = alert_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "HEALTHY -> UNHEALTHY" in lines[0]
    assert "DB_OPEN_FAILED" in lines[0]


def test_main_watch_flag_dispatches_to_run_watch(monkeypatch, tmp_path):
    hc = _fresh_health_check()
    called = {}

    def fake_run_watch(db_path, expected_interval_seconds, poll_interval_seconds, heartbeat_every, max_checks, alert_log_path, log_path=None):
        called["invoked"] = True
        called["max_checks"] = max_checks
        return 0

    monkeypatch.setattr(hc, "run_watch", fake_run_watch)

    exit_code = hc.main([str(tmp_path / "db.db"), "--watch", "--max-checks", "3"])

    assert exit_code == 0
    assert called["invoked"] is True
    assert called["max_checks"] == 3


# --- check_log_errors (Milestone 40) -------------------------------------


def test_check_log_errors_not_checked_when_no_path_given():
    hc = _fresh_health_check()
    result = hc.check_log_errors(None)
    assert result["status"] == "NOT_CHECKED"


def test_check_log_errors_missing_file(tmp_path):
    hc = _fresh_health_check()
    result = hc.check_log_errors(tmp_path / "does_not_exist.log")
    assert result["status"] == "LOG_FILE_MISSING"


def test_check_log_errors_clean_log(tmp_path):
    hc = _fresh_health_check()
    log_path = tmp_path / "trader.log"
    log_path.write_text(
        "--- Iteration 1/100 ---\nNo signal generated this pass.\n"
        "--- Iteration 2/100 ---\nNo signal generated this pass.\n",
        encoding="utf-8",
    )
    result = hc.check_log_errors(log_path)
    assert result["status"] == "CLEAN"
    assert result["error_count"] == 0
    assert result["warning_count"] == 0


def test_check_log_errors_warnings_only_not_treated_as_errors(tmp_path):
    hc = _fresh_health_check()
    log_path = tmp_path / "trader.log"
    log_path.write_text(
        "WARNING: could not compute trades_today (boom); defaulting to 0.\n"
        "WARNING: shadow-mode recording failed (boom).\n",
        encoding="utf-8",
    )
    result = hc.check_log_errors(log_path)
    assert result["status"] == "WARNINGS_PRESENT"
    assert result["error_count"] == 0
    assert result["warning_count"] == 2


def test_check_log_errors_detects_error_lines(tmp_path):
    hc = _fresh_health_check()
    log_path = tmp_path / "trader.log"
    log_path.write_text(
        "No signal generated this pass.\n"
        "ERROR: failed to fetch candles for BTCUSDT/15m: boom\n",
        encoding="utf-8",
    )
    result = hc.check_log_errors(log_path)
    assert result["status"] == "ERRORS_PRESENT"
    assert result["error_count"] == 1
    assert "ERROR: failed to fetch candles for BTCUSDT/15m: boom" in result["recent_errors"]


def test_check_log_errors_detects_alert_lines_as_errors(tmp_path):
    hc = _fresh_health_check()
    log_path = tmp_path / "trader.log"
    log_path.write_text("ALERT: repeated fetch failures\n", encoding="utf-8")
    result = hc.check_log_errors(log_path)
    assert result["status"] == "ERRORS_PRESENT"
    assert result["error_count"] == 1


def test_check_log_errors_only_scans_tail_lines(tmp_path):
    hc = _fresh_health_check()
    log_path = tmp_path / "trader.log"
    # An old error far outside the tail window must not surface.
    lines = ["ERROR: ancient failure, outside the tail window"] + ["clean line"] * 20
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = hc.check_log_errors(log_path, tail_lines=5)
    assert result["status"] == "CLEAN"


def test_check_log_errors_caps_recent_errors_to_five(tmp_path):
    hc = _fresh_health_check()
    log_path = tmp_path / "trader.log"
    lines = [f"ERROR: failure number {i}" for i in range(10)]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = hc.check_log_errors(log_path)
    assert result["error_count"] == 10
    assert len(result["recent_errors"]) == 5


def test_run_single_check_marks_unhealthy_when_log_has_errors(migrated_db, tmp_path, db_session):
    from app.database.models import RegimeSnapshot

    db_session.add(
        RegimeSnapshot(
            captured_at=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            timeframe="15m",
            trend="bullish",
            volatility="normal",
            breakout=False,
            mean_reversion=False,
            liquidity_sweep_environment=False,
        )
    )
    db_session.commit()

    hc = _fresh_health_check()
    log_path = tmp_path / "trader.log"
    log_path.write_text("ERROR: something broke\n", encoding="utf-8")

    unhealthy, results = hc.run_single_check(
        tmp_path / "jadecap_test.db", 300, log_path
    )
    assert unhealthy is True
    assert results["log_errors"]["status"] == "ERRORS_PRESENT"


def test_run_single_check_stays_healthy_when_log_has_only_warnings(migrated_db, tmp_path, db_session):
    from app.database.models import RegimeSnapshot

    db_session.add(
        RegimeSnapshot(
            captured_at=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            timeframe="15m",
            trend="bullish",
            volatility="normal",
            breakout=False,
            mean_reversion=False,
            liquidity_sweep_environment=False,
        )
    )
    db_session.commit()

    hc = _fresh_health_check()
    log_path = tmp_path / "trader.log"
    log_path.write_text("WARNING: defaulted to 0\n", encoding="utf-8")

    unhealthy, results = hc.run_single_check(
        tmp_path / "jadecap_test.db", 300, log_path
    )
    assert unhealthy is False
    assert results["log_errors"]["status"] == "WARNINGS_PRESENT"


def test_main_log_file_flag_flows_into_unhealthy_verdict(migrated_db, tmp_path, db_session):
    from app.database.models import RegimeSnapshot

    db_session.add(
        RegimeSnapshot(
            captured_at=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            timeframe="15m",
            trend="bullish",
            volatility="normal",
            breakout=False,
            mean_reversion=False,
            liquidity_sweep_environment=False,
        )
    )
    db_session.commit()

    log_path = tmp_path / "trader.log"
    log_path.write_text("ERROR: execution raised an exception: boom\n", encoding="utf-8")

    hc = _fresh_health_check()
    exit_code = hc.main([
        str(tmp_path / "jadecap_test.db"), "--log-file", str(log_path)
    ])
    assert exit_code == 1
