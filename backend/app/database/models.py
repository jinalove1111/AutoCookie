"""
SQLAlchemy 2.0 declarative models for JadeCap trading bot (Milestone 1).

Schema source of truth until Alembic migrations are initialized
(see database/migrations/README.md). Six tables:
candles, signals, trades, risk_events, bot_state, strategy_logs.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# --------------------------------------------------------------------------
# candles — raw OHLCV market data ingested per symbol/timeframe/exchange.
# --------------------------------------------------------------------------
class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "timeframe", "timestamp", "exchange",
            name="uq_candles_symbol_timeframe_timestamp_exchange",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# signals — strategy-generated trade signals awaiting approval/execution.
# --------------------------------------------------------------------------
class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # long/short
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    htf_bias: Mapped[str] = mapped_column(String(16), nullable=False)
    sweep_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    choch_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fvg_zone: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    rr: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )  # pending/approved/rejected/executed
    # Observability follow-up (2026-07-12 profitability sprint, Phase E):
    # WHY a rejected signal was rejected was never persisted -- only visible
    # in that process's own stdout/summary dict at the moment it happened.
    # Nullable/additive: existing rows and every existing caller that never
    # passes a reason are unaffected.
    rejection_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# trades — executed trades across backtest/paper/live modes.
# --------------------------------------------------------------------------
class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    size: Mapped[float] = mapped_column(Float, nullable=False)
    leverage: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # open/closed/cancelled
    mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # backtest/paper/live
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Observability follow-up (2026-07-12 profitability sprint, Phase E):
    # three fields that were computable in-process at the moment of the
    # decision but never persisted, so a later query over the trades table
    # couldn't recover WHY a position closed, what R it realized, or which
    # experimental-flag configuration produced it. All three nullable/
    # additive -- existing rows and every existing caller (backtest reports
    # never touch the trades DB at all; paper trading callers that don't
    # pass these keep getting NULL, same as before this change) are
    # unaffected.
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)  # stop_loss/take_profit/breakeven/manual
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Adaptive-platform follow-up (2026-07-15, docs/ADAPTIVE_ARCHITECTURE.md
    # section 6.2, ENGINEERING_DECISIONS.md #44): six more fields, all
    # nullable/additive, same discipline as the three above. `market_regime`
    # stores the FULL MarketRegime classification (not just a label) at
    # signal time, once a Regime Detector exists to populate it.
    # `strategy_name` promotes the existing `strategy_config` JSON's
    # implicit info into a real, indexed column for fast per-strategy
    # rollups. `holding_time_seconds` is derivable from opened_at/closed_at
    # but stored explicitly so rolling-metrics queries don't recompute it
    # per row. `max_adverse_excursion`/`max_favorable_excursion`/
    # `latency_ms` require NEW tracking (not just a schema change) in
    # whichever loop checks open positions -- columns exist now so that
    # tracking has somewhere real to write to when it's built.
    market_regime: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    strategy_name: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    holding_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# risk_events — risk-management alerts/violations raised during trading.
# --------------------------------------------------------------------------
class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(1024), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # info/warning/critical
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )


# --------------------------------------------------------------------------
# bot_state — singleton-ish row(s) tracking current bot operating state.
# --------------------------------------------------------------------------
class BotState(Base):
    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # backtest/paper/live
    live_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    daily_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    weekly_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_drawdown: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trading_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    circuit_breaker_tripped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    circuit_breaker_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    circuit_breaker_tripped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# strategy_logs — audit trail of strategy module decisions/reasoning.
# --------------------------------------------------------------------------
class StrategyLog(Base):
    __tablename__ = "strategy_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )
    module: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    candle_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id"), nullable=True, index=True
    )


# --------------------------------------------------------------------------
# strategy_performance_snapshots — rolling per-strategy/per-regime
# performance metrics, computed periodically (not per-trade). Adaptive-
# platform milestone 2 (2026-07-15, docs/ADAPTIVE_ARCHITECTURE.md section
# 6.3, ENGINEERING_DECISIONS.md #44): a discrete, timestamped, auditable
# evaluation event, not a live-recomputed-on-every-read query -- keeps
# "what did rolling win rate look like as of this snapshot" answerable
# consistently regardless of how much trade history has accumulated
# since. `market_regime` nullable = an all-regime aggregate row;
# non-null = a per-regime rollup for that strategy.
# --------------------------------------------------------------------------
class StrategyPerformanceSnapshot(Base):
    __tablename__ = "strategy_performance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    market_regime: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    window_trades: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )
    win_rate: Mapped[float] = mapped_column(Float, nullable=False)
    profit_factor: Mapped[float] = mapped_column(Float, nullable=False)
    expectancy: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    sharpe: Mapped[float] = mapped_column(Float, nullable=False)
    sortino: Mapped[float] = mapped_column(Float, nullable=False)
    recovery_factor: Mapped[float] = mapped_column(Float, nullable=False)
    is_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disabled_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)


# --------------------------------------------------------------------------
# regime_snapshots / shadow_signals — shadow-mode observability (Milestone
# 11, 2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md sections 2.4/6). Motivation:
# regime data was previously persisted only on `Trade.market_regime`
# (milestone 2/5) and Strategy Selection Engine decisions only existed in
# process stdout -- most paper passes produce NO trade at all, so
# regime-tagged analysis accumulated only at trade speed, not pass speed.
# These two tables give every paper pass a persisted, per-pass record
# regardless of whether a trade resulted. Schema-only: wiring (writing to
# these tables from the paper trading loop, behind a default-off flag) is
# milestone 11b, not this change.
# --------------------------------------------------------------------------
class RegimeSnapshot(Base):
    """One row per market-regime classification performed during a paper
    pass, independent of whether a signal/trade resulted. `metrics` stores
    the FULL `MarketRegime.metrics` audit dict (see
    `app.regime.regime_detector.MarketRegime`), the same "store the whole
    classification, not just a label" principle `Trade.market_regime`
    already follows -- trend/volatility/breakout/mean_reversion/
    liquidity_sweep_environment are promoted to real columns for fast
    per-regime rollups, mirroring `MarketRegime`'s own field shape.
    """

    __tablename__ = "regime_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    trend: Mapped[str] = mapped_column(String(32), nullable=False)
    volatility: Mapped[str] = mapped_column(String(32), nullable=False)
    breakout: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mean_reversion: Mapped[bool] = mapped_column(Boolean, nullable=False)
    liquidity_sweep_environment: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ShadowSignal(Base):
    """One row per shadow signal actually generated (a no-signal pass
    writes nothing here -- `RegimeSnapshot` is the per-pass record; this
    table is per-signal). `market_regime` carries the `MarketRegime`
    classification active at signal time (same full-dict principle as
    `Trade.market_regime`); `signal_payload` carries the full
    `app.strategy.signal_engine.TradeSignal` asdict, minus whatever is
    already promoted to its own column below, for audit.

    Milestone 14, 2026-07-16: `outcome`/`resolved_at`/`resolved_r` are the
    outcome-resolution fields a future resolver (Milestone 14b) fills in by
    walking candles subsequent to `captured_at`. All three are nullable and
    start NULL (an "open"/unresolved shadow signal); the DB does not enforce
    the semantics below -- the resolver does:

      - `outcome`: one of `"tp"` (take-profit level touched first),
        `"sl"` (stop-loss level touched first), or `"expired"` (the signal
        aged past the resolver's lookahead window without either level
        being touched -- neither a win nor a loss, just undecided).
      - `resolved_at`: UTC timestamp of when the resolver settled the
        signal (i.e. when it wrote a non-NULL `outcome`).
      - `resolved_r`: the realized R multiple. `+rr` (this row's own `rr`
        column) when `outcome == "tp"`, `-1.0` when `outcome == "sl"`, and
        `NULL` when `outcome == "expired"` (no realized R for an
        undecided signal).
    """

    __tablename__ = "shadow_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    strategy_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    strategy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    rr: Mapped[float] = mapped_column(Float, nullable=False)
    market_regime: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    signal_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_r: Mapped[float | None] = mapped_column(Float, nullable=True)
