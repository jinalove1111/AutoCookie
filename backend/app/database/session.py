"""
SQLAlchemy 2.0 engine/session setup for JadeCap trading bot.

Provides a module-level `engine`, a `SessionLocal` sessionmaker, and a
`get_db()` generator suitable for use as a FastAPI dependency:

    @router.get("/example")
    def example(db: Session = Depends(get_db)):
        ...

Reads the database connection string from `app.config.settings`. Note:
`app/config` is expected to expose a `settings.DATABASE_URL` attribute
(e.g. a Pydantic BaseSettings instance) — that module is owned outside
this scope (app/database) and is assumed to already exist or land
alongside this file.
"""

from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI-style dependency that yields a DB session and ensures it closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
