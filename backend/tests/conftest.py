"""Shared pytest fixtures for the backend regression suite.

Central problem these fixtures solve: `app.config.settings` is a
module-level singleton (`settings = get_settings()`, cached via
`lru_cache`) and `app.database.session` binds a real SQLAlchemy `engine`
to `settings.DATABASE_URL` at IMPORT time. Neither is designed to be
reconfigured after import. To get a fresh, isolated SQLite database per
test we therefore:

  1. Point `DATABASE_URL` at a brand-new temp sqlite file (via
     `monkeypatch.setenv`, auto-restored after the test).
  2. Purge every previously-imported `app` / `app.*` module from
     `sys.modules` so the *next* `import app.xxx` re-executes each
     module's top-level code against the new environment (fresh
     `Settings()`, fresh `create_engine(...)`, fresh `SessionLocal`).

This mirrors the pattern the prior manual audit used to verify DB
bootstrap: set `DATABASE_URL` to a temp sqlite path BEFORE importing
`app.main`, then boot (via `TestClient`, which drives the real FastAPI
`lifespan` hook -> `alembic upgrade head`) against a completely empty
file.

Test modules that need DB-backed objects (TradeTracker,
get_or_create_bot_state, StrategyLog, ...) must import them *inside* the
test function body (after depending on one of the fixtures below), not
at module import time -- otherwise they would bind to whatever module
instance happened to be cached first during collection.
"""

from __future__ import annotations

import sys
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


def _purge_app_modules() -> None:
    """Drop every `app` / `app.*` module from sys.modules.

    Forces the next `import app.xxx` anywhere to re-run that module's
    top-level code (re-reading env vars, rebuilding the DB engine, etc.)
    instead of silently reusing a stale cached module bound to a
    previous test's temp database.
    """
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


@pytest.fixture()
def sqlite_url(tmp_path) -> str:
    """A `sqlite:///` URL pointing at a brand-new, nonexistent file per test."""
    db_file = tmp_path / "jadecap_test.db"
    return f"sqlite:///{db_file.as_posix()}"


@pytest.fixture()
def fresh_app_env(monkeypatch: pytest.MonkeyPatch, sqlite_url: str) -> Iterator[str]:
    """Point DATABASE_URL at a fresh temp sqlite file and purge cached
    `app.*` modules so the next import picks it up. Yields the URL.
    """
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    _purge_app_modules()
    yield sqlite_url
    _purge_app_modules()


@pytest.fixture()
def app_main(fresh_app_env: str):
    """Import `app.main` fresh, bound to this test's temp SQLite DB.

    Importing alone does not touch the database -- migrations only run
    when the FastAPI `lifespan` hook fires (see the `client` fixture) or
    when `run_migrations()` is called explicitly (see `migrated_db`).
    """
    import app.main as main

    return main


@pytest.fixture()
def migrated_db(app_main):
    """Run the real `alembic upgrade head` (the same function the
    lifespan hook calls) against this test's temp SQLite DB, without
    booting the full FastAPI TestClient. For tests that need real DB
    persistence (e.g. app.portfolio.*, app.database bootstrap checks)
    without exercising the HTTP layer.
    """
    app_main.run_migrations()
    return app_main


@pytest.fixture()
def client(app_main) -> Iterator[TestClient]:
    """A TestClient bound to a fresh temp SQLite DB. Entering the
    context manager triggers the real FastAPI `lifespan` hook, which
    runs `alembic upgrade head` against the empty file -- the real DB
    bootstrap path, not a `Base.metadata.create_all()` shortcut.
    """
    with TestClient(app_main.app) as test_client:
        yield test_client


@pytest.fixture()
def db_session(migrated_db) -> Iterator["Session"]:  # noqa: F821 - typing only
    """A raw SQLAlchemy session against the same migrated temp SQLite DB
    the `client`/`migrated_db` fixtures use, for tests needing direct DB
    access without going through the HTTP layer.
    """
    from app.database.session import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
