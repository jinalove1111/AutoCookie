"""Shadow-signal outcome resolution (Milestone 14, 2026-07-16,
docs/ADAPTIVE_ARCHITECTURE.md section 4.3, ENGINEERING_DECISIONS.md #55).

Milestone 14a (landed just before this module, migration `65aba13281ad`)
added three nullable columns to `ShadowSignal` --  `outcome`
(`"tp"`/`"sl"`/`"expired"`, `NULL` = open/unresolved), `resolved_at`, and
`resolved_r` -- but nothing filled them in. `app.portfolio.shadow_recorder`
(Milestone 11) only ever INSERTs a `ShadowSignal` row at the moment a
non-active strategy would have signaled; it never revisits that row again.
Without a resolver, "shadow signals" stay a log of hypothetical entries
forever, with no record of whether they would have won or lost -- not yet
performance EVIDENCE a future Strategy Selection Engine, or a human, could
use to compare a shadow strategy against the one actually running. This
module is that resolver: given a symbol's most recent candles, it walks
every still-open `ShadowSignal` for that symbol and settles it against
those candles wherever there's enough evidence to do so.

IMPORTANT DISCLOSED LIMITATION: outcomes resolved here are simulated fills
against candle high/low only -- no fees, no slippage, no partial fills,
and no accounting for whether the "trade" could actually have been taken
at the recorded `entry_price` (unlike `app.execution.paper_broker`, which
models entry slippage for REAL paper trades). That makes a resolved shadow
outcome an OPTIMISTIC UPPER BOUND on what a shadow strategy would have
realized, not a faithful trade simulation. This is disclosed here plainly,
not hidden: modeling fees/slippage for shadow signals is a real refinement,
deliberately deferred until shadow outcomes are actually consumed by
something that routes real decisions off of them (a future Strategy
Selection Engine reading `resolved_r`) -- premature for a pass that is,
today, still just building the evidence table.

Same-candle SL/TP conservative-outcome convention: mirrors
`app.backtesting.backtest_engine.BacktestEngine._simulate_trade`'s
documented convention (backend/app/backtesting/backtest_engine.py, around
its per-candle stop/tp check: "If both levels fall within this candle's
range, assume the worse (stop_loss) outcome hit first -- the conservative
assumption."). This resolver checks `hit_sl` before `hit_tp` on every
candle for exactly the same reason: a candle whose range contains both
levels is treated as a loss, never optimistically as a win, since a single
OHLC candle can't tell us which level the price actually reached first
intra-candle.

Timestamp-format handling (verified empirically against this project's
real SQLite-backed test DB, not assumed): candle `timestamp` fields
(`app.data.data_normalizer.normalize_candle`) are always genuine
timezone-aware UTC `datetime` objects (`datetime.fromtimestamp(ts_ms /
1000, tz=timezone.utc)`) -- never a raw ms-epoch int or ISO string.
`ShadowSignal.captured_at`, however, round-trips through this project's
SQLite `DateTime(timezone=True)` columns as a NAIVE `datetime` on read
back (SQLite has no real timezone-aware column type; SQLAlchemy's sqlite
dialect stores the isoformat text and does not reattach tzinfo when
reading it back out) even though the value written was always UTC (every
write site in this codebase writes `datetime.now(timezone.utc)`, matching
`shadow_recorder.record_shadow_pass`'s own `captured_at` default,
`ShadowSignal.captured_at`'s `server_default=func.now()`). Comparing an
aware and a naive datetime directly raises `TypeError` in Python, and
comparing the raw values by accident (rather than deliberately) would
silently miscompare if one were ever in local time instead of UTC. To
handle this robustly rather than guessing, `_as_naive_utc` below
normalizes BOTH sides -- candle timestamps and `captured_at` -- to a
naive-UTC value before every comparison.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.models import ShadowSignal
from app.portfolio.trades import session_scope

# Disclosed-not-tuned (same status as other threshold constants in this
# codebase, e.g. performance_snapshots.py's _AUTO_DISABLE_PROFIT_FACTOR_THRESHOLD):
# a shadow signal that has gone 7 days without either level being touched is
# treated as "expired" -- neither a win nor a loss, just too stale to keep
# waiting on. 168 = 7 * 24 hours. Not swept/optimized; a reasonable default
# disclosed plainly as such.
EXPIRY_HOURS = 168


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute/key access that works for both dict-shaped and object-shaped
    candles -- mirrors `app.backtesting.backtest_engine._get`."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_naive_utc(dt: datetime) -> datetime:
    """Normalize an aware-or-naive datetime to a naive-UTC value for
    comparison. See this module's docstring ("Timestamp-format handling")
    for why this is necessary and how it was verified, rather than assumed."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def resolve_open_shadow_signals(
    symbol: str, ltf_candles: list, now: datetime | None = None
) -> dict:
    """Settle every still-open (`outcome IS NULL`) `ShadowSignal` row for
    `symbol` against `ltf_candles`.

    For each open signal, only candles STRICTLY AFTER the signal's own
    `captured_at` are considered (a signal can't be resolved by a candle
    that existed before -- or at the same moment as -- it was recorded);
    those candidate candles are walked oldest -> newest (the order
    `ltf_candles` is already in, per this codebase's universal
    oldest-first candle convention -- see
    `app.data.data_normalizer.normalize_candles` and
    `BacktestEngine._simulate_trade`'s own identical assumption about its
    `ltf_candles` argument) checking each candle's high/low against the
    signal's levels:

      - LONG: `hit_sl = low <= stop_loss`, `hit_tp = high >= take_profit`.
      - SHORT: mirrored (`hit_sl = high >= stop_loss`,
        `hit_tp = low <= take_profit`).

    `hit_sl` is checked BEFORE `hit_tp` on every candle -- when a single
    candle's range contains both levels, the signal is resolved as a loss,
    never a win. See this module's docstring for why (mirrors
    `BacktestEngine._simulate_trade`'s documented same-candle convention).

    On an SL hit: `outcome = "sl"`, `resolved_r = -1.0`. On a TP hit:
    `outcome = "tp"`, `resolved_r = ` this row's own `rr` column. Either
    way, `resolved_at` is set to `now` (UTC).

    If no candle resolves the signal AND `now - captured_at` exceeds
    `EXPIRY_HOURS`: `outcome = "expired"`, `resolved_r` stays `NULL`,
    `resolved_at = now`.

    Otherwise the signal is left open (untouched) -- `ltf_candles` may
    simply not reach far enough past `captured_at` yet to say either way;
    that's not an error, just insufficient evidence THIS pass. The next
    call (a later paper-trading pass, with fresher candles) retries it.

    DISCLOSED CAVEAT (see module docstring): a resolved outcome is a
    simulated fill against candle high/low only -- no fees, no slippage.
    This makes `resolved_r` an optimistic upper bound, not a faithful
    trade simulation; that refinement is deferred until shadow outcomes
    are actually consumed by something that routes real decisions off of
    them.

    `now` (optional): the "current time" used both for the expiry check
    and as the `resolved_at` value written on any resolution this call
    performs. Defaults to `datetime.now(timezone.utc)`. Exposed as a
    parameter (rather than always computing it internally) so tests can
    pin it deterministically -- same pattern
    `app.portfolio.journal.PaperTradingJournal.generate_daily_report`'s
    `as_of` parameter already establishes in this codebase.

    Returns a summary dict:
      {
        "examined": int,      # open signals for `symbol` looked at this call
        "resolved_tp": int,
        "resolved_sl": int,
        "expired": int,
        "still_open": int,    # examined but insufficient evidence yet
      }

    Uses the same `session_scope` session pattern
    `app.portfolio.shadow_recorder.record_shadow_pass` uses; this function
    does not itself catch exceptions -- callers (`scripts/run_paper.py`)
    wrap the whole shadow block in their own try/except per this
    codebase's "shadow work must never affect trading" discipline, same as
    `record_shadow_pass`.
    """
    from sqlalchemy import select

    summary = {
        "examined": 0,
        "resolved_tp": 0,
        "resolved_sl": 0,
        "expired": 0,
        "still_open": 0,
    }

    resolve_time = now if now is not None else datetime.now(timezone.utc)
    resolve_time_naive = _as_naive_utc(resolve_time)

    with session_scope() as db:
        open_signals = (
            db.execute(
                select(ShadowSignal).where(
                    ShadowSignal.symbol == symbol,
                    ShadowSignal.outcome.is_(None),
                )
            )
            .scalars()
            .all()
        )

        for sig in open_signals:
            summary["examined"] += 1
            captured_at_naive = _as_naive_utc(sig.captured_at)
            is_long = str(sig.direction or "").lower() in ("long", "buy")

            resolved = False
            for candle in ltf_candles:
                candle_ts = _get(candle, "timestamp")
                if candle_ts is None:
                    continue
                if _as_naive_utc(candle_ts) <= captured_at_naive:
                    continue  # only strictly-after candles count -- no lookback resolution

                high = _get(candle, "high")
                low = _get(candle, "low")
                if high is None or low is None:
                    continue

                if is_long:
                    hit_sl = low <= sig.stop_loss
                    hit_tp = high >= sig.take_profit
                else:
                    hit_sl = high >= sig.stop_loss
                    hit_tp = low <= sig.take_profit

                # SL checked first when both hit in one candle -- the
                # conservative worst-case assumption, mirroring
                # BacktestEngine._simulate_trade's documented convention
                # (backend/app/backtesting/backtest_engine.py: "If both
                # levels fall within this candle's range, assume the worse
                # (stop_loss) outcome hit first -- the conservative
                # assumption.").
                if hit_sl:
                    sig.outcome = "sl"
                    sig.resolved_r = -1.0
                    sig.resolved_at = resolve_time
                    summary["resolved_sl"] += 1
                    resolved = True
                    break

                if hit_tp:
                    sig.outcome = "tp"
                    sig.resolved_r = sig.rr
                    sig.resolved_at = resolve_time
                    summary["resolved_tp"] += 1
                    resolved = True
                    break

            if resolved:
                continue

            age = resolve_time_naive - captured_at_naive
            if age > timedelta(hours=EXPIRY_HOURS):
                sig.outcome = "expired"
                sig.resolved_r = None
                sig.resolved_at = resolve_time
                summary["expired"] += 1
            else:
                summary["still_open"] += 1

    return summary
