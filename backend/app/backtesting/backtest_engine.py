"""Backtest engine: replays historical candles through Strategy/Risk Engine.

BACKTEST_MODE only. Never places live orders, never imports execution/.
"""

from dataclasses import dataclass, field
from typing import Any

from app.backtesting.performance import calculate_max_drawdown, calculate_win_rate

MIN_CANDLES = 31  # need index 30 available (30 candles of prior LTF history)

# MIN_CANDLES sizing note (deliberate, not an oversight): MIN_CANDLES is sized
# only for LTF history and is NOT enough runway to ever have real (non-empty)
# HTF history for realistic timeframe ratios -- e.g. DEFAULT_TIMEFRAME=5m /
# HTF_TIMEFRAME=4h means one HTF bar = 48 LTF candles, so even ONE closed HTF
# candle needs ~48+ LTF candles of runway, and detect_htf_bias() itself
# requires >=10 HTF candles (with >=2 swing highs/lows each) before it will
# return anything other than "neutral" -- i.e. several hundred LTF candles,
# far more than MIN_CANDLES=31. This is intentionally left as-is rather than
# raised: `_advance_htf_cursor` degrades safely when no HTF candle has closed
# yet (htf_cursor stays -1, an empty [] slice is passed), and
# `detect_htf_bias([])`/`detect_htf_bias(<10 candles>)` already safely return
# "neutral", which `build_entry_model` then safely rejects (no signal, no
# crash, no lookahead) -- so raising MIN_CANDLES would only skip some early
# no-op iterations, not fix or prevent any correctness issue.


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


def _advance_htf_cursor(htf_candles: list, htf_cursor: int, ltf_timestamp: Any) -> int:
    """Advance (never rewind) `htf_cursor` to the largest HTF index `k` that is
    provably fully closed as of `ltf_timestamp`.

    No-lookahead invariant: an HTF candle at index `k` is provably closed once
    HTF candle `k + 1` exists with `htf_candles[k + 1].timestamp <= ltf_timestamp`
    -- the next bar can only have opened after the prior one closed. This
    sidesteps needing to parse/hardcode the HTF timeframe's duration (fragile).

    Both `htf_candles` and the caller's successive `ltf_timestamp` values are
    assumed sorted oldest-to-newest and non-decreasing across calls, so
    `htf_cursor` only ever advances forward -- callers should maintain one
    cursor instance across a whole walk-forward loop (O(n) total across the
    loop) rather than rescanning from the start of `htf_candles` on every
    step.

    Returns -1 (unchanged, or newly so) if not even one HTF candle has fully
    closed yet relative to `ltf_timestamp`; callers should then pass an empty
    HTF slice (`htf_candles[:0]`), which downstream bias detection already
    handles safely (returns "neutral").
    """
    while (
        htf_cursor + 2 < len(htf_candles)
        and _get(htf_candles[htf_cursor + 2], "timestamp") <= ltf_timestamp
    ):
        htf_cursor += 1
    return htf_cursor


class BacktestEngine:
    """Simulates strategy execution over historical data without placing live orders."""

    def run(
        self,
        ltf_candles: list,
        htf_candles: list,
        signal_engine: Any,
        risk_manager: Any,
        account_balance: float = 10000.0,
        fee_percent: float = 0.05,
        slippage_percent: float = 0.02,
    ) -> "BacktestResult":
        """Replays historical LTF candles (with a time-aligned, no-lookahead
        HTF slice at each step) through the Strategy Engine and Risk Engine
        to simulate trades, including fee and slippage (BACKTEST_MODE). No
        live orders are ever placed.

        Walk-forward, expanding window, one trade open at a time (no
        overlap): starts at index MIN_CANDLES - 1 so LTF signal generation
        always has history. At each LTF step `i`, the HTF slice passed to
        `signal_engine.generate_signal()` contains ONLY HTF candles that had
        genuinely, fully closed by `ltf_candles[i]`'s timestamp -- see
        `_advance_htf_cursor` for the no-lookahead mechanism. `htf_candles`
        may be a genuinely separate, independently-fetched series (real
        usage) or empty/short (degrades safely to "neutral" HTF bias, no
        crash).
        """
        if len(ltf_candles) < MIN_CANDLES:
            return BacktestResult(total_trades=0, win_rate=0.0, total_pnl=0.0, max_drawdown=0.0)

        trades: list = []
        equity_curve = [account_balance]
        trades_today = 0
        current_day: str | None = None
        htf_cursor = -1

        i = MIN_CANDLES - 1
        while i < len(ltf_candles):
            day = str(_get(ltf_candles[i], "timestamp"))[:10]
            if day != current_day:
                current_day = day
                trades_today = 0

            symbol = _get(ltf_candles[i], "symbol") or "UNKNOWN"

            ltf_timestamp = _get(ltf_candles[i], "timestamp")
            htf_cursor = _advance_htf_cursor(htf_candles, htf_cursor, ltf_timestamp)
            htf_slice = htf_candles[: htf_cursor + 1]

            signal = signal_engine.generate_signal(
                symbol=symbol,
                ltf_candles=ltf_candles[: i + 1],
                htf_candles=htf_slice,
            )
            if signal is None:
                i += 1
                continue

            risk_decision = risk_manager.evaluate(signal, trades_today=trades_today)
            if not getattr(risk_decision, "approved", False):
                i += 1
                continue

            trades_today += 1
            trade, exit_index, account_balance = self._simulate_trade(
                signal, ltf_candles, i, account_balance, fee_percent, slippage_percent
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
        ltf_candles: list,
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
        exit_index = len(ltf_candles) - 1
        for j in range(entry_index + 1, len(ltf_candles)):
            high = _get(ltf_candles[j], "high")
            low = _get(ltf_candles[j], "low")
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
            exit_price = _get(ltf_candles[exit_index], "close")

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
            "opened_at": _get(ltf_candles[entry_index], "timestamp"),
            "closed_at": _get(ltf_candles[exit_index], "timestamp"),
            "direction": direction,
        }
        return trade, exit_index, account_balance
