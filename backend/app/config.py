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

    # No real account-balance source exists yet (see scripts/run_paper.py's
    # module docstring) -- used as the fixed denominator for position
    # sizing and for converting realized PnL into daily/weekly loss-limit
    # percentages, consistently, across scripts/run_paper.py and the
    # /dashboard/risk-status endpoint (both need the exact same base or
    # their percentages would silently disagree).
    #
    # Scope decision (operator, 2026-07-11, Phase 1 scope lock): this
    # placeholder is INTENTIONALLY kept for the entire Phase 1 pipeline
    # (Backtest -> Walk-Forward -> Paper Trading). Paper trading has no
    # real capital regardless, so a fixed placeholder is honest and
    # sufficient. Replacing it with a real, live-queried exchange balance
    # is explicitly deferred to Phase 1 gate #4 (Small Live Validation,
    # see ROADMAP.md) -- that is the point where a real balance feed
    # becomes unavoidable (real capital, real risk), not before. Do not
    # build real-balance wiring during Phase 1 without operator approval.
    PLACEHOLDER_ACCOUNT_BALANCE: float = 10000.0

    # --- Alerts ---
    ENABLE_TELEGRAM_ALERTS: bool = False
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    ENABLE_DISCORD_ALERTS: bool = False
    DISCORD_WEBHOOK_URL: str = ""

    # --- Experimental strategy/execution features (opt-in, A/B validated
    # in BacktestEngine before being offered here -- see
    # docs/strategy_coverage_audit.md and ENGINEERING_DECISIONS.md) ---
    #
    # Break-even stop management: reproduced positive on two independent
    # backtest samples (+13.5% on a ~31-day sample, +9.2% on a 6-month
    # sample -- see CHANGELOG.md), the strongest of the three findings.
    # `BREAKEVEN_TRIGGER_R` is shared with `BacktestEngine`'s own
    # `use_breakeven` A/B-test path (imported from here, not duplicated)
    # so paper trading and backtesting always agree on the same trigger
    # distance -- ENABLE_BREAKEVEN itself only gates scripts/run_paper.py;
    # BacktestEngine.run()'s per-call `use_breakeven` flag stays
    # independent of this setting (backtesting needs to A/B test with
    # both on and off regardless of the "production" paper setting).
    ENABLE_BREAKEVEN: bool = False
    BREAKEVEN_TRIGGER_R: float = 1.0

    # Jade engine (opt-in, default off): unlike ENABLE_BREAKEVEN above,
    # this was wired into scripts/run_paper.py per explicit operator
    # instruction (2026-07-12) BEFORE any A/B backtest evidence exists --
    # a deliberate reversal of this project's usual "evidence first, then
    # offer in paper trading" sequence (see ENGINEERING_DECISIONS.md #35).
    # Default False preserves the exact prior behavior for every existing
    # run; do not flip this to True without real backtest evidence first.
    USE_JADE_ENGINE: bool = False

    # Strategy Selection Engine routing (opt-in, default off -- adaptive
    # platform milestone 7b, operator directive 2026-07-16,
    # ENGINEERING_DECISIONS.md #50). False (the default) preserves the
    # EXACT prior scripts/run_paper.py call path (direct
    # SignalEngine().generate_signal(..., use_jade_engine=USE_JADE_ENGINE)
    # call), byte-for-byte -- flipping this flag does not, by itself,
    # change USE_JADE_ENGINE's own meaning: ConfigurableFallbackSelector
    # still honors USE_JADE_ENGINE as an explicit operator override and
    # otherwise falls back to "legacy" deterministically. True routes
    # signal generation through the Strategy Selection Engine instead
    # (adds regime detection + selection-reason logging/persistence, no
    # automatic regime-based switching). Read ENGINEERING_DECISIONS.md #50
    # before flipping.
    USE_STRATEGY_SELECTOR: bool = False

    # Shadow-mode strategy-signal observability (opt-in, default off --
    # Milestone 11, 2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md sections
    # 2.4/6, ENGINEERING_DECISIONS.md #53). False (the default) preserves
    # today's scripts/run_paper.py behavior EXACTLY -- nothing new runs,
    # not even a regime computation, beyond the single flag check at the
    # shadow block's entry. True makes every paper-trading pass record one
    # `RegimeSnapshot` row and, for every registered strategy
    # (`app.strategy.experimental.all_strategies()`) EXCEPT whichever one
    # is actually active this pass, a `ShadowSignal` row whenever that
    # strategy would have produced a signal on this pass's real candles.
    # Observability only: this NEVER trades and NEVER gates a real
    # decision -- see `app.portfolio.shadow_recorder`'s module docstring
    # for the "quarantine intact" discipline this preserves.
    ENABLE_SHADOW_STRATEGY_SIGNALS: bool = False

    # Multi-symbol shadow collection (opt-in, default off -- Milestone 17a,
    # 2026-07-16, docs/REGIME_PERFORMANCE_ANALYSIS.md). Motivation: that
    # analysis found evidence accumulation to be this platform's binding
    # constraint -- 8 of 9 regime buckets evidence-starved -- and today
    # shadow data (RegimeSnapshot/ShadowSignal rows, see
    # ENABLE_SHADOW_STRATEGY_SIGNALS above) only ever accrues from the ONE
    # symbol scripts/run_paper.py actually trades (`settings.SYMBOL`, e.g.
    # "BTCUSDT"). Comma-separated extra symbols here (e.g.
    # "ETHUSDT,SOLUSDT,XRPUSDT" -- this project's standard validation set)
    # are evaluated for shadow-only regime snapshots/signals/outcome
    # resolution ONLY, multiplying evidence throughput roughly N-fold at
    # zero production risk: nothing in `SHADOW_SYMBOLS` is ever traded, and
    # this setting is only even consulted when
    # `ENABLE_SHADOW_STRATEGY_SIGNALS` is also True (see
    # `scripts/run_paper.py`'s shadow block). Default "" (empty) preserves
    # today's behavior EXACTLY -- an empty string parses to zero extra
    # symbols, so the shadow block's existing single-symbol
    # (`settings.SYMBOL`) behavior is untouched byte-for-byte; this is a
    # pure opt-in, the operator/launcher must explicitly set it to collect
    # extra-symbol evidence.
    SHADOW_SYMBOLS: str = ""

    # Minimum stop-distance-as-ATR-multiple gate (opt-in, default off --
    # Milestone 18b, 2026-07-16, docs/RESEARCH_ROUND_1.md recommendation
    # #2). docs/ROBUSTNESS_REPORT.md traced the dead candidate's execution-
    # delay failure to a root cause: its stop averaged just 0.17-0.23% of
    # price, tighter than routine single-candle movement, so ANY delay
    # invalidated its risk geometry. Standard practice per Wilder-
    # convention literature is stops of 1.5-3.0x ATR -- disclosed here as
    # the literature's convention, NOT as an operator-tuned value; no
    # backtest evidence for a specific multiple exists yet on this
    # platform. 0.0 (the default) DISABLES the gate and preserves prior
    # `RiskManager.evaluate()` behavior EXACTLY, including for signals
    # with very tight stops -- this is the same "implemented is not
    # evidenced" discipline every other experimental flag in this file
    # follows (see USE_JADE_ENGINE, ENABLE_BREAKEVEN above). IMPORTANT:
    # this gate changes trade ACCEPTANCE when enabled (it can reject
    # signals that would otherwise pass) and MUST be A/B backtest-
    # evaluated in `BacktestEngine` before being enabled in paper trading.
    # Do not flip this above 0.0 without that evidence.
    MIN_STOP_ATR_MULT: float = 0.0

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
