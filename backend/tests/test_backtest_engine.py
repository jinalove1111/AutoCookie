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
# directly in test_strategy_bias.py) plus a final wick that sweeps a recent
# swing low and closes back above it -- same pattern verified in
# test_strategy_signal_engine.py's `_bullish_confluence_candles`, reused
# here with real datetime timestamps instead of string placeholders.
_ZIGZAG_HIGHS = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
_ZIGZAG_LOWS = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]


def _ltf_candles_with_real_confluence(n_pad: int = 17) -> list[dict]:
    """`n_pad` flat lead-in candles (so the walk-forward loop has the
    MIN_CANDLES history it requires) followed by the real bullish zigzag +
    sweep pattern. Confirmed empirically (see task verification) that this
    padding does not change the resulting signal versus the unpadded
    14-candle fixture -- the detectors that matter here (liquidity sweep,
    FVG) are local/index-relative, not affected by unrelated flat history
    earlier in the series.
    """
    candles: list[dict] = []
    ts = BASE_TS
    for _ in range(n_pad):
        candles.append(_c(10, 10.5, 9.5, 10, ts))
        ts += LTF_STEP

    for h, l in zip(_ZIGZAG_HIGHS, _ZIGZAG_LOWS):
        candles.append(_c((h + l) / 2, h, l, (h + l) / 2, ts))
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
    ltf_candles = _ltf_candles_with_real_confluence(n_pad=0)  # only 14 total
    assert len(ltf_candles) < MIN_CANDLES

    result = BacktestEngine().run(
        ltf_candles, _htf_bullish_closed_candles(), SignalEngine(), RiskManager()
    )

    assert result.total_trades == 0
    assert result.win_rate == 0.0
    assert result.total_pnl == 0.0
    assert result.max_drawdown == 0.0
    assert result.trades == []


def test_run_produces_a_real_trade_with_real_signal_and_risk_engines():
    """End-to-end smoke test with real (non-mocked) SignalEngine/RiskManager:
    a genuine bullish HTF series + a genuine LTF sweep/FVG confluence
    pattern must walk forward, generate a real signal, get risk-approved
    (rr=2.0 >= MIN_RR), and simulate a real trade.
    """
    ltf_candles = _ltf_candles_with_real_confluence(n_pad=17)  # len == MIN_CANDLES
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

    def __init__(self, entry_price, stop_loss, take_profit, direction):
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.direction = direction


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


class _FakeApprovedRiskDecision:
    approved = True
    reasons: list = []


class _FakeRiskManager:
    """Always approves -- isolates this section's tests to the engine's own
    sizing wiring in `run()`, not RiskManager's own approval logic (which
    has its own dedicated tests).
    """

    def evaluate(self, signal, trades_today=0):
        return _FakeApprovedRiskDecision()


class _FakeSignalEngineFixedSignal:
    """Returns the same fixed signal on every call -- lets `run()`'s
    walk-forward loop be driven deterministically without depending on real
    strategy detection."""

    def __init__(self, signal):
        self._signal = signal
        self.call_count = 0

    def generate_signal(self, symbol, ltf_candles, htf_candles):
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
