"""Settings endpoints — read/update runtime bot settings (e.g. paper vs live mode).

The live-mode switch is safety-gated: it is only ever accepted if
`config.settings.is_live_trading_allowed` is True. Otherwise it is rejected
with 403 and an explanation, regardless of what the caller requests.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/settings", tags=["settings"])


class TradingModeUpdate(BaseModel):
    trading_mode: str


@router.get("/mode")
def get_trading_mode() -> dict:
    """Return the current trading mode and whether live trading is permitted."""
    return {
        "trading_mode": settings.TRADING_MODE,
        "live_trading_enabled": settings.LIVE_TRADING_ENABLED,
        "is_live_trading_allowed": settings.is_live_trading_allowed,
    }


@router.post("/mode")
def set_trading_mode(payload: TradingModeUpdate) -> dict:
    """Attempt to switch trading mode; future: persist to config/DB.

    Any switch to 'live' is rejected with 403 unless
    settings.is_live_trading_allowed is True (TRADING_MODE=live AND
    LIVE_TRADING_ENABLED=true in the environment).
    """
    requested_mode = payload.trading_mode.strip().lower()

    if requested_mode == "live" and not settings.is_live_trading_allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                "Live trading is not allowed. Requires TRADING_MODE=live AND "
                "LIVE_TRADING_ENABLED=true in the environment configuration. "
                "This is a Milestone 1 safety gate; no live orders can be placed."
            ),
        )

    return {"requested_mode": requested_mode, "applied": False, "note": "stub: not yet persisted"}
