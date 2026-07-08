"""Backtest engine: replays historical candles through Strategy/Risk Engine.

BACKTEST_MODE only. Never places live orders, never imports execution/.
"""

from dataclasses import dataclass, field
from typing import Any

from app.backtesting.performance import calculate_max_drawdown, calculate_win_rate

MIN_CANDLES = 31  # need index 30 available (30 candles of prior history)


@dataclass
class BacktestResult:
    """Holds the outcome of a single backtest run."""

    total_trades: int
    win_rate: float
    total_pnl: float
    max_drawdown: float
    trades: list = field(default_factory=list)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute/key access that works for both dict-shaped and object-shaped candles."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class BacktestEngine:
    """Simulates strategy execution over historical data without placing live orders."""

    def run(
        self,
        candles: list,
        signal_engine: Any,
        risk_manager: Any,
        account_balance: float = 10000.0,
        fee_percent: float = 0.05,
        slippage_percent: float = 0.02,
    ) -> "BacktestResult":
        """Replays historical candles through the Strategy Engine and Risk Engine to
        simulate trades, including fee and slippage (BACKTEST_MODE). No live orders
        are ever placed.

        Walk-forward, expanding window, one trade open at a time (no overlap):
        starts at index MIN_CANDLES - 1 so signal generation always has history.
        """
        if len(candles) < MIN_CANDLES:
            return BacktestResult(total_trades=0, win_rate=0.0, total_pnl=0.0, max_drawdown=0.0)

        trades: list = []
        equity_curve = [account_balance]
        trades_today = 0
        current_day: str | None = None

        i = MIN_CANDLES - 1
        while i < len(candles):
            day = str(_get(candles[i], "timestamp"))[:10]
            if day != current_day:
                current_day = day
                trades_today = 0

            symbol = _get(candles[i], "symbol") or "UNKNOWN"
            signal = signal_engine.generate_signal(symbol=symbol, candles=candles[: i + 1])
            if signal is None:
                i += 1
                continue

            risk_decision = risk_manager.evaluate(signal, trades_today=trades_today)
            if not getattr(risk_decision, "approved", False):
                i += 1
                continue

            trades_today += 1
            trade, exit_index, account_balance = self._simulate_trade(
                signal, candles, i, account_balance, fee_percent, slippage_percent
            )
            trades.append(trade)
            equity_curve.append(account_balance)
            i = exit_index + 1

        total_pnl = sum(t["pnl"] for t in trades)
        return BacktestResult(
            total_trades=len(trades),
            win_rate=calculate_win_rate(trades),
            total_pnl=total_pnl,
            max_drawdown=calculate_max_drawdown(equity_curve),
            trades=trades,
        )

    def _simulate_trade(
        self,
        signal: Any,
        candles: list,
        entry_index: int,
        account_balance: float,
        fee_percent: float,
        slippage_percent: float,
    ) -> tuple[dict, int, float]:
        """Fills entry (with unfavorable slippage), scans forward for SL/TP, and
        returns (trade_record, exit_index, updated_account_balance).

        Position sizing simplification: each trade risks the full current
        account_balance as notional (simple compounding), since no position
        sizing model is wired in for this milestone.
        """
        entry_price = getattr(signal, "entry_price")
        stop_loss = getattr(signal, "stop_loss")
        take_profit = getattr(signal, "take_profit")
        direction = str(getattr(signal, "direction", "") or "").lower()
        is_long = direction in ("long", "buy")

        slip = slippage_percent / 100
        entry_fill = entry_price * (1 + slip) if is_long else entry_price * (1 - slip)

        exit_price = None
        exit_index = len(candles) - 1
        for j in range(entry_index + 1, len(candles)):
            high = _get(candles[j], "high")
            low = _get(candles[j], "low")
            if is_long:
                hit_sl = low is not None and stop_loss is not None and low <= stop_loss
                hit_tp = high is not None and take_profit is not None and high >= take_profit
            else:
                hit_sl = high is not None and stop_loss is not None and high >= stop_loss
                hit_tp = low is not None and take_profit is not None and low <= take_profit

            # If both levels fall within this candle's range, assume the worse
            # (stop_loss) outcome hit first — the conservative assumption.
            if hit_sl:
                exit_price = stop_loss
                exit_index = j
                break
            if hit_tp:
                exit_price = take_profit
                exit_index = j
                break

        if exit_price is None:
            exit_price = _get(candles[exit_index], "close")

        if is_long:
            price_return = (exit_price - entry_fill) / entry_fill
        else:
            price_return = (entry_fill - exit_price) / entry_fill

        fee_fraction = (fee_percent / 100) * 2  # applied on entry + exit notional
        net_return = price_return - fee_fraction
        pnl = account_balance * net_return
        account_balance += pnl

        trade = {
            "entry_price": entry_fill,
            "exit_price": exit_price,
            "pnl": pnl,
            "opened_at": _get(candles[entry_index], "timestamp"),
            "closed_at": _get(candles[exit_index], "timestamp"),
            "direction": direction,
        }
        return trade, exit_index, account_balance
