"""Performance metrics for backtest results.

Stdlib-only implementation (no numpy/pandas) — see repo constraint: numpy has
no prebuilt wheel for this Python/OS combo and no C compiler is available.
"""

import statistics


def calculate_win_rate(trades: list) -> float:
    """Returns the fraction (0.0-1.0) of trades that closed with positive PnL.

    Each trade is a dict with at least a "pnl" key. Returns 0.0 for an empty
    list of trades.
    """
    if not trades:
        return 0.0
    winners = sum(1 for trade in trades if trade["pnl"] > 0)
    return winners / len(trades)


def calculate_max_drawdown(equity_curve: list) -> float:
    """Returns the largest peak-to-trough percentage decline in equity_curve.

    equity_curve is a list of cumulative equity values in chronological order.
    Returns 0.0 for an empty or single-point curve, or if the running peak is
    ever <= 0 (avoids a division by zero / nonsensical percentage).
    """
    if len(equity_curve) < 2:
        return 0.0

    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            drawdown = (peak - value) / peak
            if drawdown > max_dd:
                max_dd = drawdown
    return max_dd


def calculate_sharpe_ratio(returns: list) -> float:
    """Returns a simplified risk-adjusted return (mean / population stdev).

    Simplification: no annualization is applied for this milestone — this is
    a plain mean-over-stdev ratio on whatever period the caller's `returns`
    represent (e.g. per-trade). Returns 0.0 if fewer than 2 returns are given
    or if the stdev is 0 (avoids ZeroDivisionError).
    """
    if len(returns) < 2:
        return 0.0
    stdev = statistics.pstdev(returns)
    if stdev == 0:
        return 0.0
    return statistics.mean(returns) / stdev


def calculate_profit_factor(trades: list) -> float:
    """Returns gross profit / abs(gross loss) across all trades.

    Each trade is a dict with at least a "pnl" key. If there are no losing
    trades: returns float('inf') when there is at least one winning trade,
    otherwise 0.0 (no trades at all, or all trades break exactly even).
    """
    gross_profit = sum(trade["pnl"] for trade in trades if trade["pnl"] > 0)
    gross_loss = sum(trade["pnl"] for trade in trades if trade["pnl"] < 0)

    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / abs(gross_loss)
