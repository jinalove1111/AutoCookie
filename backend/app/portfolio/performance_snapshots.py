"""Rolling per-strategy performance metrics + auto-disable mechanism
(operator directive, 2026-07-15, adaptive-platform pivot --
docs/ADAPTIVE_ARCHITECTURE.md section 7, milestone 6). Computes rolling
win_rate/profit_factor/expectancy/max_drawdown/sharpe/sortino/
recovery_factor over a strategy's most recent closed trades and persists
one `StrategyPerformanceSnapshot` row per evaluation (schema added by
milestone 2, decision #44).

Deliberately split into a pure computation function (`compute_rolling_metrics`,
easy to unit test against synthetic trade lists) and a persistence/query
layer (`StrategyPerformanceEvaluator`, which reads real `TradeTracker`
data) -- same separation-of-concerns pattern this project already uses
(e.g. `app.regime.regime_detector`'s standalone helper functions,
decision #45).

Computation-only, matching this project's established "not yet wired
into a decision path" discipline (decisions #19, #23, #24, #45, #46):
`is_disabled` is computed and persisted here, but `DefaultToLegacySelector`
(milestone 4) does not read it yet -- no strategy is actually blocked by
this module today.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.database.models import StrategyPerformanceSnapshot
from app.portfolio.trades import TradeTracker, session_scope

# Duplicated from scripts/experiment_runner.py's MIN_TRADES_FOR_CONFIDENCE
# (decision #41), not imported -- scripts/ and backend/app are separate
# top-level packages with no existing cross-import path. Same value, same
# meaning: below this many trades, "adequate sample size" fails.
MIN_TRADES_FOR_CONFIDENCE = 20

# Disclosed-not-tuned (same status as _STOP_BUFFER/_RR before their
# 2026-07-11 sweep, decision #18): a strategy whose rolling profit factor
# is at or below breakeven over a confidence-worthy window has no
# evidentiary basis to remain enabled.
_AUTO_DISABLE_PROFIT_FACTOR_THRESHOLD = 1.0

# `StrategyPerformanceSnapshot`'s ratio columns (profit_factor, sharpe,
# sortino, recovery_factor) are all non-nullable Float -- but each is
# mathematically UNDEFINED in a genuinely reachable edge case (no losing
# trades in the window; zero variance; zero drawdown). Rather than storing
# NULL (schema doesn't allow it) or Python's inf/NaN (neither round-trips
# cleanly through SQLite/JSON and both are easy to mishandle downstream),
# undefined-because-things-went-well cases are capped at this sentinel --
# a large but finite, directionally honest ("very good, not literally
# infinite") value. Documented here once rather than re-justified at each
# use site below.
_UNDEFINED_RATIO_CAP = 10.0


@dataclass
class RollingMetrics:
    window_trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    max_drawdown: float
    sharpe: float
    sortino: float
    recovery_factor: float


def compute_rolling_metrics(trades: list[dict], account_balance: float) -> RollingMetrics | None:
    """Compute rolling metrics over `trades` (closed-trade dicts, e.g. from
    `TradeTracker.get_closed_trades()`, already filtered/windowed by the
    caller). Returns `None` if `trades` is empty -- there is nothing
    meaningful to compute or persist.

    `account_balance`: `max_drawdown` is expressed as a PERCENT of this
    value (same `settings.PLACEHOLDER_ACCOUNT_BALANCE`-based conversion
    convention `scripts/run_paper.py::_pnl_to_percent` and decision #3
    already established), not a raw dollar figure -- comparable across
    windows/strategies the same way every other percent-of-account figure
    in this codebase already is.

    `expectancy`/`sharpe`/`sortino` are computed over each trade's
    `r_multiple` (already stored at close time, `_check_and_close_open_
    positions`), not raw PnL -- R-multiples are comparable across
    different position sizes/assets, raw PnL is not (same reasoning
    decision #47 used for MAE/MFE). Trades with a `None` r_multiple
    (possible when `risk_per_unit` was 0 at close -- see that function's
    guard) are excluded from the r_multiple-based figures only; they
    still count toward win_rate/profit_factor/max_drawdown, which use
    raw `pnl` instead.

    Disclosed simplification: `sharpe`/`sortino` here are PER-TRADE ratios
    (mean R-multiple / stdev of R-multiples across the window), not the
    textbook PERIODIC-RETURNS Sharpe/Sortino (which needs a fixed time
    interval, e.g. daily returns) -- this codebase has no periodic equity
    series to compute that from, only a sequence of closed trades. A
    reasonable, standard approximation used elsewhere in this space when
    only trade-level data exists, not a claim of textbook exactness (same
    disclosure style as decision #45's ADX simplification).
    """
    if not trades:
        return None

    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    win_rate = len(wins) / n

    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = _UNDEFINED_RATIO_CAP  # no losing trades this window
    else:
        profit_factor = 1.0  # no wins, no losses (all breakeven/unset)

    r_multiples = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    expectancy = (sum(r_multiples) / len(r_multiples)) if r_multiples else 0.0

    cumulative = 0.0
    peak = 0.0
    max_dd_absolute = 0.0
    for t in trades:
        cumulative += t["pnl"]
        peak = max(peak, cumulative)
        max_dd_absolute = max(max_dd_absolute, peak - cumulative)
    max_drawdown = (max_dd_absolute / account_balance) * 100 if account_balance > 0 else 0.0

    sharpe = 0.0
    sortino = 0.0
    if len(r_multiples) >= 2:
        mean_r = sum(r_multiples) / len(r_multiples)
        variance = sum((r - mean_r) ** 2 for r in r_multiples) / len(r_multiples)
        stdev = math.sqrt(variance)
        if stdev > 0:
            sharpe = mean_r / stdev

        downside = [r for r in r_multiples if r < 0]
        if downside:
            downside_variance = sum(r**2 for r in downside) / len(downside)
            downside_stdev = math.sqrt(downside_variance)
            if downside_stdev > 0:
                sortino = mean_r / downside_stdev
        elif mean_r > 0:
            sortino = _UNDEFINED_RATIO_CAP  # no downside observations at all this window

    total_pnl = sum(t["pnl"] for t in trades)
    if max_dd_absolute > 0:
        recovery_factor = total_pnl / max_dd_absolute
    elif total_pnl > 0:
        recovery_factor = _UNDEFINED_RATIO_CAP  # profitable with zero observed drawdown
    else:
        recovery_factor = 0.0

    return RollingMetrics(
        window_trades=n,
        win_rate=win_rate,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_drawdown=max_drawdown,
        sharpe=sharpe,
        sortino=sortino,
        recovery_factor=recovery_factor,
    )


class StrategyPerformanceEvaluator:
    """Queries real closed trades for one `strategy_name` (optionally
    scoped to one `market_regime`), computes `RollingMetrics` over the
    most recent `window_trades`, and persists one
    `StrategyPerformanceSnapshot` row -- auto-disabling the strategy in
    the SAME snapshot if the window has reached `MIN_TRADES_FOR_CONFIDENCE`
    and `profit_factor` has fallen to or below
    `_AUTO_DISABLE_PROFIT_FACTOR_THRESHOLD`.
    """

    def evaluate_and_snapshot(
        self,
        strategy_name: str,
        account_balance: float,
        market_regime: str | None = None,
        window_trades: int = MIN_TRADES_FOR_CONFIDENCE,
    ) -> int | None:
        """Returns the new snapshot's id, or `None` if there were no
        matching closed trades to evaluate (no-op, not an error -- a
        strategy/regime combination simply hasn't traded yet).

        `market_regime`, when supplied, matches against the `trend`
        dimension of `Trade.market_regime` (the full `MarketRegime`
        audit dict persisted per-trade, decision #44/#49) -- NOT the
        whole composite classification. `StrategyPerformanceSnapshot.
        market_regime` is a single `String(32)` grouping key by schema
        design (section 6.3), and `trend` (strong_trend/weak_trend/range)
        is the primary partition among the composite's dimensions, same
        judgment call this project has made before for genuinely
        ambiguous prose (decision #21).
        """
        trades = TradeTracker().get_closed_trades()
        trades = [t for t in trades if t.get("strategy_name") == strategy_name]
        if market_regime is not None:
            trades = [
                t
                for t in trades
                if isinstance(t.get("market_regime"), dict)
                and t["market_regime"].get("trend") == market_regime
            ]
        trades.sort(key=lambda t: t["closed_at"])
        recent = trades[-window_trades:] if window_trades > 0 else trades

        metrics = compute_rolling_metrics(recent, account_balance)
        if metrics is None:
            return None

        is_disabled = (
            metrics.window_trades >= MIN_TRADES_FOR_CONFIDENCE
            and metrics.profit_factor <= _AUTO_DISABLE_PROFIT_FACTOR_THRESHOLD
        )
        disabled_reason = (
            f"Rolling profit factor {metrics.profit_factor:.2f} <= "
            f"{_AUTO_DISABLE_PROFIT_FACTOR_THRESHOLD} over the last "
            f"{metrics.window_trades} trades."
            if is_disabled
            else None
        )

        with session_scope() as db:
            snapshot = StrategyPerformanceSnapshot(
                strategy_name=strategy_name,
                market_regime=market_regime,
                window_trades=metrics.window_trades,
                win_rate=metrics.win_rate,
                profit_factor=metrics.profit_factor,
                expectancy=metrics.expectancy,
                max_drawdown=metrics.max_drawdown,
                sharpe=metrics.sharpe,
                sortino=metrics.sortino,
                recovery_factor=metrics.recovery_factor,
                is_disabled=is_disabled,
                disabled_reason=disabled_reason,
            )
            db.add(snapshot)
            db.flush()
            snapshot_id = snapshot.id
        return snapshot_id

    def latest_snapshot(
        self, strategy_name: str, market_regime: str | None = None
    ) -> dict[str, Any] | None:
        """Returns the most recently computed snapshot for `strategy_name`
        (optionally scoped to `market_regime`) as a plain dict, or `None`
        if none exists yet. Read path used by `is_strategy_disabled` below
        (milestone 7's Risk Engine disable hook) and, in future, by
        section 4.3's `RollingPerformanceSelector` (not yet built)."""
        with session_scope() as db:
            from sqlalchemy import select

            query = select(StrategyPerformanceSnapshot).where(
                StrategyPerformanceSnapshot.strategy_name == strategy_name
            )
            if market_regime is not None:
                query = query.where(StrategyPerformanceSnapshot.market_regime == market_regime)
            # Tie-break on `id` (monotonically increasing), not `computed_at`
            # alone -- SQLite's `CURRENT_TIMESTAMP` server_default only has
            # SECOND-level resolution, so two snapshots computed within the
            # same second (a real possibility: consecutive trade closes,
            # or this evaluator called back-to-back in a fast loop/test)
            # would otherwise tie and sort non-deterministically.
            query = query.order_by(
                StrategyPerformanceSnapshot.computed_at.desc(),
                StrategyPerformanceSnapshot.id.desc(),
            ).limit(1)
            row = db.execute(query).scalars().first()
            if row is None:
                return None
            return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    def is_strategy_disabled(self, strategy_name: str, market_regime: str | None = None) -> bool:
        """Convenience wrapper around `latest_snapshot` for the Risk Engine's
        per-strategy disable hook (`docs/ADAPTIVE_ARCHITECTURE.md` section
        5.2, milestone 7). Fails OPEN, not closed: returns `False` (not
        disabled) when no snapshot exists yet for this strategy -- the
        absence of evidence is not evidence of a problem, same "no data yet
        -> safe default" reasoning `DefaultToLegacySelector` (decision #46)
        already established at the selection layer."""
        snapshot = self.latest_snapshot(strategy_name, market_regime)
        if snapshot is None:
            return False
        return bool(snapshot["is_disabled"])
