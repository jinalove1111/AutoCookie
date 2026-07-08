"""
Milestone 4: real Discord alert dispatch via an incoming webhook. Gated by
ENABLE_DISCORD_ALERTS / DISCORD_WEBHOOK_URL from app.config.settings.
Never raises -- a Discord outage or misconfiguration must never crash the
caller (the paper-trading loop).
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def send_discord_alert(message: str) -> None:
    """
    Send an alert message to Discord.

    Reads DISCORD_WEBHOOK_URL from app.config.settings.
    Gated by the ENABLE_DISCORD_ALERTS config flag -- when disabled or
    unconfigured, this is a clean no-op. Real HTTP failures (network errors
    or non-2xx responses) are caught and logged, never raised.
    """
    if not settings.ENABLE_DISCORD_ALERTS or not settings.DISCORD_WEBHOOK_URL:
        logger.debug("discord alerts disabled or unconfigured, skipping")
        return

    try:
        response = httpx.post(
            settings.DISCORD_WEBHOOK_URL,
            json={"content": message},
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("discord alert failed: %s", exc)
    except Exception as exc:  # noqa: BLE001 - final safety net, must never raise
        logger.error("discord alert failed unexpectedly: %s", exc)
