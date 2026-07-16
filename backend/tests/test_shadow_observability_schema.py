"""Tests for the Milestone 11 (2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md
sections 2.4/6) shadow-mode observability schema: the `regime_snapshots`
and `shadow_signals` tables added by migration `36cb62e9e2ac` (chained on
`e3110e6a6b59`) and the matching `RegimeSnapshot`/`ShadowSignal` ORM
models in `app.database.models`.

This is a schema-only milestone -- nothing yet writes to these tables in
the paper trading loop (that's milestone 11b). These tests prove three
things:

  1. `alembic upgrade head` creates both tables with the expected columns
     (via the `migrated_db`/`db_session` fixtures in conftest.py, the
     same real-migration-driven bootstrap `app.main`'s FastAPI lifespan
     uses).
  2. Rows round-trip through the ORM models via a session bound to that
     migrated temp DB.
  3. `app.database.migrate_existing.migrate_database` -- the tool that
     brings the live, never-alembic-stamped paper-trading DB up to head
     (ENGINEERING_DECISIONS.md #51) -- still works end-to-end on an
     old-generation DB and lands on the NEW head with both new tables
     present. This proves the live-DB migration path picks up this
     milestone's tables too, without any change to `migrate_existing.py`
     itself (out of this change's scope).

Old-generation DBs for (3) are built the same way `test_migrate_existing.py`
does: via the real migration chain (`command.upgrade(cfg, <revision>)`),
then hiding the `alembic_version` table via RENAME to simulate the
pre-alembic legacy bootstrap `migrate_database` is designed to detect.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from alembic import command

from app.database.migrate_existing import build_alembic_config, migrate_database


def _make_unstamped_legacy_db(tmp_path, revision: str):
    """Build a real DB at `revision` via the actual migration chain, then
    hide `alembic_version` (RENAME, not DROP -- this repo's tooling gates
    destructive SQL keywords even in test fixtures) to simulate the live
    paper DB's never-stamped condition.
    """
    db_path = tmp_path / "legacy.db"
    cfg = build_alembic_config(db_path)
    command.upgrade(cfg, revision)
    conn = sqlite3.connect(str(db_path))
    conn.execute("ALTER TABLE alembic_version RENAME TO not_a_stamp_fixture")
    conn.commit()
    conn.close()
    return db_path


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_upgrade_head_creates_regime_snapshots_table(migrated_db):
    from app.database.session import engine

    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        tables = {
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "regime_snapshots" in tables

        columns = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(regime_snapshots)").fetchall()
        }
    finally:
        conn.close()

    assert columns == {
        "id",
        "captured_at",
        "symbol",
        "timeframe",
        "trend",
        "volatility",
        "breakout",
        "mean_reversion",
        "liquidity_sweep_environment",
        "metrics",
    }


def test_upgrade_head_creates_shadow_signals_table(migrated_db):
    from app.database.session import engine

    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        tables = {
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "shadow_signals" in tables

        columns = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(shadow_signals)").fetchall()
        }
    finally:
        conn.close()

    assert columns == {
        "id",
        "captured_at",
        "symbol",
        "strategy_name",
        "strategy_version",
        "direction",
        "entry_price",
        "stop_loss",
        "take_profit",
        "rr",
        "market_regime",
        "signal_payload",
    }


def test_regime_snapshots_indexes_created(migrated_db):
    from app.database.session import engine

    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        index_names = {
            row[1]
            for row in cursor.execute("PRAGMA index_list(regime_snapshots)").fetchall()
        }
    finally:
        conn.close()

    assert "ix_regime_snapshots_captured_at" in index_names
    assert "ix_regime_snapshots_symbol" in index_names


def test_shadow_signals_indexes_created(migrated_db):
    from app.database.session import engine

    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        index_names = {
            row[1]
            for row in cursor.execute("PRAGMA index_list(shadow_signals)").fetchall()
        }
    finally:
        conn.close()

    assert "ix_shadow_signals_captured_at" in index_names
    assert "ix_shadow_signals_symbol" in index_names
    assert "ix_shadow_signals_strategy_name" in index_names


def test_regime_snapshot_orm_round_trip(db_session):
    from app.database.models import RegimeSnapshot

    row = RegimeSnapshot(
        captured_at=datetime.now(timezone.utc),
        symbol="BTCUSDT",
        timeframe="15m",
        trend="strong_trend",
        volatility="high_volatility",
        breakout=True,
        mean_reversion=False,
        liquidity_sweep_environment=True,
        metrics={"adx": 31.2, "atr": 145.6, "distance_from_ma": 0.021},
    )
    db_session.add(row)
    db_session.commit()

    fetched = db_session.query(RegimeSnapshot).one()
    assert fetched.symbol == "BTCUSDT"
    assert fetched.timeframe == "15m"
    assert fetched.trend == "strong_trend"
    assert fetched.volatility == "high_volatility"
    assert fetched.breakout is True
    assert fetched.mean_reversion is False
    assert fetched.liquidity_sweep_environment is True
    assert fetched.metrics == {"adx": 31.2, "atr": 145.6, "distance_from_ma": 0.021}
    assert fetched.id is not None
    assert fetched.captured_at is not None


def test_regime_snapshot_metrics_nullable(db_session):
    """`metrics` is nullable -- a snapshot can be persisted even when the
    caller has no audit dict to attach."""
    from app.database.models import RegimeSnapshot

    row = RegimeSnapshot(
        captured_at=datetime.now(timezone.utc),
        symbol="ETHUSDT",
        timeframe="1h",
        trend="range",
        volatility="normal_volatility",
        breakout=False,
        mean_reversion=False,
        liquidity_sweep_environment=False,
    )
    db_session.add(row)
    db_session.commit()

    fetched = db_session.query(RegimeSnapshot).one()
    assert fetched.metrics is None


def test_shadow_signal_orm_round_trip(db_session):
    from app.database.models import ShadowSignal

    row = ShadowSignal(
        captured_at=datetime.now(timezone.utc),
        symbol="BTCUSDT",
        strategy_name="jade_v1",
        strategy_version="1.2.0",
        direction="long",
        entry_price=61234.5,
        stop_loss=60800.0,
        take_profit=62500.0,
        rr=2.9,
        market_regime={"trend": "strong_trend", "volatility": "high_volatility"},
        signal_payload={"htf_bias": "bullish", "choch_detected": True},
    )
    db_session.add(row)
    db_session.commit()

    fetched = db_session.query(ShadowSignal).one()
    assert fetched.symbol == "BTCUSDT"
    assert fetched.strategy_name == "jade_v1"
    assert fetched.strategy_version == "1.2.0"
    assert fetched.direction == "long"
    assert fetched.entry_price == 61234.5
    assert fetched.stop_loss == 60800.0
    assert fetched.take_profit == 62500.0
    assert fetched.rr == 2.9
    assert fetched.market_regime == {"trend": "strong_trend", "volatility": "high_volatility"}
    assert fetched.signal_payload == {"htf_bias": "bullish", "choch_detected": True}
    assert fetched.id is not None


def test_shadow_signal_json_fields_nullable(db_session):
    """`market_regime`/`signal_payload` are nullable -- a shadow signal
    can be persisted before/without a regime detector or full-payload
    audit trail attached."""
    from app.database.models import ShadowSignal

    row = ShadowSignal(
        captured_at=datetime.now(timezone.utc),
        symbol="BTCUSDT",
        strategy_name="jade_v1",
        strategy_version=None,
        direction="short",
        entry_price=100.0,
        stop_loss=102.0,
        take_profit=94.0,
        rr=3.0,
    )
    db_session.add(row)
    db_session.commit()

    fetched = db_session.query(ShadowSignal).one()
    assert fetched.market_regime is None
    assert fetched.signal_payload is None
    assert fetched.strategy_version is None


def test_migrate_existing_lands_on_new_head_with_new_tables(tmp_path):
    """The live-DB migration path (`migrate_database`, used against
    `paper_validation.db`) picks up this milestone's tables too: an
    old-generation, never-stamped DB reaches the CURRENT head (this
    migration, not the previous one) and both new tables exist.
    """
    from alembic.script import ScriptDirectory

    db_path = _make_unstamped_legacy_db(tmp_path, "4b8a822a475b")

    report = migrate_database(db_path, backup=False)

    cfg = build_alembic_config(db_path)
    current_head = ScriptDirectory.from_config(cfg).get_current_head()
    assert current_head == "36cb62e9e2ac"
    assert report["head"] == current_head

    assert "regime_snapshots" in report["tables"]
    assert "shadow_signals" in report["tables"]

    conn = sqlite3.connect(str(db_path))
    try:
        regime_cols = _table_columns(conn, "regime_snapshots")
        shadow_cols = _table_columns(conn, "shadow_signals")
    finally:
        conn.close()

    assert "metrics" in regime_cols
    assert "signal_payload" in shadow_cols


def test_migrate_existing_report_still_validates_previous_generation_artifacts(tmp_path):
    """`migrate_database`'s own internal post-migration verification
    (hardcoded to check for `strategy_performance_snapshots` /
    `trades.market_regime` -- the PREVIOUS head's artifacts, milestone
    e3110e6a6b59) still passes unchanged: those artifacts still exist at
    the new head, purely additive migrations never remove them. See this
    test module's docstring / the task's findings note: `migrate_existing.py`
    was NOT edited for this milestone, and this test is the proof that it
    didn't need to be.
    """
    db_path = _make_unstamped_legacy_db(tmp_path, "393afdf7fe67")

    report = migrate_database(db_path, backup=False)

    assert "strategy_performance_snapshots" in report["tables"]
    assert "market_regime" in report["trades_columns"]
    assert "regime_snapshots" in report["tables"]
    assert "shadow_signals" in report["tables"]
