"""
FastAPI application entrypoint for JadeCap Trading Bot (Milestone 1).

This wires together the API routers only. It contains NO strategy, risk,
or exchange execution logic. Routes currently return stub/placeholder data.
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_health import router as health_router
from app.api.routes_settings import router as settings_router
from app.api.routes_trades import router as trades_router
from app.config import settings

app = FastAPI(
    title="JadeCap Trading Bot API",
    description="Milestone 1 architecture/foundation skeleton (no live trading logic).",
    version="0.1.0",
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
