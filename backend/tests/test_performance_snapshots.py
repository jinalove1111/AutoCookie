"""Tests for app.portfolio.performance_snapshots: rolling per-strategy
metrics + auto-disable (operator directive, 2026-07-15,
docs/ADAPTIVE_ARCHITECTURE.md section 7, milestone 6).

`app.*` modules are imported INSIDE each test function, not at module
level -- see conftest.py's module docstring: `app.database.session`
binds a real SQLAlchemy engine to `settings.DATABASE_URL` at IMPORT
time, so importing eagerly at collection time would bind to a stale
engine from whichever test happened to import first.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _trade(pnl: float, r_multiple: float | None, idx: int = 0) -> dict:
    return {"pnl": pnl, "r_multiple": r_multiple, "closed_at": _BASE + timedelta(minutes=idx)}


# --- compute_rolling_metrics (pure function) --------------------------------


def test_compute_rolling_metrics_none_for_empty_list(migrated_db):
    from app.portfolio.performance_snapshots import compute_rolling_metrics

    assert compute_rolling_metrics([], account_balance=1000.0) is None


def test_compute_rolling_metrics_basic_win_rate_and_profit_factor(migrated_db):
    from app.portfolio.performance_snapshots import compute_rolling_metrics

    trades = [
        _trade(pnl=10.0, r_multiple=2.0, idx=0),
        _trade(pnl=10.0, r_multiple=2.0, idx=1),
        _trade(pnl=-5.0, r_multiple=-1.0, idx=2),
        _trade(pnl=-5.0, r_multiple=-1.0, idx=3),
    ]
    metrics = compute_rolling_metrics(trades, account_balance=1000.0)
    assert metrics is not None
    assert metrics.window_trades == 4
    assert metrics.win_rate == 0.5
    assert metrics.profit_factor == 2.0  # 20 gross profit / 10 gross loss
    assert metrics.expectancy == 0.5  # mean of [2, 2, -1, -1]


def test_compute_rolling_metrics_caps_profit_factor_when_no_losses(migrated_db):
    from app.portfolio.performance_snapshots import compute_rolling_metrics

    trades = [_trade(pnl=10.0, r_multiple=2.0, idx=i) for i in range(3)]
    metrics = compute_rolling_metrics(trades, account_balance=1000.0)
    assert metrics.profit_factor == 10.0  # _UNDEFINED_RATIO_CAP, not inf


def test_compute_rolling_metrics_profit_factor_one_when_all_breakeven(migrated_db):
    from app.portfolio.performance_snapshots import compute_rolling_metrics

    trades = [_trade(pnl=0.0, r_multiple=0.0, idx=i) for i in range(3)]
    metrics = compute_rolling_metrics(trades, account_balance=1000.0)
    assert metrics.profit_factor == 1.0


def test_compute_rolling_metrics_max_drawdown_percent_of_account_balance(migrated_db):
    from app.portfolio.performance_snapshots import compute_rolling_metrics

    # Cumulative pnl path: +10 (peak=10) -> -30 (drawdown from 10 to -20 == 30) -> +5
    trades = [
        _trade(pnl=10.0, r_multiple=1.0, idx=0),
        _trade(pnl=-30.0, r_multiple=-3.0, idx=1),
        _trade(pnl=5.0, r_multiple=0.5, idx=2),
    ]
    metrics = compute_rolling_metrics(trades, account_balance=100.0)
    assert metrics.max_drawdown == 30.0  # 30 / 100 * 100%


def test_compute_rolling_metrics_sharpe_zero_when_insufficient_or_zero_variance(migrated_db):
    from app.portfolio.performance_snapshots import compute_rolling_metrics

    # Only 1 trade -- insufficient sample for a variance-based ratio.
    metrics = compute_rolling_metrics([_trade(pnl=10.0, r_multiple=1.0)], account_balance=1000.0)
    assert metrics.sharpe == 0.0
    assert metrics.sortino == 0.0

    # Identical r_multiples -- zero variance.
    trades = [_trade(pnl=10.0, r_multiple=1.0, idx=i) for i in range(3)]
    metrics = compute_rolling_metrics(trades, account_balance=1000.0)
    assert metrics.sharpe == 0.0


def test_compute_rolling_metrics_sortino_caps_when_no_downside_observations(migrated_db):
    from app.portfolio.performance_snapshots import compute_rolling_metrics

    trades = [_trade(pnl=10.0, r_multiple=r, idx=i) for i, r in enumerate([1.0, 2.0, 3.0])]
    metrics = compute_rolling_metrics(trades, account_balance=1000.0)
    assert metrics.sortino == 10.0  # _UNDEFINED_RATIO_CAP: positive mean, no losers to measure downside from


def test_compute_rolling_metrics_recovery_factor_variants(migrated_db):
    from app.portfolio.performance_snapshots import compute_rolling_metrics

    # Zero drawdown, profitable -> capped.
    trades = [_trade(pnl=10.0, r_multiple=1.0, idx=i) for i in range(3)]
    assert compute_rolling_metrics(trades, account_balance=1000.0).recovery_factor == 10.0

    # Zero drawdown, non-positive total pnl (all breakeven) -> 0.0.
    trades = [_trade(pnl=0.0, r_multiple=0.0, idx=i) for i in range(3)]
    assert compute_rolling_metrics(trades, account_balance=1000.0).recovery_factor == 0.0

    # Real drawdown -> total_pnl / max_dd_absolute.
    trades = [
        _trade(pnl=20.0, r_multiple=2.0, idx=0),
        _trade(pnl=-10.0, r_multiple=-1.0, idx=1),
    ]
    metrics = compute_rolling_metrics(trades, account_balance=1000.0)
    assert metrics.recovery_factor == 1.0  # total_pnl 10 / max_dd_absolute 10


def test_compute_rolling_metrics_expectancy_falls_back_to_zero_without_r_multiples(migrated_db):
    from app.portfolio.performance_snapshots import compute_rolling_metrics

    trades = [_trade(pnl=10.0, r_multiple=None, idx=i) for i in range(3)]
    metrics = compute_rolling_metrics(trades, account_balance=1000.0)
    assert metrics.expectancy == 0.0


# --- StrategyPerformanceEvaluator (real DB round-trip) ----------------------


def _seed_closed_trade(
    tracker, *, strategy_name: str, pnl: float, r_multiple: float | None, idx: int = 0
) -> int:
    trade_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "size": 1.0,
            "mode": "paper",
            "strategy_name": strategy_name,
            "opened_at": _BASE + timedelta(minutes=idx),
        }
    )
    tracker.close_trade(
        trade_id,
        exit_price=100.0 + pnl,
        pnl=pnl,
        closed_at=_BASE + timedelta(minutes=idx, seconds=30),
        r_multiple=r_multiple,
    )
    return trade_id


def test_evaluator_returns_none_when_no_matching_trades(migrated_db):
    from app.portfolio.performance_snapshots import StrategyPerformanceEvaluator

    result = StrategyPerformanceEvaluator().evaluate_and_snapshot(
        "legacy", account_balance=1000.0
    )
    assert result is None


def test_evaluator_persists_snapshot_and_ignores_other_strategies(migrated_db):
    from app.portfolio.performance_snapshots import StrategyPerformanceEvaluator
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    _seed_closed_trade(tracker, strategy_name="legacy", pnl=10.0, r_multiple=2.0, idx=0)
    _seed_closed_trade(tracker, strategy_name="legacy", pnl=-5.0, r_multiple=-1.0, idx=1)
    _seed_closed_trade(tracker, strategy_name="jade", pnl=-1000.0, r_multiple=-50.0, idx=2)

    snapshot_id = StrategyPerformanceEvaluator().evaluate_and_snapshot(
        "legacy", account_balance=1000.0
    )
    assert isinstance(snapshot_id, int)

    snapshot = StrategyPerformanceEvaluator().latest_snapshot("legacy")
    assert snapshot["strategy_name"] == "legacy"
    assert snapshot["window_trades"] == 2  # jade's trade excluded
    assert snapshot["is_disabled"] is False


def test_evaluator_auto_disables_only_at_or_above_confidence_floor(migrated_db):
    from app.portfolio.performance_snapshots import (
        MIN_TRADES_FOR_CONFIDENCE,
        StrategyPerformanceEvaluator,
    )
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    # 5 losing trades -- well below MIN_TRADES_FOR_CONFIDENCE (20), so even
    # though profit_factor is 0 (all losses), auto-disable must NOT trigger.
    for i in range(5):
        _seed_closed_trade(tracker, strategy_name="legacy", pnl=-10.0, r_multiple=-2.0, idx=i)

    StrategyPerformanceEvaluator().evaluate_and_snapshot("legacy", account_balance=1000.0)
    snapshot = StrategyPerformanceEvaluator().latest_snapshot("legacy")
    assert snapshot["window_trades"] == 5
    assert snapshot["is_disabled"] is False
    assert snapshot["disabled_reason"] is None

    # Add enough more losing trades to reach the confidence floor.
    for i in range(5, MIN_TRADES_FOR_CONFIDENCE):
        _seed_closed_trade(tracker, strategy_name="legacy", pnl=-10.0, r_multiple=-2.0, idx=i)

    StrategyPerformanceEvaluator().evaluate_and_snapshot("legacy", account_balance=1000.0)
    snapshot = StrategyPerformanceEvaluator().latest_snapshot("legacy")
    assert snapshot["window_trades"] == MIN_TRADES_FOR_CONFIDENCE
    assert snapshot["is_disabled"] is True
    assert "profit factor" in snapshot["disabled_reason"].lower()


def test_evaluator_scopes_to_market_regime_when_given(migrated_db):
    from app.portfolio.performance_snapshots import StrategyPerformanceEvaluator
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    trade_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "size": 1.0,
            "mode": "paper",
            "strategy_name": "legacy",
        }
    )
    tracker.close_trade(trade_id, exit_price=110.0, pnl=10.0, r_multiple=2.0)

    # Regime column was never populated on this trade -- scoping to a
    # specific regime must find nothing.
    result = StrategyPerformanceEvaluator().evaluate_and_snapshot(
        "legacy", account_balance=1000.0, market_regime="strong_trend"
    )
    assert result is None

    # Unscoped (market_regime=None, the default) finds it.
    result = StrategyPerformanceEvaluator().evaluate_and_snapshot(
        "legacy", account_balance=1000.0
    )
    assert isinstance(result, int)


def test_evaluator_scopes_by_trend_label_within_the_full_market_regime_dict(migrated_db):
    """Trade.market_regime stores the FULL MarketRegime audit dict
    (adaptive platform milestone 7) -- scoping must match against its
    `trend` key, not compare the dict itself to the filter string."""
    from app.portfolio.performance_snapshots import StrategyPerformanceEvaluator
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    trending_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "size": 1.0,
            "mode": "paper",
            "strategy_name": "legacy",
            "market_regime": {"trend": "strong_trend", "volatility": "normal_volatility"},
        }
    )
    tracker.close_trade(trending_id, exit_price=110.0, pnl=10.0, r_multiple=2.0)

    ranging_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "size": 1.0,
            "mode": "paper",
            "strategy_name": "legacy",
            "market_regime": {"trend": "range", "volatility": "normal_volatility"},
        }
    )
    tracker.close_trade(ranging_id, exit_price=95.0, pnl=-5.0, r_multiple=-1.0)

    result = StrategyPerformanceEvaluator().evaluate_and_snapshot(
        "legacy", account_balance=1000.0, market_regime="strong_trend"
    )
    assert isinstance(result, int)
    snapshot = StrategyPerformanceEvaluator().latest_snapshot("legacy", market_regime="strong_trend")
    assert snapshot["window_trades"] == 1
    assert snapshot["win_rate"] == 1.0  # only the strong_trend trade (a winner) counted


# --- StrategyPerformanceEvaluator.is_strategy_disabled ----------------------


def test_is_strategy_disabled_false_when_no_snapshot_exists_yet(migrated_db):
    from app.portfolio.performance_snapshots import StrategyPerformanceEvaluator

    assert StrategyPerformanceEvaluator().is_strategy_disabled("legacy") is False


def test_is_strategy_disabled_reflects_latest_snapshot(migrated_db):
    from app.portfolio.performance_snapshots import (
        MIN_TRADES_FOR_CONFIDENCE,
        StrategyPerformanceEvaluator,
    )
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    for i in range(MIN_TRADES_FOR_CONFIDENCE):
        _seed_closed_trade(tracker, strategy_name="legacy", pnl=-10.0, r_multiple=-2.0, idx=i)

    evaluator = StrategyPerformanceEvaluator()
    assert evaluator.is_strategy_disabled("legacy") is False  # no snapshot computed yet

    evaluator.evaluate_and_snapshot("legacy", account_balance=1000.0)
    assert evaluator.is_strategy_disabled("legacy") is True


def test_evaluator_window_trades_caps_at_window_size_using_most_recent(migrated_db):
    from app.portfolio.performance_snapshots import StrategyPerformanceEvaluator
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    # 25 winning trades, then 20 losing trades -- with a window of 20, only
    # the most recent 20 (all losing) should be considered.
    for i in range(25):
        _seed_closed_trade(tracker, strategy_name="legacy", pnl=10.0, r_multiple=2.0, idx=i)
    for i in range(25, 45):
        _seed_closed_trade(tracker, strategy_name="legacy", pnl=-10.0, r_multiple=-2.0, idx=i)

    StrategyPerformanceEvaluator().evaluate_and_snapshot(
        "legacy", account_balance=1000.0, window_trades=20
    )
    snapshot = StrategyPerformanceEvaluator().latest_snapshot("legacy")
    assert snapshot["window_trades"] == 20
    assert snapshot["win_rate"] == 0.0  # the most recent 20 were all losses
