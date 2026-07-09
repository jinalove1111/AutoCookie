"""DB bootstrap regression tests, pinning what the prior manual audit
verified by hand: a completely fresh (nonexistent) SQLite file boots via
the real FastAPI `lifespan` hook, which runs `alembic upgrade head`
(not a `Base.metadata.create_all()` shortcut) and produces all 6 real
tables plus a matching `alembic_version` row. Also covers idempotency
(second boot against an already-migrated DB is a safe no-op) and
fail-fast behavior on an unparseable DATABASE_URL.
"""

from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text


EXPECTED_TABLES = {
    "bot_state",
    "candles",
    "risk_events",
    "signals",
    "trades",
    "strategy_logs",
}


def test_fresh_sqlite_boots_via_real_alembic_migration(app_main):
    """Boot the FastAPI app against a brand-new, empty SQLite file (no
    prior create_all/alembic run) and confirm the lifespan hook creates
    the real schema via Alembic -- not a shortcut.
    """
    with TestClient(app_main.app) as client:
        response = client.get("/dashboard/status")
        assert response.status_code == 200

    from app.config import settings

    engine = create_engine(settings.DATABASE_URL)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert EXPECTED_TABLES.issubset(tables)

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    # Pinned to the current migration head. Update this alongside adding any
    # new migration (was "a0f5ebc23690" prior to the circuit-breaker
    # persistence columns migration "4b8a822a475b").
    assert version == "4b8a822a475b"
    engine.dispose()


def test_second_boot_against_already_migrated_db_is_idempotent(fresh_app_env):
    """Booting twice against the SAME temp SQLite file (fresh module
    import each time, simulating a real process restart) must not error
    and must not lose previously-persisted state.
    """
    import app.main as main1

    with TestClient(main1.app) as client1:
        client1.post("/settings/mode", json={"trading_mode": "backtest"})
        status = client1.get("/dashboard/status").json()
        assert status["mode"] == "backtest"

    # Simulate a real process restart: purge cached app modules and
    # re-import fresh against the same DATABASE_URL.
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    import app.main as main2

    with TestClient(main2.app) as client2:
        response = client2.get("/dashboard/status")
        assert response.status_code == 200
        # Second boot's `alembic upgrade head` was a no-op -- previously
        # persisted state survives.
        assert response.json()["mode"] == "backtest"


def test_run_migrations_is_a_safe_noop_when_already_at_head(app_main):
    """Calling run_migrations() twice in a row against the same DB
    (without a process restart) must not raise."""
    app_main.run_migrations()
    app_main.run_migrations()  # second call: already at head, no-op

    from app.config import settings

    engine = create_engine(settings.DATABASE_URL)
    inspector = inspect(engine)
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))
    engine.dispose()


def test_fails_fast_on_unparseable_database_url(monkeypatch):
    """An unparseable DATABASE_URL must raise immediately (loudly) when
    the DB engine is constructed, not silently swallow the error and
    continue with a broken app.
    """
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    monkeypatch.setenv("DATABASE_URL", "not-a-valid-sqlalchemy-url")

    with pytest.raises(Exception):
        import app.main  # noqa: F401 - import itself must raise

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
