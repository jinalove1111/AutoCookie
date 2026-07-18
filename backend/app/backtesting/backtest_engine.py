"""Backtest engine: replays historical candles through Strategy/Risk Engine.

BACKTEST_MODE only. Never places live orders, never imports execution/.
"""

import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any

from app.backtesting.performance import calculate_max_drawdown, calculate_win_rate
from app.config import settings
from app.regime.regime_detector import detect_market_regime
from app.risk.position_sizing import calculate_position_size
from app.strategy.utils import average_true_range

if TYPE_CHECKING:
    # Import guarded behind TYPE_CHECKING (not a runtime import) so this
    # module never actually depends on app.strategy.strategy_interface at
    # import time -- BacktestEngine has always been driven by whatever
    # `signal_engine` object a caller passes in (structural, not a real
    # dependency on that module), and the new `strategy` parameter below
    # follows the exact same pattern: any object with a matching
    # `generate_signal` method works, this is purely a type-hint aid.
    from app.strategy.strategy_interface import Strategy

MIN_CANDLES = 31  # need index 30 available (30 candles of prior LTF history)

# Break-even move trigger, in multiples of the trade's own initial risk
# (R = |entry_fill - stop_loss|). 1.0 (move stop to entry once price has
# moved 1R in favor) is the standard, simplest convention -- not
# backtested/tuned to a different multiple, same "reasonable starting
# default, disclosed as such" spirit as entry_model.py's _RR/_STOP_BUFFER.
# Read from `settings.BREAKEVEN_TRIGGER_R` (app/config.py) rather than
# hardcoded here so paper trading (scripts/run_paper.py, gated by the
# separate `settings.ENABLE_BREAKEVEN`) and this module's own
# `use_breakeven` A/B-test path always agree on the same trigger
# distance -- see that setting's docstring for the full rationale
# (A/B validated positive on two independent backtest samples before
# being wired into paper trading, per docs/strategy_coverage_audit.md).
BREAKEVEN_TRIGGER_R = settings.BREAKEVEN_TRIGGER_R

# Partial take-profit trigger/portion. `PARTIAL_TP_TRIGGER_R = 1.0` (close
# part of the position once price has moved 1R in favor -- same trigger
# distance as BREAKEVEN_TRIGGER_R, though the two are independent,
# separately-toggled features, not coupled) and `PARTIAL_TP_PORTION = 0.5`
# (close half the position) are both the simplest, most common retail-SMC
# convention -- not backtested/tuned, same disclosed-default spirit as
# every other constant in this module. Only takes effect when
# `BacktestEngine.run(..., use_partial_tp=True)` -- see that parameter's
# docstring for why this is opt-in: `OrderManager.handle_partial_tp()`
# (Execution layer) has existed since Milestone 3 but was never wired
# into any live/paper/backtest trade path (see
# docs/strategy_coverage_audit.md) -- this is the first real,
# empirically-tested integration of it, and it is NOT yet proven to
# improve results (locking in a partial profit early reduces give-back
# risk on a reversal, but also caps upside on a trade that would have run
# all the way to the full take_profit anyway).
PARTIAL_TP_TRIGGER_R = 1.0
PARTIAL_TP_PORTION = 0.5

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


def _empty_risk_rejections() -> dict:
    """Default-populated shape for `BacktestResult.risk_rejections` (Milestone
    23, 2026-07-17, ENGINEERING_DECISIONS.md #60): used both as the
    dataclass field's `default_factory` (so ANY `BacktestResult` --
    including the below-`MIN_CANDLES` early return, which never runs the
    walk-forward loop at all -- always has this key with a consistent,
    zero-populated shape, never a missing key or `None`) and as `run()`'s
    own starting accumulator.
    """
    return {"total_signals": 0, "approved": 0, "rejected": 0, "by_reason": {}}


@dataclass
class BacktestResult:
    """Holds the outcome of a single backtest run."""

    total_trades: int
    win_rate: float
    total_pnl: float
    max_drawdown: float
    trades: list = field(default_factory=list)
    # Milestone 23 (2026-07-17, ENGINEERING_DECISIONS.md #60): purely
    # additive risk-gate observability -- closes the gap where a runner
    # "could not report how many signals the risk gate rejected or why"
    # (docs/ATR_FLOOR_EVALUATION.md). Never influences which trades happen;
    # it only counts what `risk_manager.evaluate()` already decided. Shape:
    # `{"total_signals": int, "approved": int, "rejected": int, "by_reason":
    # dict[str, int]}` -- `total_signals` is every non-`None` signal that
    # reached a risk-evaluation call this run (== `approved + rejected`,
    # since every such signal is evaluated exactly once); `by_reason` tallies
    # `RiskDecision.reasons` strings verbatim (a rejected decision can carry
    # more than one reason -- see `RiskManager.evaluate()`'s "no
    # short-circuiting" docstring -- so `sum(by_reason.values()) >=
    # rejected`, not necessarily `==`). Default-populated (see
    # `_empty_risk_rejections`), never a missing key, so a consumer can
    # always read it without a `getattr`/`None` guard.
    risk_rejections: dict = field(default_factory=_empty_risk_rejections)


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
        use_breaker_block: bool = False,
        use_partial_tp: bool = False,
        require_full_confluence: bool = False,
        require_ob_fvg_confluence: bool = False,
        use_structure_tp: bool = False,
        require_premium_discount_filter: bool = False,
        use_jade_engine: bool = False,
        structure_tp_max_r: float | None = None,
        entry_delay_candles: int = 0,
        require_session: str | None = None,
        max_entry_drift_pct: float | None = None,
        atr_stop_multiplier: float | None = None,
        strategy: "Strategy | None" = None,
        tag_regimes: bool = False,
        min_stop_atr_mult: float = 0.0,
        vol_scaled_sizing: bool = False,
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

        `use_breaker_block` (default `False`, opt-in): threaded straight
        through to `signal_engine.generate_signal(..., use_breaker_block=...)`
        -- see that parameter's own docstring
        (`app.strategy.signal_engine.SignalEngine.generate_signal`) for
        what it does. Default `False` here for the identical reason as
        `use_breakeven`: A/B testing a genuinely new behavior, not a
        silent default change.

        `use_partial_tp` (default `False`, opt-in): when `True`, once a
        trade has moved `PARTIAL_TP_TRIGGER_R` (default 1R) in favor,
        `PARTIAL_TP_PORTION` (default 50%) of the position closes at that
        price -- see those constants' docstrings. The remaining size
        continues toward the ORIGINAL stop_loss/take_profit, completely
        independently of `use_breakeven` (the two features are not
        coupled; combining them is possible but not what this round's
        A/B test evaluates -- see docs/strategy_coverage_audit.md and
        ENGINEERING_DECISIONS.md for why every new strategy behavior is
        tested one variable at a time).

        `require_full_confluence` (default `False`, opt-in): threaded
        straight through to `signal_engine.generate_signal(...,
        require_full_confluence=...)` -- resolves a real spec/code
        ambiguity in docs/strategy_spec.md section 6 by requiring BOTH a
        matching sweep AND a matching CHOCH (not just one) before a
        signal is produced. See
        `app.strategy.entry_model.build_entry_model`'s docstring for the
        full rationale. Default `False` preserves the exact prior
        (looser) behavior for every existing caller; this is A/B tested
        the same way as the other three flags above.

        `require_ob_fvg_confluence` (default `False`, opt-in): threaded
        straight through to `signal_engine.generate_signal(...,
        require_ob_fvg_confluence=...)` -- see
        `app.strategy.entry_model.build_entry_model`'s docstring and
        docs/ROADMAP.md "Core Rule MVP completion" item #3. Default
        `False` preserves the exact prior (looser, "either zone")
        behavior for every existing caller; A/B tested the same way as
        the other flags above.

        `use_structure_tp` (default `False`, opt-in): threaded straight
        through to `signal_engine.generate_signal(..., use_structure_tp=...)`
        -- see `app.strategy.entry_model.build_entry_model`'s docstring and
        docs/ROADMAP.md "Core Rule MVP completion" item #4. Default
        `False` preserves the exact prior fixed-RR take-profit behavior
        for every existing caller; A/B tested the same way as the other
        flags above.

        `require_premium_discount_filter` (default `False`, opt-in):
        threaded straight through to `signal_engine.generate_signal(...,
        require_premium_discount_filter=...)` -- see
        `app.strategy.entry_model.build_entry_model`'s docstring. Default
        `False` preserves the exact prior behavior for every existing
        caller; A/B tested the same way as the other flags above.

        `use_jade_engine` (default `False`, opt-in -- see
        `app.strategy.signal_engine.SignalEngine.generate_signal`'s own
        docstring and ENGINEERING_DECISIONS.md #34): threaded straight
        through to `signal_engine.generate_signal(..., use_jade_engine=...)`.
        When `True`, `signal_engine` bypasses its entire legacy pipeline
        and uses the complete Jade methodology
        (`app.strategy.jade_trade_plan.build_trade_plan`) instead --
        every OTHER flag above (`use_breaker_block`,
        `require_full_confluence`, etc.) is ignored when this is `True`,
        since those only configure the legacy path this bypasses.
        Default `False` preserves the exact prior behavior for every
        existing caller; this is the first real A/B test of the Jade
        engine against this project's existing, extensively-validated
        strategy (ENGINEERING_DECISIONS.md #35 -- see that entry for
        results once run).

        `entry_delay_candles` (default `0`, opt-in -- 2026-07-14
        robustness validation, ENGINEERING_DECISIONS.md #42): when `> 0`,
        simulates real-world dispatch/network/exchange latency between
        signal generation (candle `i`) and actual order fill (candle
        `i + entry_delay_candles`). The signal's STRUCTURAL stop_loss/
        take_profit (and position sizing, which happens before this) are
        UNCHANGED -- only the fill-price reference shifts to the delayed
        candle's own close, then the normal slippage model applies on top
        of that. This can make a trade fill already past its own stop or
        target if price moved sharply during the delay window -- that is
        the realistic risk this test exists to surface, not a bug to hide.

        `max_entry_drift_pct` (default `None`, opt-in, only has effect
        when `entry_delay_candles > 0` -- 2026-07-14 continuous research
        mode, docs/CONTINUOUS_RESEARCH_LOG.md experiment 4): an "entry
        confirmation" gate. If the delayed fill price has drifted more
        than this fraction away from the signal's ORIGINALLY PLANNED
        `entry_price`, the trade is skipped entirely (treated exactly
        like "no signal this step") instead of filling at a price the
        strategy's own structure never confirmed. This does not change
        `entry_delay_candles`'s existing behavior when unset -- a trade
        that clears the drift check still fills exactly as before.

        `strategy` (default `None`, opt-in -- Milestone 9, 2026-07-16, the
        adaptive platform's "evidence pipeline": ANY module conforming to
        `app.strategy.strategy_interface.Strategy` -- production
        (`AVAILABLE_STRATEGIES`) or experimental
        (`app.strategy.experimental.EXPERIMENTAL_STRATEGIES`) -- must be
        able to be backtested through this SAME engine, fees/slippage/
        walk-forward included, before it is ever considered for
        production). When `None` (the default), behavior is EXACTLY as
        before this parameter existed: every step calls
        `signal_engine.generate_signal(...)` with the full set of
        SignalEngine-configuration flags above. When given a `Strategy`
        instance, every step instead calls
        `strategy.generate_signal(symbol=..., ltf_candles=..., htf_candles=...)`
        -- `signal_engine` and every SignalEngine-configuration flag
        (`use_breaker_block`, `require_full_confluence`,
        `require_ob_fvg_confluence`, `use_structure_tp`,
        `require_premium_discount_filter`, `use_jade_engine`,
        `structure_tp_max_r`, `require_session`, `atr_stop_multiplier`) are
        then ignored -- those only configure the SignalEngine path this
        bypasses, the same "every OTHER flag is ignored" precedent
        `use_jade_engine` already established above. Everything
        DOWNSTREAM of signal generation (risk gating via `risk_manager`,
        position sizing, fill simulation, fees, slippage, break-even,
        partial take-profit, PnL, reporting) is completely unchanged and
        applies identically regardless of which path produced the signal
        -- this is the whole point: a strategy module gets evaluated
        through the exact same execution simulation as the production
        SignalEngine path, not a separate/looser one.

        `tag_regimes` (default `False`, opt-in -- Milestone 12,
        2026-07-16, the adaptive platform's evidence pipeline:
        docs/ADAPTIVE_ARCHITECTURE.md section 4.3 needs per-regime
        strategy performance evidence AT SCALE, without waiting for live
        shadow-mode trading to slowly accumulate it one trade at a time --
        a backtest can produce the same regime-tagged evidence over years
        of history in one run). When `True`, every trade this run
        actually simulates (i.e. AFTER risk acceptance -- only real
        trades get tagged, matching `scripts/run_paper.py`'s own
        `market_regime` tagging point, never a rejected/no-signal step)
        gets a `"market_regime"` key added to its dict in
        `BacktestResult.trades`: `app.regime.regime_detector.
        detect_market_regime(ltf_candles[: i + 1])` -- the SAME walk-
        forward index `i` used for signal generation at this step (the
        regime that produced the decision, not the regime as of the
        delayed fill when `entry_delay_candles > 0`) -- serialized via
        `dataclasses.asdict()` (identical convention to `run_paper.py`'s
        `asdict(regime) if regime is not None else None`), or `None` if
        `detect_market_regime` returns `None` (below its own minimum-
        history floor) or raises (wrapped in try/except, WARN-and-
        continue spirit matching `run_paper.py`'s own best-effort regime
        calls -- a regime-tagging failure must never break or skip an
        otherwise-valid trade). Works identically regardless of which
        path produced the signal (default `SignalEngine` path or the
        Milestone 9 `strategy`-injection path above) -- the tagging point
        is downstream of both. Default `False` preserves the exact prior
        behavior for every existing caller: trade dicts get NO new key at
        all (not even `"market_regime": None`) when this is left off, so
        a consumer can distinguish "untagged run" from "tagged run, no
        classification available" purely by key absence vs. presence.

        `min_stop_atr_mult` (default `0.0`, opt-in -- Milestone 20a,
        2026-07-16, the A/B-evidence round that decides whether the
        Milestone 18b ATR stop-distance floor may ever be enabled: the
        gate itself (`stop_distance_atr_mult`/`min_stop_atr_mult`) has
        existed in `app.risk.risk_manager.RiskManager.evaluate()` since
        18b, but nothing in the backtest path could exercise it until
        now -- it was implemented but never evidenced. `min_stop_atr_mult
        <= 0.0` (the default): the gate stays disabled and
        `risk_manager.evaluate()` is called with EXACTLY the same
        arguments as before this parameter existed -- byte-identical for
        every existing caller, including test fakes/mocks whose
        `evaluate()` signature doesn't even accept the new keywords.
        `min_stop_atr_mult > 0.0`: at each signal that reaches the risk
        check, ATR is measured EXACTLY ONCE via
        `average_true_range(ltf_candles[: i + 1])`
        (`app.strategy.utils.average_true_range`, lookback 14) -- the
        SAME no-lookahead slice (`ltf_candles[: i + 1]`) the signal
        itself was generated from at this step; no new candle fetch, no
        history beyond what is already in scope. `stop_distance_atr_mult`
        is then `abs(signal.entry_price - signal.stop_loss) / atr` when
        `atr` is a positive number and both prices are present, else
        `None` -- the `None` case (too little history for
        `average_true_range`'s own `lookback + 1` minimum, or a signal
        missing a price) mirrors `RiskManager.evaluate()`'s documented
        WARN-and-allow semantics for a missing measurement (see that
        method's own docstring): it is never itself evidence of a tight
        stop, never a rejection on its own. Both values are passed
        straight through to `risk_manager.evaluate(...,
        stop_distance_atr_mult=..., min_stop_atr_mult=...)`, which
        performs the actual accept/reject decision -- this parameter only
        supplies the caller-computed measurement that gate's docstring
        requires; `BacktestEngine` itself has no opinion on what floor is
        reasonable. Designed to be composed with `scripts/run_backtest.py`'s
        `--delay-check` (the whole point of this milestone: does a wider,
        ATR-scaled stop floor fix the execution-delay fragility
        `docs/ROBUSTNESS_REPORT.md` test 2 found?).

        `vol_scaled_sizing` (default `False`, opt-in -- Milestone 25,
        2026-07-17, H4 experiment, docs/HYPOTHESES_ROUND_1.md section 5:
        closes a verified, present-tense divergence between this engine
        and `scripts/run_paper.py`'s live sizing call. Live paper trading
        has passed `detect_market_regime(candles).volatility` into
        `calculate_position_size(..., volatility=...)` since Milestone 7
        (ENGINEERING_DECISIONS.md #49); this engine's own sizing call
        (below) never did, so every backtest number in this platform's
        evidence base to date was computed at a uniform 1.0x risk scalar
        while live has been running a 0.5x scalar in high-volatility
        regimes. When `True`, this mirrors `run_paper.py`'s exact
        best-effort/fail-open pattern: `detect_market_regime(ltf_candles[:
        i + 1])` -- the SAME no-lookahead slice (and, when `tag_regimes`
        is also `True`, the SAME walk-forward index) `tag_regimes` above
        already classifies at, computed at most once per step and reused
        for both purposes rather than recomputed -- wrapped in try/except
        (`None` on any failure or below `detect_market_regime`'s own
        minimum-history floor, exactly matching `run_paper.py`'s own
        `WARNING: could not compute market regime for sizing` fallback).
        `regime.volatility` (or `None`) is then passed as
        `calculate_position_size(..., volatility=...)`'s `volatility`
        argument -- `None` applies `position_sizing.py`'s unchanged 1.0x
        scalar, never a hard failure. Default `False` calls
        `calculate_position_size` with the exact same 4 positional
        arguments as before this parameter existed -- no `volatility`
        keyword at all -- so every existing caller (including test fakes
        standing in for `calculate_position_size` with the pre-Milestone-
        25 signature) is byte-for-byte unaffected. This is a measurement
        flag, not a default change: the keep-rule and any decision to
        flip the backtest default live in docs/H4_SIZING_PARITY_RESULTS.md,
        not here.

        Risk-gate rejection observability (Milestone 23, 2026-07-17,
        ENGINEERING_DECISIONS.md #60): purely additive -- see
        `BacktestResult.risk_rejections`'s own docstring for the exact
        shape. Every step whose signal is non-`None` (i.e. reaches a
        `risk_manager.evaluate()` call) increments `total_signals`; that
        call's `approved`/`rejected` outcome increments the matching
        counter; a rejected decision's `reasons` (verbatim strings, as
        returned by `RiskManager.evaluate()` -- see
        `app.risk.risk_manager.RiskDecision`) each increment `by_reason`.
        This never changes which trades happen or any existing field --
        it only observes the SAME `risk_decision` this method already
        computes and branches on.

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
        risk_rejections = _empty_risk_rejections()

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

            if strategy is not None:
                # Strategy-injection path (Milestone 9, see `strategy`'s
                # docstring above): bypasses signal_engine and every
                # SignalEngine-configuration flag entirely -- everything
                # downstream (risk gating, fills, fees, slippage, PnL) is
                # unchanged from here on regardless of which path produced
                # `signal`.
                signal = strategy.generate_signal(
                    symbol=symbol,
                    ltf_candles=ltf_candles[: i + 1],
                    htf_candles=htf_slice,
                )
            else:
                signal = signal_engine.generate_signal(
                    symbol=symbol,
                    ltf_candles=ltf_candles[: i + 1],
                    htf_candles=htf_slice,
                    use_breaker_block=use_breaker_block,
                    require_full_confluence=require_full_confluence,
                    require_ob_fvg_confluence=require_ob_fvg_confluence,
                    use_structure_tp=use_structure_tp,
                    require_premium_discount_filter=require_premium_discount_filter,
                    use_jade_engine=use_jade_engine,
                    structure_tp_max_r=structure_tp_max_r,
                    require_session=require_session,
                    atr_stop_multiplier=atr_stop_multiplier,
                )
            if signal is None:
                i += 1
                continue

            risk_rejections["total_signals"] += 1

            day_start, day_end = _day_bounds(ltf_timestamp)
            week_start, week_end = _week_bounds(ltf_timestamp)
            daily_pnl_percent = (
                _realized_pnl_in_window(trades, day_start, day_end) / starting_balance
            ) * 100
            weekly_pnl_percent = (
                _realized_pnl_in_window(trades, week_start, week_end) / starting_balance
            ) * 100

            if min_stop_atr_mult > 0.0:
                # Milestone 20a ATR stop-distance floor (default-off, see
                # `min_stop_atr_mult`'s docstring above): measured EXACTLY
                # ONCE per signal, from the identical no-lookahead slice
                # (`ltf_candles[: i + 1]`) the signal itself was generated
                # from -- no new fetch, no extra history.
                atr = average_true_range(ltf_candles[: i + 1])
                entry_price = getattr(signal, "entry_price", None)
                stop_loss = getattr(signal, "stop_loss", None)
                stop_distance_atr_mult = (
                    abs(entry_price - stop_loss) / atr
                    if atr is not None
                    and atr > 0
                    and entry_price is not None
                    and stop_loss is not None
                    else None
                )
                risk_decision = risk_manager.evaluate(
                    signal,
                    trades_today=trades_today,
                    daily_pnl_percent=daily_pnl_percent,
                    weekly_pnl_percent=weekly_pnl_percent,
                    stop_distance_atr_mult=stop_distance_atr_mult,
                    min_stop_atr_mult=min_stop_atr_mult,
                )
            else:
                risk_decision = risk_manager.evaluate(
                    signal,
                    trades_today=trades_today,
                    daily_pnl_percent=daily_pnl_percent,
                    weekly_pnl_percent=weekly_pnl_percent,
                )
            if getattr(risk_decision, "approved", False):
                risk_rejections["approved"] += 1
            else:
                risk_rejections["rejected"] += 1
                for reason in getattr(risk_decision, "reasons", None) or []:
                    risk_rejections["by_reason"][reason] = (
                        risk_rejections["by_reason"].get(reason, 0) + 1
                    )
                i += 1
                continue

            # Real position sizing (replaces the old 100%-notional
            # placeholder): sized off the signal's ORIGINAL (pre-slippage)
            # entry/stop, exactly mirroring scripts/run_paper.py's pattern,
            # so backtest sizing matches what paper/live trading will
            # actually run.
            #
            # vol_scaled_sizing (default off, see that parameter's own
            # docstring -- Milestone 25, H4 experiment): computed BEFORE
            # sizing, exactly mirroring run_paper.py's own ordering
            # (regime classified, then passed into calculate_position_size).
            # `regime_at_signal` is cached here so the `tag_regimes` block
            # below can reuse it (same ltf_candles[: i + 1] slice, same
            # walk-forward index `i`) instead of recomputing.
            if vol_scaled_sizing:
                try:
                    regime_at_signal = detect_market_regime(ltf_candles[: i + 1])
                except Exception:
                    regime_at_signal = None
                current_volatility = (
                    regime_at_signal.volatility if regime_at_signal is not None else None
                )
                size = calculate_position_size(
                    account_balance,
                    settings.RISK_PER_TRADE_PERCENT,
                    signal.entry_price,
                    signal.stop_loss,
                    volatility=current_volatility,
                )
            else:
                regime_at_signal = None
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

            fill_index = i
            fill_signal = signal
            if entry_delay_candles > 0:
                fill_index = min(i + entry_delay_candles, len(ltf_candles) - 1)
                delayed_price = _get(ltf_candles[fill_index], "close")
                # max_entry_drift_pct (opt-in, default None -- 2026-07-14
                # continuous research mode, docs/CONTINUOUS_RESEARCH_LOG.md
                # experiment 4, "entry confirmation"): if the delayed fill
                # price has moved more than this fraction away from the
                # ORIGINALLY PLANNED entry_price, skip the trade entirely
                # (same "treat like no signal" handling as the zero-size
                # guard above) instead of filling at a price the strategy
                # never actually confirmed against. Targets
                # docs/ROBUSTNESS_REPORT.md test 2's material failure
                # directly -- a delayed fill that has already drifted past
                # its own tight stop/target math is exactly the scenario
                # this rejects before it ever becomes a bad trade.
                if max_entry_drift_pct is not None and signal.entry_price:
                    drift = abs(delayed_price - signal.entry_price) / signal.entry_price
                    if drift > max_entry_drift_pct:
                        i += 1
                        continue
                # copy.copy (not dataclasses.replace) so this works against
                # ANY signal-shaped object, not just a real dataclass --
                # e.g. test fakes that duck-type TradeSignal's attributes
                # without being a dataclass themselves.
                fill_signal = copy.copy(signal)
                fill_signal.entry_price = delayed_price

            trades_today += 1
            trade, exit_index, account_balance = self._simulate_trade(
                fill_signal,
                ltf_candles,
                fill_index,
                account_balance,
                fee_percent,
                slippage_percent,
                size,
                use_breakeven=use_breakeven,
                use_partial_tp=use_partial_tp,
            )
            if tag_regimes:
                # Milestone 12 (2026-07-16, see `tag_regimes`'s docstring):
                # tag this real, risk-accepted trade with the market
                # regime as of the SIGNAL's own candle (`ltf_candles[: i +
                # 1]`) -- best-effort, WARN-and-continue on any failure,
                # matching run_paper.py's own regime-tagging spirit.
                #
                # Milestone 25 (H4 experiment, see `vol_scaled_sizing`'s
                # docstring): when vol_scaled_sizing already computed this
                # SAME regime (same slice, same index `i`) for sizing above,
                # reuse it here instead of calling detect_market_regime a
                # second time this step.
                if vol_scaled_sizing:
                    regime = regime_at_signal
                else:
                    try:
                        regime = detect_market_regime(ltf_candles[: i + 1])
                    except Exception:
                        regime = None
                trade["market_regime"] = asdict(regime) if regime is not None else None
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
            risk_rejections=risk_rejections,
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
        use_partial_tp: bool = False,
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

        `use_partial_tp`: when `True`, `PARTIAL_TP_PORTION` of `size`
        closes at the `PARTIAL_TP_TRIGGER_R`-favorable price (its own
        leg, own fee), and the REMAINING size continues toward the
        original stop_loss/take_profit unchanged. Checked in this order
        within a candle: original stop-loss first (worst case, as
        always), THEN the partial-TP trigger (if not yet triggered), THEN
        take_profit -- deliberately in that order (not stop -> TP ->
        partial) because `PARTIAL_TP_TRIGGER_R` (1R) is always closer to
        entry than `take_profit` (RR * 1R) for any RR > 1, so a candle
        whose range reaches take_profit necessarily passed through the
        partial-TP trigger price along any real (monotonic) path -- this
        lets a single candle that jumps straight to take_profit still
        correctly bank the partial leg at its own nearer price first,
        rather than skipping it. `use_partial_tp`/`use_breakeven` are
        independent, uncoupled features (this round's A/B test evaluates
        partial-TP alone, not combined with break-even).
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
        partial_tp_trigger_price = (
            (entry_fill + PARTIAL_TP_TRIGGER_R * risk_per_unit)
            if is_long
            else (entry_fill - PARTIAL_TP_TRIGGER_R * risk_per_unit)
        )
        effective_stop = stop_loss
        breakeven_triggered = False
        partial_tp_triggered = False
        partial_size = 0.0
        partial_exit_price: float | None = None

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

            # Partial-TP trigger check happens AFTER the stop check but
            # BEFORE the take_profit check -- see this method's docstring
            # for why that specific ordering: PARTIAL_TP_TRIGGER_R (1R) is
            # always closer to entry than take_profit for any RR > 1, so a
            # candle that reaches take_profit necessarily passed through
            # the partial trigger price too. Checking it first lets a
            # single candle that jumps straight to take_profit still
            # correctly bank the partial leg at its own nearer price.
            if use_partial_tp and not partial_tp_triggered and risk_per_unit > 0:
                triggered_this_candle = (
                    (is_long and high is not None and high >= partial_tp_trigger_price)
                    or (not is_long and low is not None and low <= partial_tp_trigger_price)
                )
                if triggered_this_candle:
                    partial_size = size * PARTIAL_TP_PORTION
                    partial_exit_price = partial_tp_trigger_price
                    partial_tp_triggered = True

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
        #
        # Two-leg PnL when a partial-TP fired: `remaining_size` (size minus
        # whatever partial_size already closed) is what actually rides to
        # `exit_price`, not the full `size` -- and the partial leg's own
        # raw PnL/fee (computed at ITS OWN price, `partial_exit_price`) is
        # added on top. When `partial_tp_triggered` is False (feature
        # disabled or never triggered), `partial_size` stays 0.0 and
        # `remaining_size` reduces to exactly `size` -- byte-for-byte the
        # original single-leg formula.
        remaining_size = size - partial_size

        if is_long:
            remaining_raw_pnl = remaining_size * (exit_price - entry_fill)
        else:
            remaining_raw_pnl = remaining_size * (entry_fill - exit_price)

        if partial_tp_triggered:
            if is_long:
                partial_raw_pnl = partial_size * (partial_exit_price - entry_fill)
            else:
                partial_raw_pnl = partial_size * (entry_fill - partial_exit_price)
        else:
            partial_raw_pnl = 0.0

        # Fees must scale with the ACTUAL notional traded at each leg, not
        # a flat percent-of-account-equity approximation like before --
        # otherwise a small, properly-risk-sized position would still pay
        # fees as if it were the full account, silently overstating costs
        # (or, before this fix, silently understating PnL magnitude via the
        # old formula's coupling to account_balance). Entry-leg notional is
        # `size * entry_fill` (the actual, slippage-adjusted fill price,
        # ALWAYS the full size -- one entry transaction regardless of how
        # many exit legs follow); each exit leg's notional is that leg's
        # own size times its own exit price. `fee_percent` is applied once
        # per leg, mirroring a typical per-side taker fee.
        fee_rate = fee_percent / 100
        entry_fee = fee_rate * size * entry_fill
        remaining_fee = fee_rate * remaining_size * exit_price
        partial_fee = fee_rate * partial_size * partial_exit_price if partial_tp_triggered else 0.0
        pnl = partial_raw_pnl + remaining_raw_pnl - entry_fee - partial_fee - remaining_fee
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
            "partial_tp_triggered": partial_tp_triggered,
            "partial_tp_exit_price": partial_exit_price,
            "partial_tp_pnl": (partial_raw_pnl - partial_fee) if partial_tp_triggered else None,
            # Planned (pre-trade) stop_loss/take_profit and the ORIGINAL
            # per-unit risk distance -- added for R-multiple analysis
            # (e.g. scripts/parameter_sweep.py's Average R metric).
            # `risk_per_unit` is the distance used for POSITION SIZING
            # (computed above, before any breakeven/partial-tp move), so
            # `pnl / (size * risk_per_unit)` is a real, comparable
            # R-multiple even for trades where the effective stop moved.
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_per_unit": risk_per_unit,
        }
        return trade, exit_index, account_balance
