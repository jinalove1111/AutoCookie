"""
Application configuration for JadeCap Trading Bot.

Loads all runtime configuration from environment variables (or a .env file)
via pydantic-settings. This module contains NO trading/strategy/exchange
logic. It only exposes typed settings and a safety gate
(`is_live_trading_allowed`) that downstream engines must consult before
ever placing a live order.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_TRADING_MODES = {"backtest", "paper", "live"}


class Settings(BaseSettings):
    """Typed, validated application settings sourced from environment vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- App / environment ---
    APP_ENV: str = "development"
    TRADING_MODE: str = "paper"
    LIVE_TRADING_ENABLED: bool = False

    # --- Market / exchange selection ---
    EXCHANGE: str = "okx"
    SYMBOL: str = "BTCUSDT"
    DEFAULT_TIMEFRAME: str = "5m"
    HTF_TIMEFRAME: str = "4h"

    # --- Exchange credentials (never logged, never printed) ---
    OKX_API_KEY: str = ""
    OKX_API_SECRET: str = ""
    OKX_API_PASSPHRASE: str = ""
    ORANGEX_API_KEY: str = ""
    ORANGEX_API_SECRET: str = ""

    # --- Infra ---
    DATABASE_URL: str = ""
    REDIS_URL: str = ""

    # --- Risk parameters ---
    MAX_DAILY_LOSS_PERCENT: float = 1
    MAX_WEEKLY_LOSS_PERCENT: float = 3
    RISK_PER_TRADE_PERCENT: float = 0.25
    MAX_TRADES_PER_DAY: int = 2
    MIN_RR: float = 2

    # --- Alerts ---
    ENABLE_TELEGRAM_ALERTS: bool = False
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    ENABLE_DISCORD_ALERTS: bool = False
    DISCORD_WEBHOOK_URL: str = ""

    @field_validator("TRADING_MODE")
    @classmethod
    def validate_trading_mode(cls, value: str) -> str:
        """Ensure TRADING_MODE is one of the supported modes."""
        normalized = value.strip().lower()
        if normalized not in VALID_TRADING_MODES:
            raise ValueError(
                f"TRADING_MODE must be one of {sorted(VALID_TRADING_MODES)}, got {value!r}"
            )
        return normalized

    @property
    def is_live_trading_allowed(self) -> bool:
        """
        Safety-critical gate. True ONLY when TRADING_MODE == 'live' AND
        LIVE_TRADING_ENABLED is explicitly True. Every execution/order path
        must check this before sending anything to a real exchange.
        """
        return self.TRADING_MODE == "live" and self.LIVE_TRADING_ENABLED is True


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


settings = get_settings()
