"""Tests for the Milestone 14a (2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md
section 4.3) shadow-signal outcome-resolution schema: the `outcome` /
`resolved_at` / `resolved_r` columns added to `shadow_signals` (Milestone
11) by migration `65aba13281ad` (chained on `36cb62e9e2ac`) and the
matching additions to the `ShadowSignal` ORM model in
`app.database.models`.

This is a schema-only milestone -- nothing yet resolves shadow signals
against subsequent candles (that's milestone 14b). These tests prove
three things:

  1. `alembic upgrade head` adds the three new columns and the `outcome`
     index to `shadow_signals` (via the `migrated_db`/`db_session`
     fixtures in conftest.py, the same real-migration-driven bootstrap
     `app.main`'s FastAPI lifespan uses).
  2. A shadow signal round-trips through the ORM model as "open"
     (`outcome` NULL) and then as "resolved" (`outcome`/`resolved_at`/
     `resolved_r` populated via an update), both readable back correctly.
  3. `app.database.migrate_existing.migrate_database` -- the tool that
     brings the live, never-alembic-stamped paper-trading DB up to head
     (ENGINEERING_DECISIONS.md #51) -- still works end-to-end on an
     old-generation DB and lands on the NEW head with the new columns
     present. This proves the live-DB migration path picks up this
     milestone's columns too, without any change to `migrate_existing.py`
     itself (out of this change's scope).

Old-generation DBs for (3) are built the same way
`test_shadow_observability_schema.py`/`test_migrate_existing.py` do: via
the real migration chain (`command.upgrade(cfg, <revision>)`), then
hiding the `alembic_version` table via RENAME to simulate the
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


def test_upgrade_head_adds_outcome_columns_to_shadow_signals(migrated_db):
    from app.database.session import engine

    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        columns = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(shadow_signals)").fetchall()
        }
    finally:
        conn.close()

    # Milestone 18c (docs/RESEARCH_ROUND_1.md recommendation #3, migration
    # "6b085b904777") added "resolution_model" on top of this milestone's
    # three columns -- update this set alongside any future additive
    # shadow_signals migration.
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
        "outcome",
        "resolved_at",
        "resolved_r",
        "resolution_model",
    }


def test_outcome_index_created(migrated_db):
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

    assert "ix_shadow_signals_outcome" in index_names
    # Prior indexes (Milestone 11) still present -- purely additive.
    assert "ix_shadow_signals_captured_at" in index_names
    assert "ix_shadow_signals_strategy_name" in index_names
    assert "ix_shadow_signals_symbol" in index_names


def test_shadow_signal_orm_round_trip_open_then_resolved(db_session):
    """A shadow signal is inserted "open" (outcome NULL, the resolver
    hasn't run yet), then updated in place to "resolved" the way
    Milestone 14b's resolver will, and both states read back correctly.
    """
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
    assert fetched.outcome is None
    assert fetched.resolved_at is None
    assert fetched.resolved_r is None

    resolved_at = datetime.now(timezone.utc)
    fetched.outcome = "tp"
    fetched.resolved_at = resolved_at
    fetched.resolved_r = fetched.rr
    db_session.commit()

    reread = db_session.query(ShadowSignal).one()
    assert reread.outcome == "tp"
    assert reread.resolved_at is not None
    assert reread.resolved_r == 2.9


def test_shadow_signal_sl_outcome_resolved_r_is_negative_one(db_session):
    from app.database.models import ShadowSignal

    row = ShadowSignal(
        captured_at=datetime.now(timezone.utc),
        symbol="ETHUSDT",
        strategy_name="jade_v1",
        strategy_version=None,
        direction="short",
        entry_price=100.0,
        stop_loss=102.0,
        take_profit=94.0,
        rr=3.0,
        outcome="sl",
        resolved_at=datetime.now(timezone.utc),
        resolved_r=-1.0,
    )
    db_session.add(row)
    db_session.commit()

    fetched = db_session.query(ShadowSignal).one()
    assert fetched.outcome == "sl"
    assert fetched.resolved_r == -1.0
    assert fetched.resolved_at is not None


def test_shadow_signal_expired_outcome_resolved_r_is_null(db_session):
    from app.database.models import ShadowSignal

    row = ShadowSignal(
        captured_at=datetime.now(timezone.utc),
        symbol="ETHUSDT",
        strategy_name="jade_v1",
        strategy_version=None,
        direction="short",
        entry_price=100.0,
        stop_loss=102.0,
        take_profit=94.0,
        rr=3.0,
        outcome="expired",
        resolved_at=datetime.now(timezone.utc),
        resolved_r=None,
    )
    db_session.add(row)
    db_session.commit()

    fetched = db_session.query(ShadowSignal).one()
    assert fetched.outcome == "expired"
    assert fetched.resolved_r is None
    assert fetched.resolved_at is not None


def test_migrate_existing_lands_on_new_head_with_outcome_columns(tmp_path):
    """The live-DB migration path (`migrate_database`, used against
    `paper_validation.db`) picks up this milestone's columns too: an
    old-generation, never-stamped DB reaches the CURRENT head (this
    migration, not the previous one) and the new `shadow_signals`
    columns exist.
    """
    from alembic.script import ScriptDirectory

    db_path = _make_unstamped_legacy_db(tmp_path, "4b8a822a475b")

    report = migrate_database(db_path, backup=False)

    cfg = build_alembic_config(db_path)
    current_head = ScriptDirectory.from_config(cfg).get_current_head()
    # Head-pin: was "65aba13281ad" prior to Milestone 18c's
    # "resolution_model" migration ("6b085b904777") -- update alongside
    # any future additive shadow_signals migration.
    assert current_head == "6b085b904777"
    assert report["head"] == current_head

    assert "shadow_signals" in report["tables"]

    conn = sqlite3.connect(str(db_path))
    try:
        shadow_cols = _table_columns(conn, "shadow_signals")
    finally:
        conn.close()

    assert {"outcome", "resolved_at", "resolved_r", "resolution_model"}.issubset(shadow_cols)


def test_migrate_existing_report_still_validates_previous_generation_artifacts(tmp_path):
    """`migrate_database`'s own internal post-migration verification
    (hardcoded to check for `strategy_performance_snapshots` /
    `trades.market_regime` -- an even earlier head's artifacts, milestone
    e3110e6a6b59) still passes unchanged: those artifacts still exist at
    the new head, purely additive migrations never remove them. See this
    test module's docstring: `migrate_existing.py` was NOT edited for
    this milestone, and this test is the proof that it didn't need to be.
    """
    db_path = _make_unstamped_legacy_db(tmp_path, "393afdf7fe67")

    report = migrate_database(db_path, backup=False)

    assert "strategy_performance_snapshots" in report["tables"]
    assert "market_regime" in report["trades_columns"]
    assert "shadow_signals" in report["tables"]

    conn = sqlite3.connect(str(db_path))
    try:
        shadow_cols = _table_columns(conn, "shadow_signals")
    finally:
        conn.close()

    assert {"outcome", "resolved_at", "resolved_r", "resolution_model"}.issubset(shadow_cols)
