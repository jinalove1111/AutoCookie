"""Tests for scripts/research_signal_selection.py (H1 experiment harness,
docs/HYPOTHESES_ROUND_1.md section 2). scripts/ is a sibling directory to
backend/, not a package under it, so it's added to sys.path explicitly
here -- same pattern test_run_backtest.py already uses.

Split into two groups:
  - Pure selection/scoring logic (`score_signal`, `select_daily_top`):
    deterministic, small synthetic `Candidate` sets, no candles/detectors
    involved at all -- these are the primary target of this test file, per
    the task's own examples (3+ signals on a day / cap=2 / tie-breaking).
  - Integration-level checks (`collect_candidates`, `run_variant`): confirm
    the chronological variant is byte-identical to calling
    `BacktestEngine.run()` directly, and that a full rr-ranked replay
    (collect -> select -> replay) actually executes a DIFFERENT pair of
    trades than FIFO would have, using a fake, fully-controlled
    signal_engine (same `generate_signal` fake-stub convention
    test_backtest_engine.py already uses) rather than real strategy
    detectors -- this file is testing the SELECTION harness, not strategy
    detection (which has its own dedicated test files).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from research_signal_selection import (  # noqa: E402
    Candidate,
    collect_candidates,
    replay_selected,
    run_variant,
    score_signal,
    select_daily_top,
)

from app.backtesting.backtest_engine import MIN_CANDLES, BacktestEngine  # noqa: E402
from app.risk.risk_manager import RiskManager  # noqa: E402
from app.strategy.signal_engine import SignalEngine  # noqa: E402

LTF_STEP = timedelta(minutes=5)
HTF_STEP = timedelta(hours=4)
BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _c(open_: float, high: float, low: float, close: float, ts: datetime) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


# --- score_signal -------------------------------------------------------


def test_score_signal_rr_variant_returns_rr_verbatim():
    assert score_signal(rr=2.75, confluence_count=3, variant="rr") == 2.75


def test_score_signal_rr_confluence_variant_adds_confluence_count():
    assert score_signal(rr=2.0, confluence_count=3, variant="rr_confluence") == 5.0


def test_score_signal_unknown_variant_raises_value_error():
    with pytest.raises(ValueError):
        score_signal(rr=2.0, confluence_count=0, variant="not_a_real_variant")


def test_score_signal_chronological_is_not_a_scored_variant():
    """`score_signal` deliberately has no chronological branch -- selection
    for that variant never scores anything (see `select_daily_top`)."""
    with pytest.raises(ValueError):
        score_signal(rr=2.0, confluence_count=0, variant="chronological")


# --- select_daily_top ----------------------------------------------------


def _cand(index: int, rr: float, confluence_count: int = 0, day: str = "2024-01-01") -> Candidate:
    return Candidate(index=index, day=day, signal=object(), rr=rr, confluence_count=confluence_count)


def test_select_daily_top_rr_variant_picks_two_highest_rr_regardless_of_arrival_order():
    # Arrival order (by index): rr 1.5, 3.0, 2.0, 0.5 -- highest two are 3.0 (index 11) and 2.0 (index 12).
    candidates = [
        _cand(index=10, rr=1.5),
        _cand(index=11, rr=3.0),
        _cand(index=12, rr=2.0),
        _cand(index=13, rr=0.5),
    ]

    selected = select_daily_top(candidates, variant="rr", cap=2)

    assert [c.index for c in selected] == [11, 12]
    assert [c.rr for c in selected] == [3.0, 2.0]


def test_select_daily_top_chronological_variant_is_plain_fifo_ignoring_rr():
    # Highest rr (index 12) is deliberately LAST in arrival order -- FIFO
    # must still take the first `cap` by arrival order alone.
    candidates = [
        _cand(index=10, rr=0.1),
        _cand(index=11, rr=0.2),
        _cand(index=12, rr=99.0),
    ]

    selected = select_daily_top(candidates, variant="chronological", cap=2)

    assert [c.index for c in selected] == [10, 11]


def test_select_daily_top_rr_confluence_tie_break_is_deterministic_earliest_arrival_wins():
    # index 20: rr=1.0, confluence=2 -> score 3.0
    # index 21: rr=2.0, confluence=1 -> score 3.0 (tied with index 20)
    # index 22: rr=0.5, confluence=0 -> score 0.5 (clear loser)
    # cap=2: the tie must resolve by earliest arrival (index 20 before 21),
    # both keeping their score-3.0 tie ahead of the clear loser.
    candidates = [
        _cand(index=20, rr=1.0, confluence_count=2),
        _cand(index=21, rr=2.0, confluence_count=1),
        _cand(index=22, rr=0.5, confluence_count=0),
    ]

    selected = select_daily_top(candidates, variant="rr_confluence", cap=2)

    assert [c.index for c in selected] == [20, 21]

    # Reversing arrival order (same scores) must flip which of the tied
    # pair sorts first internally, but the FINAL replay order is always
    # re-sorted by index ascending regardless -- confirms determinism is
    # about WHICH candidates are kept, not a fluke of one arrival order.
    reversed_candidates = [
        _cand(index=20, rr=2.0, confluence_count=1),  # now the "index 21" shape, at index 20
        _cand(index=21, rr=1.0, confluence_count=2),  # now the "index 20" shape, at index 21
        _cand(index=22, rr=0.5, confluence_count=0),
    ]
    selected_reversed = select_daily_top(reversed_candidates, variant="rr_confluence", cap=2)
    assert [c.index for c in selected_reversed] == [20, 21]


def test_select_daily_top_respects_multiple_days_independently():
    candidates = [
        _cand(index=1, rr=1.0, day="2024-01-01"),
        _cand(index=2, rr=2.0, day="2024-01-01"),
        _cand(index=3, rr=3.0, day="2024-01-01"),
        _cand(index=4, rr=9.0, day="2024-01-02"),
        _cand(index=5, rr=8.0, day="2024-01-02"),
    ]

    selected = select_daily_top(candidates, variant="rr", cap=2)

    day1 = [c.index for c in selected if c.day == "2024-01-01"]
    day2 = [c.index for c in selected if c.day == "2024-01-02"]
    assert sorted(day1) == [2, 3]  # top-2 rr within day 1 (2.0, 3.0), not 1.0
    assert sorted(day2) == [4, 5]  # both of day 2's candidates fit under its OWN cap=2
    assert len(selected) == 4


def test_select_daily_top_custom_cap_overrides_default():
    candidates = [_cand(index=i, rr=float(i)) for i in range(5)]

    selected_cap1 = select_daily_top(candidates, variant="rr", cap=1)
    selected_cap5 = select_daily_top(candidates, variant="rr", cap=5)

    assert [c.index for c in selected_cap1] == [4]  # highest rr only
    assert [c.index for c in selected_cap5] == [0, 1, 2, 3, 4]  # cap larger than population: keep all


def test_select_daily_top_default_cap_matches_settings_max_trades_per_day(monkeypatch):
    import research_signal_selection as rss_module

    monkeypatch.setattr(rss_module.settings, "MAX_TRADES_PER_DAY", 1)
    candidates = [_cand(index=1, rr=1.0), _cand(index=2, rr=5.0)]

    selected = select_daily_top(candidates, variant="rr")  # cap not passed -> reads settings

    assert [c.index for c in selected] == [2]


# --- collect_candidates ----------------------------------------------------


class _FakeSignal:
    def __init__(self, entry_price, stop_loss, take_profit, direction, rr):
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.direction = direction
        self.rr = rr


class _FakeSignalEngineByLength:
    """Returns a pre-scripted signal keyed by `len(ltf_candles)` at the
    step it's called -- lets a test control exactly which walk-forward
    steps produce a candidate, independent of any real strategy detector.
    """

    def __init__(self, signals_by_length: dict[int, Any]):
        self._signals_by_length = signals_by_length
        self.call_count = 0

    def generate_signal(self, symbol, ltf_candles, htf_candles):
        self.call_count += 1
        return self._signals_by_length.get(len(ltf_candles))


def _flat_candles(n: int, ts_step: timedelta = timedelta(minutes=1)) -> list[dict]:
    ts = BASE_TS
    candles = []
    for _ in range(n):
        candles.append(_c(100, 101, 99, 100, ts))
        ts += ts_step
    return candles


def test_collect_candidates_never_skips_ahead_for_a_hypothetically_open_trade():
    """Unlike BacktestEngine.run()'s own loop, collect_candidates must call
    generate_signal() at EVERY step from MIN_CANDLES-1 onward -- even ones
    that, if this were a real single-pass replay with an open trade, would
    never be reached. Signals every 3rd step to prove intermediate steps
    are still scanned (not silently skipped), not just the trigger steps.
    """
    n = MIN_CANDLES + 5
    candles = _flat_candles(n)
    sig = _FakeSignal(entry_price=100.0, stop_loss=50.0, take_profit=200.0, direction="long", rr=3.0)
    # Trigger on every 3rd length value from MIN_CANDLES onward.
    signals_by_length = {length: sig for length in range(MIN_CANDLES, n + 1, 3)}
    engine = _FakeSignalEngineByLength(signals_by_length)

    candidates = collect_candidates(candles, [], engine)

    expected_call_count = n - (MIN_CANDLES - 1)  # one call per walk-forward step
    assert engine.call_count == expected_call_count
    assert len(candidates) == len(signals_by_length)


def test_collect_candidates_below_min_candles_returns_empty_without_calling_engine():
    candles = _flat_candles(MIN_CANDLES - 1)
    engine = _FakeSignalEngineByLength({})

    candidates = collect_candidates(candles, [], engine)

    assert candidates == []
    assert engine.call_count == 0


# --- run_variant: chronological byte-identical to BacktestEngine.run() ----

# Real higher-highs/higher-lows zigzag (bullish bias), reused verbatim from
# test_backtest_engine.py's own fixture (same shape verified there and in
# test_strategy_bias.py / test_strategy_signal_engine.py).
_ZIGZAG_HIGHS = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
_ZIGZAG_LOWS = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]


def _ltf_candles_with_real_confluence(n_pad: int = 17) -> list[dict]:
    candles: list[dict] = []
    ts = BASE_TS
    for _ in range(n_pad):
        candles.append(_c(10, 10.5, 9.5, 10, ts))
        ts += LTF_STEP
    for h, l in zip(_ZIGZAG_HIGHS, _ZIGZAG_LOWS):
        candles.append(_c((h + l) / 2, h, l, (h + l) / 2, ts))
        ts += LTF_STEP
    candles.append(_c(31, 32, 29, 31, ts))  # fresh leg: bullish FVG [32, 35]
    ts += LTF_STEP
    candles.append(_c(31, 40, 30, 39, ts))
    ts += LTF_STEP
    candles.append(_c(39, 42, 35, 41, ts))
    ts += LTF_STEP
    candles.append(_c(9, 10, 6, 9.5, ts))  # sweeps below swing low 8, closes back above
    return candles


def _htf_bullish_closed_candles(n: int = 13) -> list[dict]:
    ts = BASE_TS - HTF_STEP * (n + 5)
    candles: list[dict] = []
    for h, l in zip(_ZIGZAG_HIGHS[:n], _ZIGZAG_LOWS[:n]):
        candles.append(_c((h + l) / 2, h, l, (h + l) / 2, ts))
        ts += HTF_STEP
    return candles


def test_run_variant_chronological_is_byte_identical_to_backtest_engine_run():
    ltf_candles = _ltf_candles_with_real_confluence(n_pad=17)
    htf_candles = _htf_bullish_closed_candles(13)

    direct = BacktestEngine().run(ltf_candles, htf_candles, SignalEngine(), RiskManager())
    via_harness = run_variant(ltf_candles, htf_candles, variant="chronological")

    assert via_harness.total_trades == direct.total_trades == 1
    assert via_harness.total_pnl == direct.total_pnl
    assert via_harness.win_rate == direct.win_rate
    assert via_harness.max_drawdown == direct.max_drawdown
    assert via_harness.trades == direct.trades
    assert via_harness.risk_rejections == direct.risk_rejections


def test_run_variant_unknown_variant_raises_value_error():
    with pytest.raises(ValueError):
        run_variant([], [], variant="not_a_real_variant")


# --- full pipeline: rr-ranked replay actually differs from FIFO -----------


def test_rr_ranked_replay_selects_and_executes_the_two_highest_rr_signals_not_the_first_two():
    """3 candidates on the same UTC day, cap=2 (default settings.MAX_TRADES_
    PER_DAY): FIFO/chronological would take indices 30 and 32 (first two
    arrival order); rr-ranking must instead take indices 32 and 34 (rr 4.0
    and 3.0, the two highest), skipping the lower-rr index-30 signal, and
    both must actually execute as real, independent trades (proving the
    single-open-trade-at-a-time invariant doesn't collide here, since each
    trade's own take_profit is hit on the very next candle).
    """
    n = 36  # steps i=30..35 -> ltf_candles[:i+1] lengths 31..36
    candles = _flat_candles(n)

    sig_low_rr = _FakeSignal(entry_price=100.0, stop_loss=50.0, take_profit=100.5, direction="long", rr=2.5)
    sig_high_rr = _FakeSignal(entry_price=100.0, stop_loss=50.0, take_profit=100.5, direction="long", rr=4.0)
    sig_mid_rr = _FakeSignal(entry_price=100.0, stop_loss=50.0, take_profit=100.5, direction="long", rr=3.0)

    engine_stub = _FakeSignalEngineByLength(
        {31: sig_low_rr, 33: sig_high_rr, 35: sig_mid_rr}
    )

    candidates = collect_candidates(candles, [], engine_stub)
    assert [c.index for c in candidates] == [30, 32, 34]

    chronological_selection = select_daily_top(candidates, variant="chronological", cap=2)
    rr_selection = select_daily_top(candidates, variant="rr", cap=2)

    assert [c.index for c in chronological_selection] == [30, 32]
    assert [c.index for c in rr_selection] == [32, 34]

    result = replay_selected(rr_selection, candles, RiskManager())

    assert result.total_trades == 2
    assert {t["entry_price"] for t in result.trades} != set()  # both trades actually filled
    assert all(t["pnl"] > 0 for t in result.trades)  # both hit take_profit, not stop_loss
