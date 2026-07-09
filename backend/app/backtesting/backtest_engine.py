"""Backtest engine: replays historical candles through Strategy/Risk Engine.

BACKTEST_MODE only. Never places live orders, never imports execution/.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any

from app.backtesting.performance import calculate_max_drawdown, calculate_win_rate
from app.config import settings
from app.risk.position_sizing import calculate_position_size

MIN_CANDLES = 31  # need index 30 available (30 candles of prior LTF history)

# Break-even move trigger, in multiples of the trade's own initial risk
# (R = |entry_fill - stop_loss|). 1.0 (move stop to entry once price has
# moved 1R in favor) is the standard, simplest convention -- not
# backtested/tuned to a different multiple, same "reasonable starting
# default, disclosed as such" spirit as entry_model.py's _RR/_STOP_BUFFER.
# Only takes effect when `BacktestEngine.run(..., use_breakeven=True)` --
# see that parameter's docstring for why this is opt-in, not default-on:
# `OrderManager.move_to_breakeven()` (Execution layer) has existed since
# Milestone 3 but was never wired into any live/paper/backtest trade path
# (see docs/strategy_coverage_audit.md) -- this is the first real,
# empirically-tested integration of it, and it is NOT yet proven to
# improve results (a break-even move can just as easily turn an eventual
# full winner into a scratch trade on a pullback-then-continuation move
# as it can protect against a full loss on a reversal).
BREAKEVEN_TRIGGER_R = 1.0

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


def _day_bounds(ts: datetime) -> tuple[datetime, datetime]:
    """UTC calendar day `[00:00:00.000000, 23:59:59.999999]` containing `ts`.

    Mirrors `app.portfolio.journal.TradeJournal.generate_daily_report()`'s
    boundary exactly (see docs/risk_rules.md's "Daily/weekly boundary
    convention"), so a backtest's notion of "today" for loss-limit purposes
    matches what paper/live trading will actually use.
    """
    day = ts.date()
    return (
        datetime.combine(day, time.min, tzinfo=timezone.utc),
        datetime.combine(day, time.max, tzinfo=timezone.utc),
    )


def _week_bounds(ts: datetime) -> tuple[datetime, datetime]:
    """ISO calendar week (Monday 00:00:00.000000 UTC through Sunday
    23:59:59.999999 UTC) containing `ts`. Mirrors
    `TradeJournal.generate_weekly_report()`'s boundary exactly.
    """
    monday = ts.date() - timedelta(days=ts.weekday())
    sunday = monday + timedelta(days=6)
    return (
        datetime.combine(monday, time.min, tzinfo=timezone.utc),
        datetime.combine(sunday, time.max, tzinfo=timezone.utc),
    )


def _realized_pnl_in_window(trades: list, start: datetime, end: datetime) -> float:
    """Sum `pnl` over `trades` whose `closed_at` falls in `[start, end]`.

    In-memory equivalent of `TradeJournal.generate_journal_report(start,
    end)`'s realized-PnL-window query -- `trades` is the same list `run()`
    accumulates, so this recomputes from the walk-forward's own ground
    truth on every step rather than maintaining separate running
    accumulators that could drift out of sync with day/week rollovers
    (a trade's `exit_index` can land on a later day/week than the step
    that opened it). Trade counts per backtest are small enough (bounded
    by candle count) that rescanning `trades` on each step is not a
    performance concern.
    """
    return sum(
        t["pnl"]
        for t in trades
        if t.get("closed_at") is not None and start <= t["closed_at"] <= end
    )


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
        use_breakeven: bool = False,
    ) -> "BacktestResult":
        """Replays historical LTF candles (with a time-aligned, no-lookahead
        HTF slice at each step) through the Strategy Engine and Risk Engine
        to simulate trades, including fee and slippage (BACKTEST_MODE). No
        live orders are ever placed.

        `use_breakeven` (default `False`, opt-in): when `True`, each
        trade's stop is moved to its own entry price once price has moved
        `BREAKEVEN_TRIGGER_R` (default 1R) in favor -- see that constant's
        docstring. Default `False` preserves the exact prior behavior for
        every existing caller; this is a genuinely new, unproven behavior
        being A/B tested (see docs/strategy_coverage_audit.md), not a
        silent default change.

        Walk-forward, expanding window, one trade open at a time (no
        overlap): starts at index MIN_CANDLES - 1 so LTF signal generation
        always has history. At each LTF step `i`, the HTF slice passed to
        `signal_engine.generate_signal()` contains ONLY HTF candles that had
        genuinely, fully closed by `ltf_candles[i]`'s timestamp -- see
        `_advance_htf_cursor` for the no-lookahead mechanism. `htf_candles`
        may be a genuinely separate, independently-fetched series (real
        usage) or empty/short (degrades safely to "neutral" HTF bias, no
        crash).

        Daily/weekly loss-limit gap closed: `risk_manager.evaluate()` now
        also receives real `daily_pnl_percent`/`weekly_pnl_percent`,
        computed from THIS run's own `trades` list via `_realized_pnl_in_window`
        against `_day_bounds`/`_week_bounds` (the same UTC-day/ISO-week
        convention `TradeJournal` uses for paper/live -- see
        docs/risk_rules.md). Previously these were never passed at all
        (silently defaulting to 0.0 inside `RiskManager.evaluate()`), so a
        backtest could keep opening trades through a day/week that would
        have tripped paper/live's loss-limit reject -- making backtest
        results a materially easier, non-representative test of the
        strategy than what paper/live will actually run. The percent
        denominator is `account_balance` as originally passed into `run()`
        (fixed, not the compounding running balance used for position
        sizing) -- deliberately mirrors `scripts/run_paper.py`'s
        `PLACEHOLDER_ACCOUNT_BALANCE`-based `_pnl_to_percent()` (also a
        fixed base, not compounding), so backtest's loss-limit percentages
        stay comparable to paper's.
        """
        if len(ltf_candles) < MIN_CANDLES:
            return BacktestResult(total_trades=0, win_rate=0.0, total_pnl=0.0, max_drawdown=0.0)

        starting_balance = account_balance
        trades: list = []
        equity_curve = [account_balance]
        trades_today = 0
        current_day: str | None = None
        htf_cursor = -1

        i = MIN_CANDLES - 1
        while i < len(ltf_candles):
            ltf_timestamp = _get(ltf_candles[i], "timestamp")

            day = str(ltf_timestamp)[:10]
            if day != current_day:
                current_day = day
                trades_today = 0

            symbol = _get(ltf_candles[i], "symbol") or "UNKNOWN"

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

            day_start, day_end = _day_bounds(ltf_timestamp)
            week_start, week_end = _week_bounds(ltf_timestamp)
            daily_pnl_percent = (
                _realized_pnl_in_window(trades, day_start, day_end) / starting_balance
            ) * 100
            weekly_pnl_percent = (
                _realized_pnl_in_window(trades, week_start, week_end) / starting_balance
            ) * 100

            risk_decision = risk_manager.evaluate(
                signal,
                trades_today=trades_today,
                daily_pnl_percent=daily_pnl_percent,
                weekly_pnl_percent=weekly_pnl_percent,
            )
            if not getattr(risk_decision, "approved", False):
                i += 1
                continue

            # Real position sizing (replaces the old 100%-notional
            # placeholder): sized off the signal's ORIGINAL (pre-slippage)
            # entry/stop, exactly mirroring scripts/run_paper.py's pattern,
            # so backtest sizing matches what paper/live trading will
            # actually run.
            size = calculate_position_size(
                account_balance,
                settings.RISK_PER_TRADE_PERCENT,
                signal.entry_price,
                signal.stop_loss,
            )
            if size == 0.0:
                # Degenerate case: calculate_position_size returns 0.0 when
                # entry == stop_loss (its own division-by-zero guard). A
                # zero-size trade has no notional and thus no meaningful
                # fill/PnL/fee, so treat this exactly like a
                # rejected/no-signal step -- never record a fake
                # zero-notional "trade". Deliberately not trusting that
                # entry_model.py's upstream `if risk <= 0: return None`
                # guarantee makes this unreachable here: BacktestEngine
                # shouldn't trust a caller blindly for money-math and must
                # defend against it directly.
                i += 1
                continue

            trades_today += 1
            trade, exit_index, account_balance = self._simulate_trade(
                signal,
                ltf_candles,
                i,
                account_balance,
                fee_percent,
                slippage_percent,
                size,
                use_breakeven=use_breakeven,
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
        size: float,
        use_breakeven: bool = False,
    ) -> tuple[dict, int, float]:
        """Fills entry (with unfavorable slippage), scans forward for SL/TP, and
        returns (trade_record, exit_index, updated_account_balance).

        Position sizing: `size` (units) is computed by the caller via
        `calculate_position_size(account_balance, RISK_PER_TRADE_PERCENT,
        signal.entry_price, signal.stop_loss)` -- the same real Risk Engine
        sizing model `scripts/run_paper.py` uses -- rather than the old
        placeholder that risked the full account_balance as notional on
        every trade.

        `use_breakeven`: when `True`, tracks an EFFECTIVE stop_loss
        (starts at the signal's real stop, may move to `entry_fill` once
        triggered) separately from the original `stop_loss` used for
        sizing/reporting. Conservative ordering, matching this method's
        existing "assume the worse outcome first" philosophy for a candle
        that touches multiple levels: within any given candle, the
        CURRENT effective stop (as of the START of that candle) is always
        checked first; only after confirming that candle did NOT exit the
        trade does a break-even trigger (price having moved
        `BREAKEVEN_TRIGGER_R` in favor) update the effective stop for
        candles AFTER this one. A candle that would touch both the
        original stop AND the break-even trigger level in the same bar is
        therefore resolved as a normal stop-out, never an optimistic
        breakeven-then-saved outcome -- there is no way to know the real
        intra-candle sequencing from OHLC alone, so this never assumes
        the favorable order.
        """
        entry_price = getattr(signal, "entry_price")
        stop_loss = getattr(signal, "stop_loss")
        take_profit = getattr(signal, "take_profit")
        direction = str(getattr(signal, "direction", "") or "").lower()
        is_long = direction in ("long", "buy")

        slip = slippage_percent / 100
        entry_fill = entry_price * (1 + slip) if is_long else entry_price * (1 - slip)

        risk_per_unit = abs(entry_fill - stop_loss) if stop_loss is not None else 0.0
        breakeven_trigger_price = (
            (entry_fill + BREAKEVEN_TRIGGER_R * risk_per_unit)
            if is_long
            else (entry_fill - BREAKEVEN_TRIGGER_R * risk_per_unit)
        )
        effective_stop = stop_loss
        breakeven_triggered = False

        exit_price = None
        exit_index = len(ltf_candles) - 1
        for j in range(entry_index + 1, len(ltf_candles)):
            high = _get(ltf_candles[j], "high")
            low = _get(ltf_candles[j], "low")
            if is_long:
                hit_sl = low is not None and effective_stop is not None and low <= effective_stop
                hit_tp = high is not None and take_profit is not None and high >= take_profit
            else:
                hit_sl = high is not None and effective_stop is not None and high >= effective_stop
                hit_tp = low is not None and take_profit is not None and low <= take_profit

            # If both levels fall within this candle's range, assume the worse
            # (stop_loss) outcome hit first — the conservative assumption.
            if hit_sl:
                exit_price = effective_stop
                exit_index = j
                break
            if hit_tp:
                exit_price = take_profit
                exit_index = j
                break

            # Break-even trigger check happens AFTER this candle's exit
            # check (not before) -- see this method's docstring for why:
            # a candle that touches the ORIGINAL stop is always resolved
            # as a stop-out first, never optimistically "saved" by a
            # break-even move triggered within that same candle.
            if use_breakeven and not breakeven_triggered and risk_per_unit > 0:
                triggered_this_candle = (
                    (is_long and high is not None and high >= breakeven_trigger_price)
                    or (not is_long and low is not None and low <= breakeven_trigger_price)
                )
                if triggered_this_candle:
                    effective_stop = entry_fill
                    breakeven_triggered = True

        if exit_price is None:
            exit_price = _get(ltf_candles[exit_index], "close")

        # Real position-based PnL (replaces the old notional-fraction
        # approximation): raw_pnl is the actual price move times the actual
        # position size, in account-currency units -- not a percentage of
        # account_balance. This is the correct financial model once `size`
        # is a real, risk-bounded position rather than "the whole account".
        if is_long:
            raw_pnl = size * (exit_price - entry_fill)
        else:
            raw_pnl = size * (entry_fill - exit_price)

        # Fees must scale with the ACTUAL notional traded at each leg, not
        # a flat percent-of-account-equity approximation like before --
        # otherwise a small, properly-risk-sized position would still pay
        # fees as if it were the full account, silently overstating costs
        # (or, before this fix, silently understating PnL magnitude via the
        # old formula's coupling to account_balance). Entry-leg notional is
        # `size * entry_fill` (the actual, slippage-adjusted fill price);
        # exit-leg notional is `size * exit_price` (whatever price closed
        # the trade -- SL, TP, or final candle close). `fee_percent` is
        # applied once per leg, mirroring a typical per-side taker fee.
        fee_rate = fee_percent / 100
        entry_fee = fee_rate * size * entry_fill
        exit_fee = fee_rate * size * exit_price
        pnl = raw_pnl - entry_fee - exit_fee
        account_balance += pnl

        trade = {
            "entry_price": entry_fill,
            "exit_price": exit_price,
            "pnl": pnl,
            "opened_at": _get(ltf_candles[entry_index], "timestamp"),
            "closed_at": _get(ltf_candles[exit_index], "timestamp"),
            "direction": direction,
            "size": size,
            "breakeven_triggered": breakeven_triggered,
        }
        return trade, exit_index, account_balance
