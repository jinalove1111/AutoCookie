"""Shadow-mode strategy-signal observability (Milestone 11, 2026-07-16,
docs/ADAPTIVE_ARCHITECTURE.md sections 2.4/6, ENGINEERING_DECISIONS.md
#53).

Motivation: today regime data only ever persists on `Trade` rows (via
`Trade.market_regime`), and most paper-trading passes -- any pass with no
signal, or a signal that gets rejected/skipped before a trade opens --
persist no regime data at all. Regime-tagged strategy analysis (e.g. "how
would `trend_following` have performed in `range`/`high_volatility`
conditions over the last month, compared to whatever was actually
selected?") starves as a result: there is no per-pass record independent
of whether a trade happened, and no record of what strategies OTHER than
the active one would have done.

This module is `scripts/run_paper.py`'s shadow-mode integration point
(wired in at Milestone 11b, gated by
`settings.ENABLE_SHADOW_STRATEGY_SIGNALS`, default `False`): once per
paper pass, it records one `RegimeSnapshot` row for that pass's
classification (regardless of whether a real signal/trade resulted), and
asks every registered strategy EXCEPT the one actually active this pass
what it would have signaled, persisting one `ShadowSignal` row per
non-`None` answer.

Quarantine discipline, preserved -- not weakened -- by this module:
`app.strategy.experimental.EXPERIMENTAL_STRATEGIES` remains completely
unselectable in production; no real selector
(`app.strategy.selector.ConfigurableFallbackSelector` or any future
Strategy Selection Engine) ever consults it, and nothing in this module
changes that. This module only ever ASKS every strategy
(`app.strategy.experimental.all_strategies()`, production + experimental
combined) what it would do on this pass's real candles, via each
strategy's own `generate_signal` -- it never selects, executes, sizes,
risk-evaluates, or otherwise acts on any answer it gets back. Every write
this module performs is purely observational: a `ShadowSignal` row is
data about what a strategy WOULD have done, not a trade, and nothing
downstream in the real trading pipeline (Risk Engine, ExecutionEngine,
`TradeTracker`) ever reads from `shadow_signals`/`regime_snapshots`.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.database.models import RegimeSnapshot, ShadowSignal
from app.portfolio.trades import session_scope
from app.strategy.experimental import all_strategies

# TradeSignal fields already promoted to their own ShadowSignal columns
# (see app.database.models.ShadowSignal's docstring) -- excluded from
# `signal_payload` so the same value is never stored twice.
_PROMOTED_SIGNAL_FIELDS = {
    "symbol",
    "direction",
    "entry_price",
    "stop_loss",
    "take_profit",
    "rr",
}


def record_shadow_pass(
    symbol: str,
    timeframe: str,
    ltf_candles: list,
    htf_candles: list,
    regime: Any,
    active_strategy_name: str,
    captured_at: Any = None,
) -> dict:
    """Record one shadow-mode observation for a single paper-trading pass.

    (a) Persists one `RegimeSnapshot` row from `regime` (an
    `app.regime.regime_detector.MarketRegime` instance, or `None`). If
    `regime` is `None`, no snapshot row is written -- there is nothing
    real to record -- but this is counted (not silently dropped) in the
    returned summary, and every registered strategy is still evaluated
    below regardless.

    (b) Iterates `all_strategies()` (production + experimental,
    `app.strategy.experimental.all_strategies()`) EXCLUDING whichever
    strategy name matches `active_strategy_name` -- that strategy already
    has a real chance to trade this pass via the normal pipeline; asking
    it again here would just duplicate (not shadow) its own real signal.
    Each remaining strategy's `generate_signal(symbol, ltf_candles,
    htf_candles)` is called inside its own try/except: one strategy
    raising must never block any other strategy from being evaluated, nor
    the pass as a whole -- the exception is WARNed and counted in
    `errors`, and the loop continues. A `None` return (no setup right
    now) is the common case and is simply skipped, not an error.

    Every non-`None` signal is persisted as one `ShadowSignal` row:
    `direction`/`entry_price`/`stop_loss`/`take_profit`/`rr` are promoted
    to real columns (see `_PROMOTED_SIGNAL_FIELDS`); `market_regime` is
    `asdict(regime)` when a regime was supplied, else `None`;
    `signal_payload` is the full `asdict(signal)` MINUS the promoted
    columns, for audit; `strategy_version` comes from the strategy
    instance's own `.version` attribute (falls back to `None` if a
    strategy module doesn't expose one -- defensive, every current
    `Strategy` implementation does).

    Returns a summary dict:
      {
        "snapshot_written": bool,
        "shadow_signals_written": int,
        "strategies_evaluated": int,
        "errors": int,
      }

    This function never raises on a per-strategy failure (see above);
    callers (`scripts/run_paper.py`) additionally wrap the ENTIRE call in
    their own try/except per this codebase's "shadow work must never
    affect trading" discipline -- a failure persisting the
    `RegimeSnapshot` row itself, or any other unexpected error, propagates
    up to that outer guard rather than being swallowed twice here.
    """
    summary = {
        "snapshot_written": False,
        "shadow_signals_written": 0,
        "strategies_evaluated": 0,
        "errors": 0,
    }

    regime_dict = asdict(regime) if regime is not None else None

    if regime is not None:
        with session_scope() as db:
            snapshot_kwargs: dict[str, Any] = dict(
                symbol=symbol,
                timeframe=timeframe,
                trend=regime.trend,
                volatility=regime.volatility,
                breakout=regime.breakout,
                mean_reversion=regime.mean_reversion,
                liquidity_sweep_environment=regime.liquidity_sweep_environment,
                metrics=regime.metrics,
            )
            if captured_at is not None:
                snapshot_kwargs["captured_at"] = captured_at
            db.add(RegimeSnapshot(**snapshot_kwargs))
        summary["snapshot_written"] = True

    for strategy_name, strategy in all_strategies().items():
        if strategy_name == active_strategy_name:
            continue

        summary["strategies_evaluated"] += 1
        try:
            signal = strategy.generate_signal(symbol, ltf_candles, htf_candles)
        except Exception as exc:
            print(f"WARNING: shadow strategy '{strategy_name}' raised ({exc}); skipping.")
            summary["errors"] += 1
            continue

        if signal is None:
            continue

        signal_dict = asdict(signal)
        payload = {k: v for k, v in signal_dict.items() if k not in _PROMOTED_SIGNAL_FIELDS}

        with session_scope() as db:
            row_kwargs: dict[str, Any] = dict(
                symbol=signal.symbol,
                strategy_name=strategy_name,
                strategy_version=getattr(strategy, "version", None),
                direction=signal.direction,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                rr=signal.rr,
                market_regime=regime_dict,
                signal_payload=payload,
            )
            if captured_at is not None:
                row_kwargs["captured_at"] = captured_at
            db.add(ShadowSignal(**row_kwargs))
        summary["shadow_signals_written"] += 1

    return summary
