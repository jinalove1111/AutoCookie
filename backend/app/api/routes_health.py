"""Health check endpoints — used by uptime monitors and deployment probes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/")
def healthcheck() -> dict:
    """Return basic liveness status; future: DB/redis connectivity checks."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/ready")
def readiness() -> dict:
    """Return readiness status; future: verify DB/exchange connections are warm."""
    return {"status": "ready", "checks": {"database": "stub", "redis": "stub"}}
