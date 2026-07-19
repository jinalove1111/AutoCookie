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
