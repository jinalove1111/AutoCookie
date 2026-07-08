"""
Milestone 4: real Telegram alert dispatch via the Bot API's sendMessage
endpoint. Gated by ENABLE_TELEGRAM_ALERTS / TELEGRAM_BOT_TOKEN /
TELEGRAM_CHAT_ID from app.config.settings. Never raises -- a Telegram
outage or misconfiguration must never crash the caller (the paper-trading
loop).
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def send_telegram_alert(message: str) -> None:
    """
    Send an alert message to Telegram.

    Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from app.config.settings.
    Gated by the ENABLE_TELEGRAM_ALERTS config flag -- when disabled or
    unconfigured, this is a clean no-op. Real HTTP failures (network errors
    or non-2xx responses) are caught and logged, never raised.
    """
    if (
        not settings.ENABLE_TELEGRAM_ALERTS
        or not settings.TELEGRAM_BOT_TOKEN
        or not settings.TELEGRAM_CHAT_ID
    ):
        logger.debug("telegram alerts disabled or unconfigured, skipping")
        return

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = httpx.post(
            url,
            json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("telegram alert failed: %s", exc)
    except Exception as exc:  # noqa: BLE001 - final safety net, must never raise
        logger.error("telegram alert failed unexpectedly: %s", exc)
