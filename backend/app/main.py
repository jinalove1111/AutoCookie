"""
FastAPI application entrypoint for JadeCap Trading Bot.

This wires together the API routers, DB-backed lifespan startup (automatic
`alembic upgrade head`), and CORS. It contains no strategy, risk, or exchange
execution logic itself — that lives in app/strategy, app/risk, app/execution.
Most routes are wired to real DB-backed data (dashboard status/positions/logs,
trades, settings/mode); a few dashboard endpoints (market bias, recent
signals, risk status) remain intentional placeholders pending live strategy
state wiring.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_health import router as health_router
from app.api.routes_settings import router as settings_router
from app.api.routes_trades import router as trades_router
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# backend/app/main.py -> parents[1] == backend/
BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"


def run_migrations() -> None:
    """Run `alembic upgrade head` programmatically against the real Alembic
    setup (backend/alembic.ini + app/database/migrations/env.py).

    This does NOT duplicate env.py's URL-resolution logic: env.py itself
    reads settings.DATABASE_URL at runtime. We only point Alembic at the
    existing ini file and invoke the same "upgrade head" command the CLI
    would run. Idempotent: a DB already at head is a safe no-op. Failures
    are intentionally allowed to propagate so the app fails fast if its
    schema cannot be established.
    """
    logger.info("Startup: checking DB schema via alembic upgrade head (%s)", ALEMBIC_INI_PATH)
    cfg = Config(str(ALEMBIC_INI_PATH))
    command.upgrade(cfg, "head")
    logger.info("Startup: DB schema is up to date (alembic upgrade head complete).")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    run_migrations()
    yield


app = FastAPI(
    title="JadeCap Trading Bot API",
    description="Paper/backtest trading bot API, real DB-backed (no live trading logic).",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(dashboard_router)
app.include_router(trades_router)
app.include_router(settings_router)


@app.get("/", tags=["root"])
def read_root() -> dict:
    """Basic root endpoint confirming the API is up and its trading mode."""
    return {
        "app": "jadecap-bot",
        "env": settings.APP_ENV,
        "trading_mode": settings.TRADING_MODE,
    }


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
