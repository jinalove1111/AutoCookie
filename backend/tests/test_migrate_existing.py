"""Tests for app.database.migrate_existing (adaptive platform milestone
8.1, ENGINEERING_DECISIONS.md #51): bringing a never-alembic-stamped
SQLite DB (the live paper-trading DB's real condition) up to head.

Old-generation DBs are built with alembic ITSELF (`upgrade <rev>`, then
RENAMING alembic_version away to simulate the un-stamped legacy
bootstrap) -- real schemas from the real migration chain, not hand-built
imitations. RENAME (not a destructive statement) is deliberate: this
repo's tooling gates destructive SQL keywords even in test fixtures, and
a rename hides the stamp from `detect_schema_generation` (which checks
table EXISTENCE by exact name) just as faithfully.

`app.database.migrate_existing` deliberately reads its target DB path
explicitly (via the env.py sqlalchemy.url guard), so these tests need no
DATABASE_URL/monkeypatch environment surgery -- plain tmp_path files.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from app.database.migrate_existing import (
    build_alembic_config,
    detect_schema_generation,
    migrate_database,
)


def _make_db_at(tmp_path, revision: str, *, hide_stamp: bool = True):
    """Create a real DB at `revision` via the actual migration chain,
    optionally hiding alembic_version (via RENAME) to simulate a
    pre-alembic bootstrap (the live paper DB's condition)."""
    db_path = tmp_path / "legacy.db"
    cfg = build_alembic_config(db_path)
    command.upgrade(cfg, revision)
    if hide_stamp:
        conn = sqlite3.connect(str(db_path))
        conn.execute("ALTER TABLE alembic_version RENAME TO not_a_stamp_fixture")
        conn.commit()
        conn.close()
    return db_path


def test_detects_circuit_breaker_generation(tmp_path):
    db_path = _make_db_at(tmp_path, "4b8a822a475b")
    assert detect_schema_generation(db_path) == "4b8a822a475b"


def test_detects_initial_schema_generation(tmp_path):
    db_path = _make_db_at(tmp_path, "a0f5ebc23690")
    assert detect_schema_generation(db_path) == "a0f5ebc23690"


def test_detects_observability_generation(tmp_path):
    db_path = _make_db_at(tmp_path, "393afdf7fe67")
    assert detect_schema_generation(db_path) == "393afdf7fe67"


def test_detects_stamped_db(tmp_path):
    db_path = _make_db_at(tmp_path, "4b8a822a475b", hide_stamp=False)
    assert detect_schema_generation(db_path) == "stamped"


def test_detects_unrecognized_db_as_none(tmp_path):
    db_path = tmp_path / "not_ours.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE something_else (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    assert detect_schema_generation(db_path) is None


def test_migrate_unstamped_circuit_breaker_db_reaches_head(tmp_path):
    """The exact real-world case: the live paper DB's generation
    (4b8a822a475b schema, no alembic_version)."""
    db_path = _make_db_at(tmp_path, "4b8a822a475b")

    report = migrate_database(db_path, backup=True)

    assert report["detected"] == "4b8a822a475b"
    assert report["backup_path"] is not None
    assert "strategy_performance_snapshots" in report["tables"]
    for column in (
        "market_regime",
        "strategy_name",
        "holding_time_seconds",
        "max_adverse_excursion",
        "max_favorable_excursion",
        "latency_ms",
        "exit_reason",
        "r_multiple",
        "strategy_config",
    ):
        assert column in report["trades_columns"], column

    conn = sqlite3.connect(str(db_path))
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    conn.close()
    assert version == report["head"]


def test_migrate_preserves_existing_rows(tmp_path):
    """Additive-only guarantee: rows written by the old-generation code
    survive the migration untouched (this is the live DB's bot_state /
    circuit-breaker state)."""
    db_path = _make_db_at(tmp_path, "4b8a822a475b")
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO bot_state (mode, live_enabled, daily_pnl, weekly_pnl,"
        " current_drawdown, trading_allowed, circuit_breaker_tripped)"
        " VALUES ('paper', 0, 0.0, 0.0, 0.0, 1, 0)"
    )
    conn.commit()
    conn.close()

    migrate_database(db_path, backup=False)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT mode, live_enabled, trading_allowed, circuit_breaker_tripped FROM bot_state"
    ).fetchone()
    conn.close()
    assert row == ("paper", 0, 1, 0)


def test_migrate_creates_backup_file(tmp_path):
    db_path = _make_db_at(tmp_path, "4b8a822a475b")
    report = migrate_database(db_path, backup=True)

    backup = Path(report["backup_path"])
    assert backup.exists()
    # The backup preserves the PRE-migration state: no alembic_version.
    conn = sqlite3.connect(str(backup))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "alembic_version" not in tables


def test_migrate_refuses_unrecognized_db(tmp_path):
    db_path = tmp_path / "not_ours.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE something_else (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="unrecognized"):
        migrate_database(db_path)


def test_migrate_stamped_db_is_a_plain_upgrade(tmp_path):
    """A DB that already has alembic_version (e.g. any test DB, or a
    future re-run against the already-migrated live DB) must NOT be
    re-stamped -- just upgraded (idempotent no-op at head)."""
    db_path = _make_db_at(tmp_path, "4b8a822a475b", hide_stamp=False)

    report = migrate_database(db_path, backup=False)
    assert report["detected"] == "stamped"

    # Second run: already at head, still succeeds (idempotent).
    report2 = migrate_database(db_path, backup=False)
    assert report2["head"] == report["head"]


def test_migrate_missing_file_raises(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        migrate_database(tmp_path / "does_not_exist.db")
