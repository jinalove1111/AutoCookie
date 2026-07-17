"""Tests for app.backtesting.backtest_engine.BacktestEngine.

Uses the real (non-mocked) SignalEngine and RiskManager throughout -- these
are integration tests of the engine's own logic (walk-forward loop, HTF
cursor, trade simulation), not of the strategy/risk detectors themselves
(those have their own dedicated test files).

The no-lookahead regression test (`test_advance_htf_cursor_excludes_still_
forming_bar_no_lookahead` / `test_backtest_engine_run_unaffected_by_still_
forming_htf_bar`) is the mandatory correctness proof for this module: it
proves a still-forming (not yet closed) HTF candle can never influence a
signal generated at an earlier LTF step, both as a direct unit-level proof
of the cursor mechanism and as a full end-to-end `BacktestEngine.run()`
proof.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.backtesting.backtest_engine import (
    MIN_CANDLES,
    BacktestEngine,
    _advance_htf_cursor,
)
from app.config import settings
from app.risk.position_sizing import calculate_position_size
from app.risk.risk_manager import RiskManager
from app.strategy.signal_engine import SignalEngine

LTF_STEP = timedelta(minutes=5)
HTF_STEP = timedelta(hours=4)
BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _c(open_: float, high: float, low: float, close: float, ts: datetime) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


# Real higher-highs/higher-lows zigzag (bullish bias, same shape verified
# directly in test_strategy_bias.py), same pattern verified in
# test_strategy_signal_engine.py's `_bullish_confluence_candles`, reused
# here with real datetime timestamps instead of string placeholders. A
# zigzag's own oscillation legitimately retraces through (mitigates, see
# `app.strategy.utils.is_zone_mitigated`) every FVG it creates internally,
# so a FRESH trailing leg is appended after it (not part of the zigzag's
# regular oscillation) to leave one genuinely unmitigated bullish FVG in
# place before the final sweep candle.
_ZIGZAG_HIGHS = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
_ZIGZAG_LOWS = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]


def _ltf_candles_with_real_confluence(n_pad: int = 17) -> list[dict]:
    """`n_pad` flat lead-in candles (so the walk-forward loop has the
    MIN_CANDLES history it requires) followed by the real bullish zigzag,
    a fresh unmitigated-FVG leg, and a sweep+reversal candle. Confirmed
    empirically (see task verification) that this padding does not change
    the resulting signal versus the unpadded fixture -- the detectors that
    matter here (liquidity sweep, FVG) are local/index-relative, not
    affected by unrelated flat history earlier in the series.
    """
    candles: list[dict] = []
    ts = BASE_TS
    for _ in range(n_pad):
        candles.append(_c(10, 10.5, 9.5, 10, ts))
        ts += LTF_STEP

    for h, l in zip(_ZIGZAG_HIGHS, _ZIGZAG_LOWS):
        candles.append(_c((h + l) / 2, h, l, (h + l) / 2, ts))
        ts += LTF_STEP
    # Fresh leg (prev/impulse/next): bullish FVG [32, 35], nothing after it
    # retraces it before the sweep candle below.
    candles.append(_c(31, 32, 29, 31, ts))
    ts += LTF_STEP
    candles.append(_c(31, 40, 30, 39, ts))
    ts += LTF_STEP
    candles.append(_c(39, 42, 35, 41, ts))
    ts += LTF_STEP
    # Final wick: sweeps below the swing low at value 8 but closes back above it.
    candles.append(_c(9, 10, 6, 9.5, ts))
    return candles


def _htf_bullish_closed_candles(n: int = 13) -> list[dict]:
    """`n` real HTF candles forming a genuine higher-highs/higher-lows
    zigzag (bullish bias -- same shape verified directly in
    test_strategy_bias.py), timestamped comfortably before the LTF window.
    """
    ts = BASE_TS - HTF_STEP * (n + 5)
    candles: list[dict] = []
    for h, l in zip(_ZIGZAG_HIGHS[:n], _ZIGZAG_LOWS[:n]):
        candles.append(_c((h + l) / 2, h, l, (h + l) / 2, ts))
        ts += HTF_STEP
    return candles


# --- Basic engine mechanics -------------------------------------------------


def test_run_below_min_candles_returns_empty_result_without_calling_engines():
    """Below MIN_CANDLES, the loop must never start -- confirmed here using
    the REAL SignalEngine/RiskManager (not mocks): if this ever called them,
    it would still work correctly since generate_signal(symbol, [], [])
    returns None safely, but the point is the loop short-circuits first.
    """
    ltf_candles = _ltf_candles_with_real_confluence(n_pad=0)  # only 17 total
    assert len(ltf_candles) < MIN_CANDLES

    result = BacktestEngine().run(
        ltf_candles, _htf_bullish_closed_candles(), SignalEngine(), RiskManager()
    )

    assert result.total_trades == 0
    assert result.win_rate == 0.0
    assert result.total_pnl == 0.0
    assert result.max_drawdown == 0.0
    assert result.trades == []
    # Milestone 23 (ENGINEERING_DECISIONS.md #60): default-populated even
    # on this short-circuit path, never a missing key.
    assert result.risk_rejections == {
        "total_signals": 0,
        "approved": 0,
        "rejected": 0,
        "by_reason": {},
    }


def test_run_produces_a_real_trade_with_real_signal_and_risk_engines():
    """End-to-end smoke test with real (non-mocked) SignalEngine/RiskManager:
    a genuine bullish HTF series + a genuine LTF sweep/FVG confluence
    pattern must walk forward, generate a real signal, get risk-approved
    (rr=2.0 >= MIN_RR), and simulate a real trade.
    """
    ltf_candles = _ltf_candles_with_real_confluence(n_pad=17)  # comfortably above MIN_CANDLES
    htf_candles = _htf_bullish_closed_candles(13)

    result = BacktestEngine().run(ltf_candles, htf_candles, SignalEngine(), RiskManager())

    assert result.total_trades == 1
    trade = result.trades[0]
    assert trade["direction"] == "long"
    assert trade["entry_price"] > 0
    assert trade["opened_at"] is not None
    assert trade["closed_at"] is not None


# --- _advance_htf_cursor: direct unit-level proof of the no-lookahead mechanism ---


def test_advance_htf_cursor_stays_at_minus_one_before_any_bar_closes():
    htf_candles = _htf_bullish_closed_candles(3)
    cursor = _advance_htf_cursor(htf_candles, -1, htf_candles[0]["timestamp"])
    assert cursor == -1


def test_advance_htf_cursor_includes_bar_once_next_bar_confirms_close():
    htf_candles = _htf_bullish_closed_candles(3)
    cursor = -1

    # Bar 0 is not yet provably closed at its own timestamp.
    cursor = _advance_htf_cursor(htf_candles, cursor, htf_candles[0]["timestamp"])
    assert cursor == -1

    # Once bar 1 exists at/before T, bar 0 is provably closed.
    cursor = _advance_htf_cursor(htf_candles, cursor, htf_candles[1]["timestamp"])
    assert cursor == 0

    # Once bar 2 exists at/before T, bar 1 is provably closed too.
    cursor = _advance_htf_cursor(htf_candles, cursor, htf_candles[2]["timestamp"])
    assert cursor == 1

    # The cursor never rewinds even if called again with an earlier-or-equal T.
    cursor_again = _advance_htf_cursor(htf_candles, cursor, htf_candles[0]["timestamp"])
    assert cursor_again == 1


def test_advance_htf_cursor_excludes_still_forming_bar_no_lookahead():
    """Mandatory no-lookahead regression proof (unit level): two full HTF
    lists that are IDENTICAL except for their final (still-forming) bar's
    OHLC values -- one continues the bullish trend, the other is a wild
    crash -- must resolve to the EXACT SAME cursor/slice, proving the
    still-forming bar has zero influence on what's exposed to signal
    generation at this LTF step.

    Also proves the test is non-vacuous: a naive/buggy off-by-one cursor
    (simulating a regression where the still-forming bar leaks in) WOULD
    produce different slices between the two scenarios -- contrasting with
    the correct implementation's identical output.
    """
    closed = _htf_bullish_closed_candles(13)
    still_forming_ts = closed[-1]["timestamp"] + HTF_STEP
    forming_a = _c(30, 40, 29, 39, still_forming_ts)  # continues the bullish trend
    forming_b = _c(30, 5, 1, 2, still_forming_ts)  # wild crash -- materially different

    htf_a = closed + [forming_a]
    htf_b = closed + [forming_b]

    # Premise check: the two full HTF series really do differ materially.
    assert htf_a[-1] != htf_b[-1]
    assert len(htf_a) == len(htf_b) == len(closed) + 1

    # LTF time is well after the still-forming bar opened, but no bar exists
    # after it to ever confirm its close.
    ltf_time = still_forming_ts + timedelta(minutes=30)

    cursor_a = _advance_htf_cursor(htf_a, -1, ltf_time)
    cursor_b = _advance_htf_cursor(htf_b, -1, ltf_time)

    assert cursor_a == cursor_b == len(closed) - 1

    slice_a = htf_a[: cursor_a + 1]
    slice_b = htf_b[: cursor_b + 1]

    # The resulting slices are byte-identical, and equal to the closed-only
    # series -- the still-forming bar is excluded from both, regardless of
    # its (materially different) content.
    assert slice_a == slice_b == closed
    assert forming_a not in slice_a
    assert forming_b not in slice_b

    # Non-vacuousness check: a naive off-by-one cursor (the shape of bug
    # this test guards against) WOULD have leaked the still-forming bar and
    # produced two different slices.
    buggy_cursor_a = cursor_a + 1
    buggy_cursor_b = cursor_b + 1
    buggy_slice_a = htf_a[: buggy_cursor_a + 1]
    buggy_slice_b = htf_b[: buggy_cursor_b + 1]
    assert buggy_slice_a != buggy_slice_b


def test_backtest_engine_run_unaffected_by_still_forming_htf_bar():
    """Mandatory no-lookahead regression proof (full end-to-end): running
    `BacktestEngine.run()` twice with LTF candles held IDENTICAL and HTF
    candles differing ONLY in a final still-forming bar (which never closes
    anywhere within this LTF sample's timespan) must produce byte-identical
    `BacktestResult`s -- including at least one real, non-empty trade, so
    this isn't a vacuous empty-vs-empty comparison.
    """
    ltf_candles = _ltf_candles_with_real_confluence(n_pad=17)
    closed = _htf_bullish_closed_candles(13)

    # This still-forming bar opens strictly after the very last LTF candle
    # in this sample, so it can never be confirmed closed anywhere in this run.
    still_forming_ts = ltf_candles[-1]["timestamp"] + LTF_STEP
    forming_a = _c(30, 40, 29, 39, still_forming_ts)
    forming_b = _c(30, 5, 1, 2, still_forming_ts)

    htf_a = closed + [forming_a]
    htf_b = closed + [forming_b]
    assert htf_a[-1] != htf_b[-1]  # premise: the two HTF series really differ

    result_a = BacktestEngine().run(ltf_candles, htf_a, SignalEngine(), RiskManager())
    result_b = BacktestEngine().run(ltf_candles, htf_b, SignalEngine(), RiskManager())

    assert result_a.total_trades == result_b.total_trades
    assert result_a.total_pnl == result_b.total_pnl
    assert result_a.win_rate == result_b.win_rate
    assert result_a.max_drawdown == result_b.max_drawdown
    assert result_a.trades == result_b.trades
    # Sanity: this is a real, non-empty proof -- a genuine signal/trade fired.
    assert result_a.total_trades >= 1


# --- Position-sizing PnL correctness (real RISK_PER_TRADE_PERCENT sizing,
# replacing the old 100%-notional-of-account_balance placeholder) --------


class _FakeSignal:
    """Minimal stand-in for a real TradeSignal, used only to drive
    `_simulate_trade`/`run()` with fully controlled entry/stop/take-profit
    values -- this section is testing the ENGINE's own sizing/PnL wiring,
    not strategy detection (which has its own dedicated tests), so a
    controlled fake here (rather than the real SignalEngine) is the right
    tool, same spirit as this file's direct `_advance_htf_cursor` tests.
    """

    def __init__(self, entry_price, stop_loss, take_profit, direction, rr=None):
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.direction = direction
        self.rr = rr


def test_simulate_trade_size_matches_calculate_position_size_independently():
    """Given a known account_balance, risk_percent, and entry/stop distance,
    the size baked into the trade record must exactly equal an independent
    call to `calculate_position_size` with the same inputs -- not just
    "some positive size".
    """
    account_balance = 10000.0
    risk_percent = 1.0
    entry_price = 100.0
    stop_loss = 95.0
    take_profit = 110.0

    expected_size = calculate_position_size(
        account_balance, risk_percent, entry_price, stop_loss
    )
    assert expected_size == 20.0  # risk_amount=100, per_unit_risk=5 -> 20 units

    signal = _FakeSignal(entry_price, stop_loss, take_profit, "long")
    # No slippage, so entry_fill == entry_price exactly, keeping the
    # arithmetic below exact rather than approximate.
    candle0 = _c(100, 100, 100, 100, BASE_TS)
    # Take-profit hit on the very next candle (high >= 110), stop_loss not
    # touched (low > 95) -- deterministic exit at exit_price == take_profit.
    candle1 = _c(100, 110, 99, 105, BASE_TS + LTF_STEP)
    ltf_candles = [candle0, candle1]

    trade, exit_index, new_balance = BacktestEngine()._simulate_trade(
        signal,
        ltf_candles,
        entry_index=0,
        account_balance=account_balance,
        fee_percent=0.1,
        slippage_percent=0.0,
        size=expected_size,
    )

    assert trade["size"] == expected_size
    assert exit_index == 1
    assert trade["exit_price"] == take_profit
    assert trade["entry_price"] == entry_price  # no slippage -> fill == entry_price

    # Independently recomputed expected PnL: raw price-move PnL minus
    # per-leg fees on the ACTUAL notional (size * price at each leg) --
    # NOT a flat fraction of account_balance like the old placeholder.
    raw_pnl = expected_size * (take_profit - entry_price)
    fee_rate = 0.1 / 100
    entry_fee = fee_rate * expected_size * entry_price
    exit_fee = fee_rate * expected_size * take_profit
    expected_pnl = raw_pnl - entry_fee - exit_fee

    assert trade["pnl"] == expected_pnl
    assert new_balance == account_balance + expected_pnl


def test_simulate_trade_pnl_scales_with_size_not_flat_fraction_of_balance():
    """Two otherwise-identical scenarios (same account_balance, same price
    path/exit) differing ONLY in stop-loss distance (hence only in the
    resulting `size`) must produce PnL that scales exactly with `size` --
    proving PnL tracks the real position size, not a flat fraction of
    account_balance as the old formula did (which would have produced
    IDENTICAL pnl for both scenarios regardless of stop distance).
    """
    account_balance = 10000.0
    risk_percent = 1.0
    entry_price = 100.0
    take_profit = 110.0

    candle0 = _c(100, 100, 100, 100, BASE_TS)
    candle1 = _c(100, 110, 99, 105, BASE_TS + LTF_STEP)
    ltf_candles = [candle0, candle1]

    # Scenario A: risk 5 points -> size 20. Scenario B: risk 2.5 points (half
    # the distance) -> size 40 (double A's), same account_balance/risk_percent.
    size_a = calculate_position_size(account_balance, risk_percent, entry_price, 95.0)
    size_b = calculate_position_size(account_balance, risk_percent, entry_price, 97.5)
    assert size_a == 20.0
    assert size_b == 40.0
    assert size_b == size_a * 2

    signal_a = _FakeSignal(entry_price, 95.0, take_profit, "long")
    signal_b = _FakeSignal(entry_price, 97.5, take_profit, "long")

    trade_a, _, _ = BacktestEngine()._simulate_trade(
        signal_a, ltf_candles, 0, account_balance, fee_percent=0.1,
        slippage_percent=0.0, size=size_a,
    )
    trade_b, _, _ = BacktestEngine()._simulate_trade(
        signal_b, ltf_candles, 0, account_balance, fee_percent=0.1,
        slippage_percent=0.0, size=size_b,
    )

    # Under the OLD (pre-fix) model, both would have produced the exact same
    # pnl (a flat fraction of account_balance, oblivious to stop distance).
    # Under the fixed model, pnl must scale exactly with size (same
    # entry/exit prices in both scenarios, so the only variable is size).
    assert trade_a["pnl"] != 0.0
    assert trade_b["pnl"] == pytest.approx(trade_a["pnl"] * 2)


# --- Break-even move (use_breakeven, opt-in -- see docs/strategy_coverage_audit.md
# and BREAKEVEN_TRIGGER_R's docstring for why this is A/B tested, not default-on) ---


def test_simulate_trade_breakeven_disabled_by_default_pullback_does_not_exit():
    """Baseline/contrast: with use_breakeven left at its default (False), a
    pullback all the way to entry_price after a 1R favorable move must NOT
    exit the trade -- only the ORIGINAL stop_loss/take_profit matter.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=115.0, direction="long")
    candle0 = _c(100, 100, 100, 100, BASE_TS)
    candle1 = _c(100, 106, 99, 105, BASE_TS + LTF_STEP)  # moves 1R (to 105) in favor
    candle2 = _c(100, 101, 98, 100, BASE_TS + LTF_STEP * 2)  # pulls back to entry -- must NOT exit
    ltf_candles = [candle0, candle1, candle2]

    trade, exit_index, _ = BacktestEngine()._simulate_trade(
        signal, ltf_candles, 0, account_balance=10000.0, fee_percent=0.0,
        slippage_percent=0.0, size=1.0,
    )

    # No candle ever hit the ORIGINAL stop (95) or take_profit (115), so
    # the loop runs out of data and falls back to the last candle's close.
    assert exit_index == 2
    assert trade["exit_price"] == 100  # candle2's close, not a stop-out
    assert trade["breakeven_triggered"] is False


def test_simulate_trade_breakeven_enabled_pullback_to_entry_exits_at_breakeven():
    """With use_breakeven=True, the SAME pullback-to-entry candle from the
    contrast test above now DOES exit the trade -- at entry_fill (a scratch,
    not the original stop_loss).
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=115.0, direction="long")
    candle0 = _c(100, 100, 100, 100, BASE_TS)
    candle1 = _c(100, 106, 99, 105, BASE_TS + LTF_STEP)  # triggers breakeven (1R = 105)
    candle2 = _c(100, 101, 98, 100, BASE_TS + LTF_STEP * 2)  # low=98 <= effective_stop(100)
    ltf_candles = [candle0, candle1, candle2]

    trade, exit_index, _ = BacktestEngine()._simulate_trade(
        signal, ltf_candles, 0, account_balance=10000.0, fee_percent=0.0,
        slippage_percent=0.0, size=1.0, use_breakeven=True,
    )

    assert exit_index == 2
    assert trade["exit_price"] == 100.0  # entry_fill (breakeven), NOT original stop_loss=95
    assert trade["pnl"] == pytest.approx(0.0)  # scratch trade, zero fees in this test
    assert trade["breakeven_triggered"] is True


def test_simulate_trade_breakeven_does_not_prevent_reaching_take_profit():
    """A breakeven trigger earlier in the trade must not block a LATER
    candle from still reaching the real take_profit -- breakeven only
    matters if price pulls back far enough to touch the new (entry) stop.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=115.0, direction="long")
    candle0 = _c(100, 100, 100, 100, BASE_TS)
    candle1 = _c(100, 106, 99, 105, BASE_TS + LTF_STEP)  # triggers breakeven, no pullback after
    candle2 = _c(110, 116, 109, 115, BASE_TS + LTF_STEP * 2)  # reaches real take_profit=115
    ltf_candles = [candle0, candle1, candle2]

    trade, exit_index, _ = BacktestEngine()._simulate_trade(
        signal, ltf_candles, 0, account_balance=10000.0, fee_percent=0.0,
        slippage_percent=0.0, size=1.0, use_breakeven=True,
    )

    assert exit_index == 2
    assert trade["exit_price"] == 115.0  # real take_profit, not entry_fill
    assert trade["breakeven_triggered"] is True


def test_simulate_trade_breakeven_same_candle_conservative_ordering_favors_original_stop():
    """Conservative-ordering proof (mirrors this method's existing
    SL-before-TP-in-the-same-candle assumption): a SINGLE candle that
    touches BOTH the original stop_loss AND the breakeven trigger level
    must resolve as a normal stop-out at the ORIGINAL stop_loss -- never
    an optimistic "breakeven triggered, then saved" outcome, since the
    real intra-candle sequencing can't be known from OHLC alone.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=115.0, direction="long")
    candle0 = _c(100, 100, 100, 100, BASE_TS)
    # Single wide candle: high=106 (>= 1R breakeven trigger of 105) AND
    # low=94 (<= original stop_loss of 95), both in the SAME bar.
    candle1 = _c(100, 106, 94, 100, BASE_TS + LTF_STEP)
    ltf_candles = [candle0, candle1]

    trade, exit_index, _ = BacktestEngine()._simulate_trade(
        signal, ltf_candles, 0, account_balance=10000.0, fee_percent=0.0,
        slippage_percent=0.0, size=1.0, use_breakeven=True,
    )

    assert exit_index == 1
    assert trade["exit_price"] == 95.0  # original stop_loss, NOT entry_fill=100
    assert trade["breakeven_triggered"] is False  # never reached the trigger check


def test_simulate_trade_breakeven_mirrors_correctly_for_short_direction():
    """Short-direction mirror of the enabled-pullback-exits-at-breakeven
    test above -- proves the trigger/effective-stop logic isn't
    long-only."""
    signal = _FakeSignal(entry_price=100.0, stop_loss=105.0, take_profit=85.0, direction="short")
    candle0 = _c(100, 100, 100, 100, BASE_TS)
    candle1 = _c(100, 101, 94, 95, BASE_TS + LTF_STEP)  # low=94 <= 1R trigger (95) -> breakeven
    candle2 = _c(100, 101, 99, 100, BASE_TS + LTF_STEP * 2)  # high=101 >= effective_stop(100)
    ltf_candles = [candle0, candle1, candle2]

    trade, exit_index, _ = BacktestEngine()._simulate_trade(
        signal, ltf_candles, 0, account_balance=10000.0, fee_percent=0.0,
        slippage_percent=0.0, size=1.0, use_breakeven=True,
    )

    assert exit_index == 2
    assert trade["exit_price"] == 100.0  # entry_fill (breakeven), NOT original stop_loss=105
    assert trade["breakeven_triggered"] is True


# --- Partial take-profit (use_partial_tp, opt-in -- see
# docs/strategy_coverage_audit.md and PARTIAL_TP_TRIGGER_R/PARTIAL_TP_PORTION's
# docstrings for why this is A/B tested, not default-on) ---


def test_simulate_trade_partial_tp_disabled_by_default_no_partial_leg():
    """Baseline/contrast: with use_partial_tp left at its default (False),
    price reaching the 1R level and then reversing to the ORIGINAL stop
    must produce a normal full-size loss -- no partial leg recorded.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=115.0, direction="long")
    candle0 = _c(100, 100, 100, 100, BASE_TS)
    candle1 = _c(100, 106, 99, 105, BASE_TS + LTF_STEP)  # reaches 1R (105) -- irrelevant when disabled
    candle2 = _c(99, 99, 94, 95, BASE_TS + LTF_STEP * 2)  # reverses to original stop_loss (95)
    ltf_candles = [candle0, candle1, candle2]

    trade, exit_index, _ = BacktestEngine()._simulate_trade(
        signal, ltf_candles, 0, account_balance=10000.0, fee_percent=0.0,
        slippage_percent=0.0, size=1.0,
    )

    assert exit_index == 2
    assert trade["exit_price"] == 95.0
    assert trade["pnl"] == pytest.approx(1.0 * (95.0 - 100.0))  # full size, full loss
    assert trade["partial_tp_triggered"] is False
    assert trade["partial_tp_exit_price"] is None
    assert trade["partial_tp_pnl"] is None


def test_simulate_trade_partial_tp_enabled_locks_in_profit_then_continues_to_full_tp():
    """With use_partial_tp=True: half the position closes at the 1R level
    (105), and the remaining half continues to the real take_profit
    (115) on a later candle -- combined PnL is the sum of both legs.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=115.0, direction="long")
    candle0 = _c(100, 100, 100, 100, BASE_TS)
    candle1 = _c(100, 106, 99, 105, BASE_TS + LTF_STEP)  # triggers partial TP at 105
    candle2 = _c(110, 116, 109, 115, BASE_TS + LTF_STEP * 2)  # remaining half reaches take_profit=115
    ltf_candles = [candle0, candle1, candle2]

    trade, exit_index, _ = BacktestEngine()._simulate_trade(
        signal, ltf_candles, 0, account_balance=10000.0, fee_percent=0.0,
        slippage_percent=0.0, size=1.0, use_partial_tp=True,
    )

    assert exit_index == 2
    assert trade["exit_price"] == 115.0  # remaining leg's exit -- the real take_profit
    assert trade["partial_tp_triggered"] is True
    assert trade["partial_tp_exit_price"] == 105.0
    assert trade["partial_tp_pnl"] == pytest.approx(0.5 * (105.0 - 100.0))  # 2.5
    expected_pnl = 0.5 * (105.0 - 100.0) + 0.5 * (115.0 - 100.0)  # 2.5 + 7.5 = 10.0
    assert trade["pnl"] == pytest.approx(expected_pnl)
    # Contrast: without partial TP, the same full-size move to take_profit
    # would have realized size * (115 - 100) = 15.0 -- strictly MORE than
    # the 10.0 here. Partial TP trades some upside for earlier lock-in.
    assert trade["pnl"] < 1.0 * (115.0 - 100.0)


def test_simulate_trade_partial_tp_protects_against_a_later_full_loss():
    """The other side of the trade-off: if price reverses to the ORIGINAL
    stop_loss for the remaining half AFTER a partial has already locked in
    profit, combined PnL is much better than a full-size loss would have
    been (though not necessarily net-positive) -- this is the real
    protective value of partial-TP.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=115.0, direction="long")
    candle0 = _c(100, 100, 100, 100, BASE_TS)
    candle1 = _c(100, 106, 99, 105, BASE_TS + LTF_STEP)  # triggers partial TP at 105
    candle2 = _c(99, 99, 94, 95, BASE_TS + LTF_STEP * 2)  # remaining half reverses to stop_loss=95
    ltf_candles = [candle0, candle1, candle2]

    trade, exit_index, _ = BacktestEngine()._simulate_trade(
        signal, ltf_candles, 0, account_balance=10000.0, fee_percent=0.0,
        slippage_percent=0.0, size=1.0, use_partial_tp=True,
    )

    assert exit_index == 2
    assert trade["exit_price"] == 95.0  # remaining leg stopped out
    assert trade["partial_tp_triggered"] is True
    expected_pnl = 0.5 * (105.0 - 100.0) + 0.5 * (95.0 - 100.0)  # 2.5 - 2.5 = 0.0
    assert trade["pnl"] == pytest.approx(expected_pnl)
    # Contrast: a full-size stop-out (no partial TP) would have lost 5.0 --
    # strictly WORSE than this trade's breakeven-ish 0.0 outcome.
    assert trade["pnl"] > 1.0 * (95.0 - 100.0)


def test_simulate_trade_partial_tp_same_candle_jump_still_banks_partial_leg_first():
    """A SINGLE candle whose range reaches both the 1R partial-trigger
    price (105) AND the real take_profit (115) must still bank the
    partial leg at its own nearer price (105), not skip straight to
    closing the full size at take_profit -- see this method's docstring
    for why checking partial-TP before take_profit is the economically
    correct ordering (rather than an arbitrary implementation detail).
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=115.0, direction="long")
    candle0 = _c(100, 100, 100, 100, BASE_TS)
    candle1 = _c(100, 116, 99, 115, BASE_TS + LTF_STEP)  # single candle spans both 105 and 115
    ltf_candles = [candle0, candle1]

    trade, exit_index, _ = BacktestEngine()._simulate_trade(
        signal, ltf_candles, 0, account_balance=10000.0, fee_percent=0.0,
        slippage_percent=0.0, size=1.0, use_partial_tp=True,
    )

    assert exit_index == 1
    assert trade["partial_tp_triggered"] is True
    assert trade["partial_tp_exit_price"] == 105.0
    assert trade["exit_price"] == 115.0
    expected_pnl = 0.5 * (105.0 - 100.0) + 0.5 * (115.0 - 100.0)
    assert trade["pnl"] == pytest.approx(expected_pnl)


def test_simulate_trade_partial_tp_mirrors_correctly_for_short_direction():
    """Short-direction mirror -- proves the trigger/partial-size logic
    isn't long-only."""
    signal = _FakeSignal(entry_price=100.0, stop_loss=105.0, take_profit=85.0, direction="short")
    candle0 = _c(100, 100, 100, 100, BASE_TS)
    candle1 = _c(100, 101, 94, 95, BASE_TS + LTF_STEP)  # low=94 <= 1R trigger (95)
    candle2 = _c(90, 91, 84, 85, BASE_TS + LTF_STEP * 2)  # remaining half reaches take_profit=85
    ltf_candles = [candle0, candle1, candle2]

    trade, exit_index, _ = BacktestEngine()._simulate_trade(
        signal, ltf_candles, 0, account_balance=10000.0, fee_percent=0.0,
        slippage_percent=0.0, size=1.0, use_partial_tp=True,
    )

    assert exit_index == 2
    assert trade["partial_tp_triggered"] is True
    assert trade["partial_tp_exit_price"] == 95.0
    assert trade["exit_price"] == 85.0
    expected_pnl = 0.5 * (100.0 - 95.0) + 0.5 * (100.0 - 85.0)  # 2.5 + 7.5 = 10.0
    assert trade["pnl"] == pytest.approx(expected_pnl)


class _FakeApprovedRiskDecision:
    approved = True
    reasons: list = []


class _FakeRiskManager:
    """Always approves -- isolates this section's tests to the engine's own
    sizing wiring in `run()`, not RiskManager's own approval logic (which
    has its own dedicated tests).
    """

    def evaluate(self, signal, trades_today=0, daily_pnl_percent=0.0, weekly_pnl_percent=0.0):
        return _FakeApprovedRiskDecision()


class _FakeSignalEngineFixedSignal:
    """Returns the same fixed signal on every call -- lets `run()`'s
    walk-forward loop be driven deterministically without depending on real
    strategy detection."""

    def __init__(self, signal):
        self._signal = signal
        self.call_count = 0

    def generate_signal(
        self,
        symbol,
        ltf_candles,
        htf_candles,
        use_breaker_block=False,
        require_full_confluence=False,
        require_ob_fvg_confluence=False,
        use_structure_tp=False,
        require_premium_discount_filter=False,
        use_jade_engine=False,
        structure_tp_max_r=None,
        require_session=None,
        atr_stop_multiplier=None,
    ):
        self.call_count += 1
        return self._signal


def _flat_ltf_candles(n: int) -> list[dict]:
    ts = BASE_TS
    candles = []
    for _ in range(n):
        candles.append(_c(100, 110, 99, 105, ts))
        ts += LTF_STEP
    return candles


def test_run_wires_real_settings_risk_per_trade_percent_into_trade_size():
    """End-to-end (through `run()`, not `_simulate_trade` directly): the
    `size` recorded on the trade must equal `calculate_position_size` called
    with the REAL `settings.RISK_PER_TRADE_PERCENT` -- proving `run()` is
    actually wired to the real Risk Engine config, not a hardcoded value.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    signal_engine = _FakeSignalEngineFixedSignal(signal)
    # Exactly MIN_CANDLES + 1: one entry candle at index MIN_CANDLES - 1, one
    # exit candle right after it (immediately hits take_profit), then the
    # loop ends -- keeps this a single, unambiguous trade.
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 1)

    result = BacktestEngine().run(
        ltf_candles, [], signal_engine, _FakeRiskManager(), account_balance=10000.0
    )

    assert result.total_trades == 1
    expected_size = calculate_position_size(
        10000.0, settings.RISK_PER_TRADE_PERCENT, 100.0, 95.0
    )
    assert expected_size > 0.0
    assert result.trades[0]["size"] == expected_size


def test_run_entry_delay_candles_fills_at_the_delayed_candles_close():
    """entry_delay_candles=1 must fill at the candle ONE STEP AFTER signal
    generation, using ITS close (not the signal's originally-planned
    entry_price) as the pre-slippage fill reference -- simulating real
    dispatch/network/exchange latency (2026-07-14 robustness validation,
    ENGINEERING_DECISIONS.md #42). Position sizing must stay keyed to the
    ORIGINAL planned entry/stop (unaffected by the delay).
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    signal_engine = _FakeSignalEngineFixedSignal(signal)
    ltf_candles = _flat_ltf_candles(MIN_CANDLES - 1)
    ltf_candles.append(_c(100, 101, 99, 100, BASE_TS + (MIN_CANDLES - 1) * LTF_STEP))
    # Delayed fill candle -- close (102) is what the trade must actually
    # fill against, not the signal's planned 100.
    ltf_candles.append(_c(101, 103, 100, 102, BASE_TS + MIN_CANDLES * LTF_STEP))
    ltf_candles.append(_c(102, 111, 101, 105, BASE_TS + (MIN_CANDLES + 1) * LTF_STEP))

    result = BacktestEngine().run(
        ltf_candles,
        [],
        signal_engine,
        _FakeRiskManager(),
        account_balance=10000.0,
        slippage_percent=0.0,
        entry_delay_candles=1,
    )

    assert result.total_trades == 1
    assert result.trades[0]["entry_price"] == 102.0
    expected_size = calculate_position_size(
        10000.0, settings.RISK_PER_TRADE_PERCENT, 100.0, 95.0
    )
    assert result.trades[0]["size"] == expected_size


def test_run_entry_delay_candles_zero_is_unchanged_behavior():
    """entry_delay_candles=0 (the default) must be byte-for-byte identical
    to not passing the parameter at all -- backward compatibility for
    every existing caller."""
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 1)

    result_default = BacktestEngine().run(
        ltf_candles, [], _FakeSignalEngineFixedSignal(signal), _FakeRiskManager(), account_balance=10000.0
    )
    result_explicit_zero = BacktestEngine().run(
        ltf_candles, [], _FakeSignalEngineFixedSignal(signal), _FakeRiskManager(),
        account_balance=10000.0, entry_delay_candles=0,
    )

    assert result_default.trades == result_explicit_zero.trades


def test_run_max_entry_drift_pct_skips_trade_when_delayed_price_drifts_too_far():
    """max_entry_drift_pct (opt-in, only has effect when
    entry_delay_candles > 0 -- 2026-07-14 continuous research mode,
    docs/CONTINUOUS_RESEARCH_LOG.md experiment 4) must skip the trade
    entirely (treated like "no signal") when the delayed fill price has
    drifted more than the given fraction away from the signal's
    originally-planned entry_price -- never fill at an unconfirmed price.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    signal_engine = _FakeSignalEngineFixedSignal(signal)
    ltf_candles = _flat_ltf_candles(MIN_CANDLES - 1)
    ltf_candles.append(_c(100, 101, 99, 100, BASE_TS + (MIN_CANDLES - 1) * LTF_STEP))
    # Delayed fill candle drifts 10% away from the planned entry (100 -> 110).
    ltf_candles.append(_c(109, 111, 108, 110, BASE_TS + MIN_CANDLES * LTF_STEP))
    ltf_candles.append(_c(110, 120, 109, 115, BASE_TS + (MIN_CANDLES + 1) * LTF_STEP))

    result = BacktestEngine().run(
        ltf_candles,
        [],
        signal_engine,
        _FakeRiskManager(),
        account_balance=10000.0,
        entry_delay_candles=1,
        max_entry_drift_pct=0.02,
    )

    assert result.total_trades == 0


def test_run_max_entry_drift_pct_fills_normally_when_drift_is_within_tolerance():
    """Same shape as the test above, but the delayed candle's close is
    within the tolerance -- the trade must fill exactly as
    entry_delay_candles alone would (this parameter never changes
    behavior for a trade that clears the check)."""
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    signal_engine = _FakeSignalEngineFixedSignal(signal)
    ltf_candles = _flat_ltf_candles(MIN_CANDLES - 1)
    ltf_candles.append(_c(100, 101, 99, 100, BASE_TS + (MIN_CANDLES - 1) * LTF_STEP))
    ltf_candles.append(_c(101, 103, 100, 102, BASE_TS + MIN_CANDLES * LTF_STEP))
    ltf_candles.append(_c(102, 111, 101, 105, BASE_TS + (MIN_CANDLES + 1) * LTF_STEP))

    result = BacktestEngine().run(
        ltf_candles,
        [],
        signal_engine,
        _FakeRiskManager(),
        account_balance=10000.0,
        slippage_percent=0.0,
        entry_delay_candles=1,
        max_entry_drift_pct=0.05,
    )

    assert result.total_trades == 1
    assert result.trades[0]["entry_price"] == 102.0


def test_run_skips_degenerate_zero_size_signal_without_recording_a_fake_trade():
    """When entry == stop_loss, `calculate_position_size` returns 0.0 (its
    own division-by-zero guard). `run()` must treat this exactly like a
    rejected/no-signal step -- skip it (`i += 1; continue`) and never append
    a fake zero-notional "trade" -- even though `generate_signal` keeps
    firing on every remaining step (proving the loop genuinely reached and
    evaluated the degenerate signal each time, rather than short-circuiting
    for an unrelated reason).
    """
    degenerate_signal = _FakeSignal(
        entry_price=100.0, stop_loss=100.0, take_profit=110.0, direction="long"
    )
    signal_engine = _FakeSignalEngineFixedSignal(degenerate_signal)
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 5)

    result = BacktestEngine().run(
        ltf_candles, [], signal_engine, _FakeRiskManager(), account_balance=10000.0
    )

    assert result.total_trades == 0
    assert result.trades == []
    assert result.total_pnl == 0.0
    # Confirms the loop really did reach the sizing step repeatedly (once
    # per remaining LTF index), not that generate_signal was only called once
    # then something else short-circuited the loop.
    assert signal_engine.call_count == len(ltf_candles) - (MIN_CANDLES - 1)


# --- Daily/weekly loss-limit wiring (previously never passed to
# RiskManager.evaluate() at all -- silently defaulted to 0.0, so a backtest
# could keep opening trades through a day that would have tripped paper/
# live's real loss-limit reject) -------------------------------------------


def test_day_bounds_and_week_bounds_match_tradejournal_convention():
    """Direct unit-level proof that `_day_bounds`/`_week_bounds` compute the
    exact same UTC-calendar-day / ISO-calendar-week boundaries as
    `TradeJournal.generate_daily_report()`/`generate_weekly_report()` (see
    that module's docstrings) -- cross-checked here against independently
    hand-computed boundaries, not against the journal implementation
    itself, so this isn't a vacuous tautology.
    """
    from app.backtesting.backtest_engine import _day_bounds, _week_bounds

    # 2026-01-14 is a Wednesday; its ISO week runs Mon 2026-01-12 through
    # Sun 2026-01-18 (same fixture dates used in
    # test_risk_daily_weekly_real_integration.py for the same reason).
    ts = datetime(2026, 1, 14, 15, 30, 0, tzinfo=timezone.utc)

    day_start, day_end = _day_bounds(ts)
    assert day_start == datetime(2026, 1, 14, 0, 0, 0, tzinfo=timezone.utc)
    assert day_end == datetime(2026, 1, 14, 23, 59, 59, 999999, tzinfo=timezone.utc)

    week_start, week_end = _week_bounds(ts)
    assert week_start == datetime(2026, 1, 12, 0, 0, 0, tzinfo=timezone.utc)
    assert week_end == datetime(2026, 1, 18, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_realized_pnl_in_window_only_counts_trades_closed_inside_bounds():
    from app.backtesting.backtest_engine import _realized_pnl_in_window

    trades = [
        {"pnl": -100.0, "closed_at": datetime(2026, 1, 14, 5, 0, tzinfo=timezone.utc)},
        {"pnl": 50.0, "closed_at": datetime(2026, 1, 14, 23, 59, 59, tzinfo=timezone.utc)},
        # Outside the window on either side -- must be excluded.
        {"pnl": -999.0, "closed_at": datetime(2026, 1, 13, 23, 59, 59, tzinfo=timezone.utc)},
        {"pnl": -999.0, "closed_at": datetime(2026, 1, 15, 0, 0, 1, tzinfo=timezone.utc)},
        # Still open (no closed_at) -- must be excluded, same convention as
        # TradeJournal's realized-PnL-window query.
        {"pnl": -999.0, "closed_at": None},
    ]
    start = datetime(2026, 1, 14, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 14, 23, 59, 59, 999999, tzinfo=timezone.utc)

    assert _realized_pnl_in_window(trades, start, end) == -50.0


def _candles_with_one_crash(n_pad: int) -> list[dict]:
    """`n_pad` flat candles (safe -- never trigger the fixed signal's SL=90/
    TP=200), then one crash candle (low=80, triggers stop_loss immediately),
    then one more flat candle so the walk-forward loop gets a chance to
    evaluate a SECOND signal on the same UTC day after the first trade
    closes.
    """
    ts = BASE_TS
    candles = []
    for _ in range(n_pad):
        candles.append(_c(100, 100, 100, 100, ts))
        ts += LTF_STEP
    candles.append(_c(100, 100, 80, 85, ts))  # crash: hits stop_loss=90
    ts += LTF_STEP
    candles.append(_c(100, 100, 100, 100, ts))  # lets the loop attempt one more signal
    return candles


def test_run_daily_loss_limit_blocks_further_trades_same_day(monkeypatch):
    """A real stop-loss hit that alone breaches `MAX_DAILY_LOSS_PERCENT` must
    cause the REAL `RiskManager` to reject a second, otherwise-perfectly
    valid signal offered later the same UTC day -- proving `run()` now
    passes genuine `daily_pnl_percent` instead of the old silent 0.0
    default (which could never reject on loss alone, only on
    `trades_today`/RR/missing-SL-TP).
    """
    # Low enough that a single default-sized stop-loss hit (~0.25% risk)
    # reliably breaches it, isolating this test to the daily-loss check --
    # MAX_TRADES_PER_DAY stays at its default (2), well above the 1 trade
    # actually opened here, so it cannot be the cause of any rejection.
    #
    # Patches the SAME `settings` object imported at this file's top level
    # (not a freshly re-imported module instance) -- other test files in
    # this suite use fresh_app_env/migrated_db fixtures that purge `app.*`
    # from sys.modules for DB isolation, so an `import
    # app.backtesting.backtest_engine` done fresh inside a test body can
    # silently bind to a DIFFERENT re-imported settings singleton than the
    # one `BacktestEngine`/`RiskManager` (imported at collection time, this
    # file's top) actually use internally -- patching that copy would be a
    # silent no-op depending on suite execution order (this is exactly what
    # broke on the first version of this test: it passed in isolation but
    # failed inside the full suite).
    monkeypatch.setattr(settings, "MAX_DAILY_LOSS_PERCENT", 0.1)

    signal = _FakeSignal(entry_price=100.0, stop_loss=90.0, take_profit=200.0, direction="long", rr=10.0)
    signal_engine = _FakeSignalEngineFixedSignal(signal)
    ltf_candles = _candles_with_one_crash(n_pad=MIN_CANDLES)

    result = BacktestEngine().run(
        ltf_candles, [], signal_engine, RiskManager(), account_balance=10000.0
    )

    # First trade opens and is stopped out; the second offered signal (same
    # UTC day, real RiskManager, real daily_pnl_percent now below
    # -0.1%) must be rejected -- proving only ONE trade executes even
    # though generate_signal fired again.
    assert signal_engine.call_count == 2
    assert result.total_trades == 1
    assert result.trades[0]["pnl"] < 0
    assert (result.trades[0]["pnl"] / 10000.0) * 100 < -0.1  # premise: the loss really breaches it


def test_run_small_daily_loss_within_limit_does_not_block_further_trades(monkeypatch):
    """Contrast case (same setup as the test above, default
    `MAX_DAILY_LOSS_PERCENT`, which the small default-sized loss does NOT
    breach): the second signal must still be approved and executed --
    proving the daily-loss wiring doesn't just reject everything
    unconditionally once any loss has occurred.
    """
    assert settings.MAX_DAILY_LOSS_PERCENT == 1.0  # premise: default, unmodified

    signal = _FakeSignal(entry_price=100.0, stop_loss=90.0, take_profit=200.0, direction="long", rr=10.0)
    signal_engine = _FakeSignalEngineFixedSignal(signal)
    ltf_candles = _candles_with_one_crash(n_pad=MIN_CANDLES)

    result = BacktestEngine().run(
        ltf_candles, [], signal_engine, RiskManager(), account_balance=10000.0
    )

    assert signal_engine.call_count == 2
    # Both offered signals executed: the first is stopped out, and the
    # second -- opened on the loop's very last candle -- is left open at
    # the end of the series (no more candles to scan for an exit), so
    # _simulate_trade closes it out at that final candle's close price.
    assert result.total_trades == 2


# --- Strategy injection (Milestone 9, 2026-07-16 -- "evidence pipeline": any
# Strategy-Protocol-conforming module can be backtested through this SAME
# engine, bypassing signal_engine entirely, so future strategy modules can
# be evidenced through fees/slippage/walk-forward before ever being
# considered for production) ------------------------------------------------


class _FakeStrategy:
    """Minimal stand-in for a real Strategy-Protocol module (see
    app.strategy.strategy_interface.Strategy) -- returns the same fixed
    TradeSignal-shaped object on every call, driving `BacktestEngine.run()`'s
    walk-forward loop deterministically without depending on any real
    strategy module. Records every call's (symbol, ltf_len, htf_len) so
    tests can prove the engine actually reached this path with real
    arguments, not just that SOME signal came from somewhere.
    """

    name = "fake-strategy"
    version = "1.0"

    def __init__(self, signal):
        self._signal = signal
        self.calls: list[tuple] = []

    def generate_signal(self, symbol, ltf_candles, htf_candles):
        self.calls.append((symbol, len(ltf_candles), len(htf_candles)))
        return self._signal


class _ExplodingSignalEngine:
    """A `signal_engine` stand-in that raises if ever called -- proves the
    `strategy`-injection path truly bypasses `signal_engine` entirely
    (never even invoked), not merely that its result gets overridden."""

    def generate_signal(self, *args, **kwargs):
        raise AssertionError(
            "signal_engine.generate_signal must not be called when strategy is provided"
        )


def test_run_with_injected_strategy_produces_trades_through_normal_fill_pnl_path():
    """A fake Strategy (not SignalEngine) drives run()'s walk-forward loop:
    its TradeSignal must flow through the exact same risk/fill/fee/slippage/
    PnL machinery as the SignalEngine path -- proven via an independent
    calculate_position_size check, same pattern as
    test_run_wires_real_settings_risk_per_trade_percent_into_trade_size.
    An `_ExplodingSignalEngine` (raises if called) is passed as
    `signal_engine` to prove the SignalEngine path is truly bypassed, not
    just overridden.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    strategy = _FakeStrategy(signal)
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 1)

    result = BacktestEngine().run(
        ltf_candles,
        [],
        _ExplodingSignalEngine(),
        _FakeRiskManager(),
        account_balance=10000.0,
        strategy=strategy,
    )

    assert result.total_trades == 1
    expected_size = calculate_position_size(
        10000.0, settings.RISK_PER_TRADE_PERCENT, 100.0, 95.0
    )
    assert expected_size > 0.0
    assert result.trades[0]["size"] == expected_size
    assert result.trades[0]["direction"] == "long"

    # The engine really did call the strategy, with real (non-empty,
    # non-placeholder) arguments.
    assert len(strategy.calls) >= 1
    symbol, ltf_len, htf_len = strategy.calls[0]
    assert symbol == "UNKNOWN"  # these flat candles carry no "symbol" key
    assert ltf_len == MIN_CANDLES
    assert htf_len == 0


def test_run_strategy_none_default_matches_omitting_the_parameter():
    """strategy=None (the default) must be byte-for-byte identical to not
    passing the parameter at all -- backward compatibility for every
    existing caller, same pattern as entry_delay_candles=0's own test.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 1)

    result_default = BacktestEngine().run(
        ltf_candles, [], _FakeSignalEngineFixedSignal(signal), _FakeRiskManager(),
        account_balance=10000.0,
    )
    result_explicit_none = BacktestEngine().run(
        ltf_candles, [], _FakeSignalEngineFixedSignal(signal), _FakeRiskManager(),
        account_balance=10000.0, strategy=None,
    )

    assert result_default.trades == result_explicit_none.trades


# --- Regime tagging (tag_regimes, opt-in -- Milestone 12, 2026-07-16,
# docs/ADAPTIVE_ARCHITECTURE.md section 4.3: a backtest can produce the
# same per-regime strategy performance evidence a live shadow-mode run
# would slowly accumulate, but at scale over years of history in one
# pass). Default False preserves the exact prior trade-dict shape (no
# "market_regime" key at all, not even set to None) for every existing
# caller/consumer -- see BacktestEngine.run's tag_regimes docstring. ---


class _FakeSignalEngineFiresAfterHistory:
    """Like `_FakeSignalEngineFixedSignal`, but returns `None` until
    `ltf_candles` has at least `min_history` candles, then the fixed
    signal on every call after that -- lets a test control exactly which
    walk-forward step opens the trade, so there's comfortably enough LTF
    history by then to clear `detect_market_regime`'s own minimum-history
    floor (`app.regime.regime_detector.volatility_percentile` requires
    `>= vol_lookback(20) + percentile_window(100) + 1 = 121` candles) --
    a REAL classification is produced, not just the "None below the
    floor" fallback path.
    """

    def __init__(self, signal, min_history):
        self._signal = signal
        self.min_history = min_history
        self.call_count = 0

    def generate_signal(
        self,
        symbol,
        ltf_candles,
        htf_candles,
        use_breaker_block=False,
        require_full_confluence=False,
        require_ob_fvg_confluence=False,
        use_structure_tp=False,
        require_premium_discount_filter=False,
        use_jade_engine=False,
        structure_tp_max_r=None,
        require_session=None,
        atr_stop_multiplier=None,
    ):
        self.call_count += 1
        if len(ltf_candles) < self.min_history:
            return None
        return self._signal


class _FakeStrategyFiresAfterHistory:
    """Strategy-injection counterpart to
    `_FakeSignalEngineFiresAfterHistory` -- same "returns None until
    enough LTF history, then the fixed signal" gating, driving the
    Milestone 9 `strategy`-injection path instead of `signal_engine`.
    """

    name = "fake-strategy-fires-after-history"
    version = "1.0"

    def __init__(self, signal, min_history):
        self._signal = signal
        self.min_history = min_history
        self.calls: list[tuple] = []

    def generate_signal(self, symbol, ltf_candles, htf_candles):
        self.calls.append((symbol, len(ltf_candles), len(htf_candles)))
        if len(ltf_candles) < self.min_history:
            return None
        return self._signal


# detect_market_regime's real minimum-history floor is 121 candles (see
# _FakeSignalEngineFiresAfterHistory's docstring); 125 leaves comfortable
# margin so this is unambiguously a real classification, not a fixture
# that happens to sit right at the edge. 126 total candles = exactly
# enough for the trade to open on the history-125th candle and exit on
# the very next (and last) one -- same "exactly enough candles, exactly
# one trade" sizing convention as test_run_wires_real_settings_risk_per_
# trade_percent_into_trade_size above.
_REGIME_MIN_HISTORY = 125


def _flat_candles_with_volume(n: int) -> list[dict]:
    """Same OHLC shape as `_flat_ltf_candles`, but with a `volume` key
    included on every candle. `_c`/`_flat_ltf_candles` deliberately never
    set one (BacktestEngine's own core mechanics -- fills, SL/TP, sizing,
    fees -- never read `volume`), but `detect_market_regime`'s `vwap()`/
    `is_breakout()` do (`app.strategy.utils.cf` does a plain dict index,
    not a `.get()` with a default, so a missing `volume` key would raise
    a `KeyError` -- caught by `tag_regimes`'s try/except and silently
    degrading to `market_regime: None`, which would make these tests
    vacuous rather than proving a real classification).
    """
    ts = BASE_TS
    candles = []
    for _ in range(n):
        candles.append(_c(100, 110, 99, 105, ts))
        candles[-1]["volume"] = 100.0
        ts += LTF_STEP
    return candles


def test_run_tag_regimes_true_adds_market_regime_key_with_real_classification():
    """tag_regimes=True on the default SignalEngine path: the trade dict
    gains a "market_regime" key. The fixture is deliberately sized well
    above detect_market_regime's minimum-history floor (see
    _REGIME_MIN_HISTORY), so this must resolve to a REAL classification
    (a dict with trend/volatility among its keys), not None.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    signal_engine = _FakeSignalEngineFiresAfterHistory(signal, min_history=_REGIME_MIN_HISTORY)
    ltf_candles = _flat_candles_with_volume(_REGIME_MIN_HISTORY + 1)

    result = BacktestEngine().run(
        ltf_candles,
        [],
        signal_engine,
        _FakeRiskManager(),
        account_balance=10000.0,
        tag_regimes=True,
    )

    assert result.total_trades == 1
    trade = result.trades[0]
    assert "market_regime" in trade
    assert trade["market_regime"] is not None
    assert set(trade["market_regime"].keys()) >= {
        "trend",
        "volatility",
        "breakout",
        "mean_reversion",
        "liquidity_sweep_environment",
        "metrics",
    }
    assert trade["market_regime"]["trend"] in ("strong_trend", "weak_trend", "range")
    assert trade["market_regime"]["volatility"] in (
        "high_volatility",
        "normal_volatility",
        "low_volatility",
    )


def test_run_default_tag_regimes_false_market_regime_key_absent():
    """Default (tag_regimes left unset, i.e. False): trade dicts get NO
    "market_regime" key at all -- not even set to None -- proving the
    False path is byte-identical to pre-Milestone-12 behavior (Hard Rule:
    a consumer distinguishes "untagged run" from "tagged run, no
    classification available" purely by key absence vs. presence).
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    signal_engine = _FakeSignalEngineFixedSignal(signal)
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 1)

    result = BacktestEngine().run(
        ltf_candles, [], signal_engine, _FakeRiskManager(), account_balance=10000.0
    )

    assert result.total_trades == 1
    assert "market_regime" not in result.trades[0]


def test_run_tag_regimes_explicit_false_matches_omitting_the_parameter():
    """tag_regimes=False (explicit) must be byte-for-byte identical to
    not passing the parameter at all -- same backward-compatibility proof
    pattern as entry_delay_candles=0 and strategy=None above.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 1)

    result_default = BacktestEngine().run(
        ltf_candles, [], _FakeSignalEngineFixedSignal(signal), _FakeRiskManager(),
        account_balance=10000.0,
    )
    result_explicit_false = BacktestEngine().run(
        ltf_candles, [], _FakeSignalEngineFixedSignal(signal), _FakeRiskManager(),
        account_balance=10000.0, tag_regimes=False,
    )

    assert result_default.trades == result_explicit_false.trades


def test_run_tag_regimes_true_on_strategy_injection_path_also_tags():
    """tag_regimes=True works identically on the Milestone 9
    `strategy`-injection path -- the tagging point (right after a trade
    is actually simulated) is downstream of both signal-generation paths,
    so it must tag here too, not just on the default SignalEngine path.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    strategy = _FakeStrategyFiresAfterHistory(signal, min_history=_REGIME_MIN_HISTORY)
    ltf_candles = _flat_candles_with_volume(_REGIME_MIN_HISTORY + 1)

    result = BacktestEngine().run(
        ltf_candles,
        [],
        _ExplodingSignalEngine(),
        _FakeRiskManager(),
        account_balance=10000.0,
        strategy=strategy,
        tag_regimes=True,
    )

    assert result.total_trades == 1
    trade = result.trades[0]
    assert "market_regime" in trade
    assert trade["market_regime"] is not None
    assert trade["market_regime"]["trend"] in ("strong_trend", "weak_trend", "range")
    assert trade["market_regime"]["volatility"] in (
        "high_volatility",
        "normal_volatility",
        "low_volatility",
    )
    # The engine really did reach the strategy-injection path with real
    # (non-empty) history, not just the immediately-firing fixed signal.
    assert len(strategy.calls) >= 1


# --- min_stop_atr_mult: Milestone 20a ATR stop-distance floor (A/B-evidence) ---
#
# `_flat_ltf_candles` (open=100, high=110, low=99, close=105 on every candle)
# gives a hand-computable, CONSTANT ATR once >= 15 candles (average_true_
# range's lookback=14, needs lookback+1 candles) are in view: every candle
# after the first has True Range = max(high-low, |high-prev_close|,
# |low-prev_close|) = max(110-99=11, |110-105|=5, |99-105|=6) = 11, so the
# 14-period simple-moving-average ATR is exactly 11.0 for any window drawn
# entirely from this fixture.
#
# ATR-is-None (too-short history at signal time) is documented here as
# UNREACHABLE through `run()`, not tested: `BacktestEngine.MIN_CANDLES` is
# 31, so the walk-forward loop's first-ever signal opportunity is at index
# `MIN_CANDLES - 1 == 30`, i.e. `average_true_range(ltf_candles[:31])` sees
# 31 candles -- always comfortably >= `average_true_range`'s own minimum of
# `lookback + 1 == 15`. `average_true_range`'s own None-return path (too few
# candles) already has direct unit coverage in test_strategy_utils.py; there
# is no way to reach it from inside `run()`'s loop without also violating
# `MIN_CANDLES`'s own floor, which `run()` rejects before the loop even
# starts (see test_run_below_min_candles_returns_empty_result_without_
# calling_engines above).


def test_run_min_stop_atr_mult_zero_is_unchanged_behavior():
    """min_stop_atr_mult=0.0 (the default) must be byte-for-byte identical
    to not passing the parameter at all -- and, critically, must not pass
    ANY new keyword argument to risk_manager.evaluate() at all. Proven here
    by using `_FakeRiskManager`, whose `evaluate()` signature does not even
    accept `stop_distance_atr_mult`/`min_stop_atr_mult` -- a `TypeError`
    would fail this test immediately (not just an assertion mismatch) if
    the gate were ever wired to pass those kwargs unconditionally.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long", rr=2.0)
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 1)

    result_default = BacktestEngine().run(
        ltf_candles, [], _FakeSignalEngineFixedSignal(signal), _FakeRiskManager(),
        account_balance=10000.0,
    )
    result_explicit_zero = BacktestEngine().run(
        ltf_candles, [], _FakeSignalEngineFixedSignal(signal), _FakeRiskManager(),
        account_balance=10000.0, min_stop_atr_mult=0.0,
    )

    assert result_default.trades == result_explicit_zero.trades


def test_run_min_stop_atr_mult_rejects_trade_with_stop_tighter_than_atr_floor():
    """min_stop_atr_mult=1.0 with a stop 5 wide against a hand-computed
    ATR of 11.0 (stop_distance_atr_mult = 5/11 ~= 0.4545, below the 1.0
    floor) must be REJECTED by the real RiskManager -- the loop reaches
    the risk check every step (fixed signal fires every step) but never
    opens a trade.
    """
    signal = _FakeSignal(
        entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long", rr=2.0
    )
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 1)

    result = BacktestEngine().run(
        ltf_candles,
        [],
        _FakeSignalEngineFixedSignal(signal),
        RiskManager(),
        account_balance=10000.0,
        min_stop_atr_mult=1.0,
    )

    assert result.total_trades == 0


def test_run_min_stop_atr_mult_accepts_trade_with_stop_at_or_above_atr_floor():
    """Same fixture/ATR (11.0) and same min_stop_atr_mult=1.0 floor, but a
    stop 11 wide (stop_distance_atr_mult = 11/11 = 1.0, exactly AT the
    floor -- boundary convention per RiskManager.evaluate()'s docstring:
    exactly at the floor PASSES) must be ACCEPTED, proving the gate isn't
    simply rejecting every trade once enabled.
    """
    signal = _FakeSignal(
        entry_price=100.0, stop_loss=89.0, take_profit=122.0, direction="long", rr=2.0
    )
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 1)

    result = BacktestEngine().run(
        ltf_candles,
        [],
        _FakeSignalEngineFixedSignal(signal),
        RiskManager(),
        account_balance=10000.0,
        min_stop_atr_mult=1.0,
    )

    assert result.total_trades == 1


# --- risk_rejections observability (Milestone 23, 2026-07-17,
# ENGINEERING_DECISIONS.md #60) --------------------------------------------


class _FakeRejectingRiskDecision:
    """Minimal RiskDecision-shaped stand-in with caller-controlled reasons."""

    def __init__(self, reasons: list[str]):
        self.approved = False
        self.reasons = reasons


class _FakeRejectingRiskManager:
    """Always rejects, alternating between a single-reason and a
    two-reason decision on successive calls -- lets a test prove
    `by_reason` tallies EVERY reason on a multi-reason decision (not just
    the first), and that the total across reasons can exceed `rejected`
    when decisions carry more than one reason each (matching
    `RiskManager.evaluate()`'s real "no short-circuiting" behavior).
    """

    def __init__(self):
        self.call_count = 0

    def evaluate(self, signal, trades_today=0, daily_pnl_percent=0.0, weekly_pnl_percent=0.0):
        self.call_count += 1
        if self.call_count % 2 == 1:
            return _FakeRejectingRiskDecision(["reasonA", "reasonB"])
        return _FakeRejectingRiskDecision(["reasonA"])


def test_run_risk_rejections_counts_total_signals_and_tallies_every_reason():
    """A fixed signal fires on every step and is rejected every time (never
    opens a trade, so the loop advances one candle at a time for its full
    length) -- `total_signals`/`rejected` must equal the number of steps,
    `approved` must stay 0, and `by_reason` must tally EACH reason on
    EVERY rejected decision (reasonA on all 4 calls, reasonB only on the
    2 odd calls) using RiskDecision's own reason strings verbatim.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    signal_engine = _FakeSignalEngineFixedSignal(signal)
    # MIN_CANDLES - 1 (loop start index) .. MIN_CANDLES + 2 inclusive == 4 steps.
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 3)

    result = BacktestEngine().run(
        ltf_candles, [], signal_engine, _FakeRejectingRiskManager(), account_balance=10000.0
    )

    assert result.total_trades == 0
    assert result.risk_rejections == {
        "total_signals": 4,
        "approved": 0,
        "rejected": 4,
        "by_reason": {"reasonA": 4, "reasonB": 2},
    }


def test_run_risk_rejections_never_rejects_matches_existing_trade_behavior():
    """An always-approving risk manager (the existing `_FakeRiskManager`
    used throughout this file) must produce `rejected == 0`, an empty
    `by_reason`, and `total_signals == approved` -- and, critically, the
    resulting trade must be byte-for-byte identical to what this same
    fixture produces without this milestone's changes (see
    `test_run_wires_real_settings_risk_per_trade_percent_into_trade_size`),
    proving this is purely additive observability, not a behavior change.
    """
    signal = _FakeSignal(entry_price=100.0, stop_loss=95.0, take_profit=110.0, direction="long")
    signal_engine = _FakeSignalEngineFixedSignal(signal)
    ltf_candles = _flat_ltf_candles(MIN_CANDLES + 1)

    result = BacktestEngine().run(
        ltf_candles, [], signal_engine, _FakeRiskManager(), account_balance=10000.0
    )

    assert result.total_trades == 1
    expected_size = calculate_position_size(
        10000.0, settings.RISK_PER_TRADE_PERCENT, 100.0, 95.0
    )
    assert result.trades[0]["size"] == expected_size
    assert result.risk_rejections == {
        "total_signals": 1,
        "approved": 1,
        "rejected": 0,
        "by_reason": {},
    }
