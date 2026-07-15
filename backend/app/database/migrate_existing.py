"""Bring an EXISTING, never-alembic-stamped SQLite database up to the
current migration head (adaptive platform milestone 8.1, operator
directive 2026-07-16, ENGINEERING_DECISIONS.md #51).

Why this exists: the live paper-trading database (`paper_validation.db`)
was created by an early bootstrap that predates this project's alembic
discipline -- it has no `alembic_version` table, and `scripts/run_paper.py`
never runs migrations (only `app.main`'s FastAPI lifespan does, and no
FastAPI process runs alongside the paper trader). Every adaptive-platform
milestone since #2 added columns/tables the live DB therefore does not
have -- meaning a paper-trader restart on current code would crash on its
first `TradeTracker.record_trade()` INSERT. This module closes that gap:
it fingerprints which historical schema generation a DB file matches,
stamps that revision as the alembic baseline, and upgrades to head --
all migrations between the supported baselines and head are purely
additive (ADD COLUMN / CREATE TABLE), so this is safe to run against a
DB that an older-code process currently has open (SQLite takes only
brief write locks per statement; the paper trader's own DB reads are
already best-effort with WARN-and-default fallbacks).

Deliberately imports NOTHING from `app.*` at module level except inside
`_build_alembic_config`'s alembic invocation path -- schema detection
uses stdlib sqlite3 only, so this module can inspect any file without
the imported-settings-URL side effects `conftest.py` documents.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Fingerprints for each historical schema generation this project has
# ever shipped, ordered NEWEST FIRST (detection returns the first match,
# and every newer generation is a superset of every older one).
# Maintained alongside the migrations in app/database/migrations/versions/;
# a new migration only needs an entry here if an un-stamped DB of its
# generation could exist in the wild (which, after this module exists and
# every DB is stamped, should never happen again).
_GENERATION_FINGERPRINTS: list[tuple[str, dict]] = [
    (
        "e3110e6a6b59",  # adaptive platform performance tracking
        {"table": "strategy_performance_snapshots", "trades_column": "market_regime"},
    ),
    (
        "393afdf7fe67",  # observability columns on signals/trades
        {"trades_column": "exit_reason"},
    ),
    (
        "4b8a822a475b",  # circuit-breaker persistence columns on bot_state
        {"bot_state_column": "circuit_breaker_tripped"},
    ),
    (
        "a0f5ebc23690",  # initial schema
        {"table": "trades"},
    ),
]

_CORE_TABLES = {"bot_state", "candles", "risk_events", "signals", "trades", "strategy_logs"}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def detect_schema_generation(db_path: str | Path) -> str | None:
    """Return the alembic revision id whose schema this (un-stamped) DB
    file matches, or `None` if the file doesn't look like this project's
    database at all (missing core tables) -- the caller must refuse to
    migrate an unrecognized file rather than guess.

    If the DB already HAS an `alembic_version` table, returns the string
    `"stamped"` -- the caller should run a plain `upgrade head` without
    stamping (stamping over an existing version record would corrupt the
    migration history).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        tables = _table_names(conn)
        if "alembic_version" in tables:
            return "stamped"
        if not _CORE_TABLES.issubset(tables):
            return None

        for revision, fingerprint in _GENERATION_FINGERPRINTS:
            table_needed = fingerprint.get("table")
            if table_needed and table_needed not in tables:
                continue
            trades_col = fingerprint.get("trades_column")
            if trades_col and trades_col not in _column_names(conn, "trades"):
                continue
            bot_state_col = fingerprint.get("bot_state_column")
            if bot_state_col and bot_state_col not in _column_names(conn, "bot_state"):
                continue
            return revision
        return None
    finally:
        conn.close()


def build_alembic_config(db_path: str | Path):
    """An alembic Config targeting `db_path` explicitly (via the env.py
    guard added for this module) -- independent of settings.DATABASE_URL,
    so callers/tests can migrate any file without environment surgery.
    SQLite URLs need forward slashes even on Windows (`as_posix()`,
    the same lesson `conftest.py`'s `sqlite_url` fixture already encodes).
    """
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "app" / "database" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{Path(db_path).resolve().as_posix()}")
    return cfg


def migrate_database(db_path: str | Path, backup: bool = True) -> dict:
    """Detect, (optionally) back up, stamp if needed, and upgrade
    `db_path` to the current migration head. Returns a report dict:
    `{detected, backup_path, head, tables, trades_columns}`.

    Raises `ValueError` (refusing to touch the file) when the schema is
    unrecognized -- never guesses a baseline.
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    db_path = Path(db_path)
    if not db_path.exists():
        raise ValueError(f"database file not found: {db_path}")

    detected = detect_schema_generation(db_path)
    if detected is None:
        raise ValueError(
            f"unrecognized schema in {db_path} -- refusing to stamp/migrate a "
            "database this project's fingerprints don't match"
        )

    backup_path: str | None = None
    if backup:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_file = db_path.with_name(f"{db_path.name}.backup-{stamp}")
        shutil.copy2(db_path, backup_file)
        backup_path = str(backup_file)

    cfg = build_alembic_config(db_path)
    if detected != "stamped":
        command.stamp(cfg, detected)
    command.upgrade(cfg, "head")

    # Verify: alembic head reached, and the schema actually carries the
    # newest generation's artifacts.
    expected_head = ScriptDirectory.from_config(cfg).get_current_head()
    conn = sqlite3.connect(str(db_path))
    try:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = _table_names(conn)
        trades_columns = _column_names(conn, "trades")
    finally:
        conn.close()
    if version != expected_head:
        raise RuntimeError(f"post-migration head is {version}, expected {expected_head}")
    if "strategy_performance_snapshots" not in tables or "market_regime" not in trades_columns:
        raise RuntimeError("post-migration schema verification failed")

    return {
        "detected": detected,
        "backup_path": backup_path,
        "head": version,
        "tables": sorted(tables),
        "trades_columns": sorted(trades_columns),
    }
