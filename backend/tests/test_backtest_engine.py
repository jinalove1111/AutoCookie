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

from app.backtesting.backtest_engine import (
    MIN_CANDLES,
    BacktestEngine,
    _advance_htf_cursor,
)
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
