"""Shadow-signal outcome resolution (Milestone 14, 2026-07-16,
docs/ADAPTIVE_ARCHITECTURE.md section 4.3, ENGINEERING_DECISIONS.md #55;
realistic-fill model added Milestone 18c, 2026-07-16,
docs/RESEARCH_ROUND_1.md recommendation #3).

Milestone 14a (migration `65aba13281ad`) added three nullable columns to
`ShadowSignal` -- `outcome` (`"tp"`/`"sl"`/`"expired"`, `NULL` =
open/unresolved), `resolved_at`, and `resolved_r` -- but nothing filled
them in. `app.portfolio.shadow_recorder` (Milestone 11) only ever
INSERTs a `ShadowSignal` row at the moment a non-active strategy would
have signaled; it never revisits that row again. Without a resolver,
"shadow signals" stay a log of hypothetical entries forever, with no
record of whether they would have won or lost -- not yet performance
EVIDENCE a future Strategy Selection Engine, or a human, could use to
compare a shadow strategy against the one actually running. This module
is that resolver: given a symbol's most recent candles, it walks every
still-open `ShadowSignal` for that symbol and settles it against those
candles wherever there's enough evidence to do so.

MILESTONE 18c: FROM OPTIMISTIC UPPER BOUND TO A REALISTIC FILL MODEL
======================================================================
Milestone 14b's original model resolved outcomes as simulated fills
against candle high/low ONLY -- instant, fee-free fills at the signal's
recorded `entry_price`, no slippage, no entry delay. That was disclosed
plainly as an OPTIMISTIC UPPER BOUND, not a faithful trade simulation --
and docs/ROBUSTNESS_REPORT.md subsequently PROVED those two assumptions
(zero-fee, zero-delay) decision-relevant: they materially changed a
promotion verdict for a validated candidate. This module now implements
a realistic model instead, with three moving parts:

  (a) ENTRY DELAY (one candle): the trade does NOT fill at the signal's
      recorded `entry_price`. It fills at the OPEN of the first candle
      STRICTLY AFTER the signal's `captured_at` candle -- mirroring the
      exact delay that (per ROBUSTNESS_REPORT.md) killed the validated
      candidate. Concretely: walking `ltf_candles` oldest-to-newest
      (same convention as before), the first candle whose timestamp is
      strictly after `captured_at` AND has a usable `open` value becomes
      the "entry candle"; its `open` (adjusted for slippage, see (b)) is
      `fill_entry` -- not `sig.entry_price`, which is now used only as
      the ORIGINAL signal-time reference, never as a fill price.

      Two gap-through-before-entry cases, both evaluated against
      `fill_entry` on the entry candle specifically:

        - Gapped past the STOP before the delayed entry could even
          fill (e.g. a long whose entry candle opens below its own
          stop_loss): this is NOT special-cased separately -- it falls
          out of the ordinary `hit_sl` check below (if the entry
          candle's open is already through the stop, its low is too,
          since low <= open always), so it resolves "sl" through the
          same path an intra-candle stop touch would, with the same
          (b)/(c) formula. See `_resolve_sl` -- that formula is ALWAYS
          strictly worse than -1.0 (a positive `fee_cost` term makes
          sure of it), which is exactly the "honest r, worse than -1"
          this case calls for; no separate magnitude logic is needed.

        - Gapped past the TAKE-PROFIT before the delayed entry could
          even fill (e.g. a long whose entry candle opens above its own
          take_profit): crediting this as a win would be exactly the
          kind of optimistic, physically-impossible fill this milestone
          exists to remove -- the trade was never actually filled at a
          price from which that target was still ahead of it. Per this
          milestone's explicit design decision, NO new `outcome` value
          is introduced for this (no schema churn) -- it resolves as
          `outcome = "expired"` with `resolved_r = None`, same as a
          time-based expiry, but is additionally counted in this
          function's return dict under `"missed_entries"` (on top of,
          not instead of, `"expired"`) so a caller can distinguish
          "aged out, never triggered" from "gapped past the target
          before we could get in" without a new column or outcome
          string. This check only applies on the entry candle itself
          (`is_entry_candle`) -- once a real entry has been marked, a
          later candle touching the target is an ordinary, legitimately
          earned "tp".

  (b) SLIPPAGE: adverse-direction slippage on the entry fill, using
      `app.execution.paper_broker`'s own `SLIPPAGE_PERCENT` constant
      (imported, not copied) via the exact same direction convention
      `PaperBroker.fill_entry` uses: long fills HIGHER
      (`open * (1 + SLIPPAGE_PERCENT)`), short fills LOWER
      (`open * (1 - SLIPPAGE_PERCENT)`) -- unfavorable either way.

  (c) FEES: `app.execution.paper_broker`'s own `FEE_PERCENT` constant
      (imported, not copied), converted the same way
      `BacktestEngine._simulate_trade` converts it
      (`backend/app/backtesting/backtest_engine.py`: `fee_rate =
      fee_percent / 100`) into a fraction, then applied to BOTH legs of
      the position (entry leg at `fill_entry`, exit leg at whichever
      level was actually touched) and folded into `resolved_r` in R
      terms (a one-unit position is assumed, so "notional" is just the
      leg's own price -- there is no separate `size` to multiply by,
      unlike `BacktestEngine`, which sizes a real backtest position).
      `resolved_r` is recomputed ENTIRELY from the actual fill, not
      `sig.rr`:

        risk = abs(fill_entry - stop_loss)

        TP hit:
          fee_cost = FEE_RATE * (fill_entry + take_profit)
          resolved_r = (abs(take_profit - fill_entry) - fee_cost) / risk

        SL hit:
          fee_cost = FEE_RATE * (fill_entry + stop_loss)
          resolved_r = -(risk + fee_cost) / risk
          # always strictly < -1.0 since fee_cost > 0 -- "slightly worse
          # than -1", exactly matching a real trade's stop loss costing
          # more than the raw 1R distance once fees are paid on both
          # legs.

      where `FEE_RATE = FEE_PERCENT / 100`. See `_resolve_tp`/
      `_resolve_sl` below for the exact implementation.

  (d) EVERYTHING ELSE is unchanged from Milestone 14b: the SL-first
      same-candle conservative convention (a candle whose range contains
      BOTH levels resolves "sl", never optimistically "tp" -- see the
      original "Same-candle SL/TP conservative-outcome convention"
      section below, still in force), the `EXPIRY_HOURS` window and its
      time-based "expired" resolution, `symbol` scoping, and the
      "still open, retried next pass" behavior for insufficient
      evidence. `resolved_at` continues to mean "when the resolver
      settled this row", for ANY outcome (tp/sl/expired, whether
      time-based or gap-past-TP).

RESOLUTION_MODEL / evidence honesty: every row this resolver settles
(any outcome, not just tp/sl) is stamped `resolution_model =
RESOLUTION_MODEL` (`"v2_realistic_fills"`) -- see `ShadowSignal.
resolution_model`'s own docstring in `app.database.models`. Rows
resolved by the OLD (pre-Milestone-18c) code stay `resolution_model IS
NULL` forever; that NULL is their permanent, honest label, never
backfilled, since a NULL row and a `"v2_realistic_fills"` row are two
different measurement instruments and must never be silently pooled as
if they were the same evidence (see `app.portfolio.
rolling_regime_performance`, which excludes NULL-model rows from its
evidence `n` for exactly this reason).

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
from app.execution.paper_broker import FEE_PERCENT, SLIPPAGE_PERCENT
from app.portfolio.trades import session_scope

# Disclosed-not-tuned (same status as other threshold constants in this
# codebase, e.g. performance_snapshots.py's _AUTO_DISABLE_PROFIT_FACTOR_THRESHOLD):
# a shadow signal that has gone 7 days without either level being touched is
# treated as "expired" -- neither a win nor a loss, just too stale to keep
# waiting on. 168 = 7 * 24 hours. Not swept/optimized; a reasonable default
# disclosed plainly as such.
EXPIRY_HOURS = 168

# The resolution model implemented by THIS version of this module.
# Written to `ShadowSignal.resolution_model` on every row this resolver
# settles (any outcome). `NULL` on a row means it was settled by an
# earlier version of this module under a different (more optimistic)
# model -- see this module's docstring ("RESOLUTION_MODEL / evidence
# honesty") and `ShadowSignal.resolution_model`'s own docstring.
RESOLUTION_MODEL = "v2_realistic_fills"

# FEE_PERCENT (imported from app.execution.paper_broker, not copied) is a
# percent-of-notional value ("0.05" means 0.05%), matching the exact
# convention `BacktestEngine._simulate_trade` already established
# (backend/app/backtesting/backtest_engine.py: `fee_rate = fee_percent /
# 100`) -- divide by 100 to get the fraction used directly against a
# price. SLIPPAGE_PERCENT, by contrast, is already a fraction (imported
# and used as-is) -- see `PaperBroker.fill_entry`'s own convention.
FEE_RATE = FEE_PERCENT / 100


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


def _fill_entry(entry_open: float, is_long: bool) -> float:
    """Simulate the delayed entry fill's price: `entry_open` (the OPEN of
    the first candle strictly after `captured_at` -- see this module's
    docstring, part (a)) adjusted by adverse-direction slippage, the
    exact same direction convention `app.execution.paper_broker.
    PaperBroker.fill_entry` uses for a real paper-trade entry (imported
    `SLIPPAGE_PERCENT`, not copied)."""
    if is_long:
        return entry_open * (1 + SLIPPAGE_PERCENT)
    return entry_open * (1 - SLIPPAGE_PERCENT)


def _resolve_sl(sig: ShadowSignal, fill_entry: float, resolve_time: datetime) -> None:
    """Settle `sig` as a stop-loss hit using the realistic fee/fill model
    (see this module's docstring, part (c)):

        risk = abs(fill_entry - stop_loss)
        fee_cost = FEE_RATE * (fill_entry + stop_loss)
        resolved_r = -(risk + fee_cost) / risk

    Always strictly worse than -1.0 (fee_cost > 0), whether this is an
    ordinary intra-candle stop touch or an entry-candle gap-through --
    both paths land here identically.
    """
    risk = abs(fill_entry - sig.stop_loss)
    fee_cost = FEE_RATE * (fill_entry + sig.stop_loss)
    # risk == 0 is a degenerate case (fill landed exactly on the stop) --
    # not reachable by any real candle data this codebase produces, but
    # guarded rather than left to raise ZeroDivisionError.
    resolved_r = -1.0 - fee_cost if risk <= 0 else -(risk + fee_cost) / risk

    sig.outcome = "sl"
    sig.resolved_r = resolved_r
    sig.resolved_at = resolve_time
    sig.resolution_model = RESOLUTION_MODEL


def _resolve_tp(sig: ShadowSignal, fill_entry: float, resolve_time: datetime) -> None:
    """Settle `sig` as a take-profit hit using the realistic fee/fill
    model (see this module's docstring, part (c)):

        risk = abs(fill_entry - stop_loss)
        fee_cost = FEE_RATE * (fill_entry + take_profit)
        resolved_r = (abs(take_profit - fill_entry) - fee_cost) / risk
    """
    risk = abs(fill_entry - sig.stop_loss)
    fee_cost = FEE_RATE * (fill_entry + sig.take_profit)
    resolved_r = 0.0 if risk <= 0 else (abs(sig.take_profit - fill_entry) - fee_cost) / risk

    sig.outcome = "tp"
    sig.resolved_r = resolved_r
    sig.resolved_at = resolve_time
    sig.resolution_model = RESOLUTION_MODEL


def resolve_open_shadow_signals(
    symbol: str, ltf_candles: list, now: datetime | None = None
) -> dict:
    """Settle every still-open (`outcome IS NULL`) `ShadowSignal` row for
    `symbol` against `ltf_candles`, using the realistic fill model
    documented at the top of this module (entry delay + slippage + fees;
    Milestone 18c, `RESOLUTION_MODEL = "v2_realistic_fills"`).

    For each open signal, only candles STRICTLY AFTER the signal's own
    `captured_at` are considered (a signal can't be resolved by a candle
    that existed before -- or at the same moment as -- it was recorded);
    those candidate candles are walked oldest -> newest (the order
    `ltf_candles` is already in, per this codebase's universal
    oldest-first candle convention -- see
    `app.data.data_normalizer.normalize_candles` and
    `BacktestEngine._simulate_trade`'s own identical assumption about its
    `ltf_candles` argument).

    The FIRST such candle is the "entry candle": its `open` (adjusted for
    slippage) becomes `fill_entry`, the actual simulated fill price --
    NOT `sig.entry_price` (part (a) of this module's docstring, the
    1-candle entry delay). Every candle from the entry candle onward
    (inclusive) is then checked against the signal's ORIGINAL
    `stop_loss`/`take_profit` levels (those levels don't move -- only the
    fill does):

      - LONG: `hit_sl = low <= stop_loss`, `hit_tp = high >= take_profit`.
      - SHORT: mirrored (`hit_sl = high >= stop_loss`,
        `hit_tp = low <= take_profit`).

    `hit_sl` is checked BEFORE `hit_tp` on every candle -- when a single
    candle's range contains both levels, the signal is resolved as a
    loss, never a win (see this module's docstring, "Same-candle SL/TP
    conservative-outcome convention"). On the entry candle specifically,
    a gap-past-take-profit-before-fill check (`fill_entry` already beyond
    `take_profit`) is evaluated between the `hit_sl` and `hit_tp` checks:
    see this module's docstring, part (a), for why this can't be
    optimistically credited as a "tp" and instead resolves "expired" +
    `missed_entries`.

    On an SL hit (including an entry-candle gap-through): `outcome =
    "sl"`, `resolved_r` computed by `_resolve_sl` (always < -1.0). On a
    TP hit: `outcome = "tp"`, `resolved_r` computed by `_resolve_tp`.
    Either way, `resolved_at` is set to `now` (UTC) and
    `resolution_model` is set to `RESOLUTION_MODEL`.

    If no candle resolves the signal AND `now - captured_at` exceeds
    `EXPIRY_HOURS`: `outcome = "expired"`, `resolved_r` stays `NULL`,
    `resolved_at = now`, `resolution_model = RESOLUTION_MODEL`.

    Otherwise the signal is left open (untouched, `resolution_model`
    stays whatever it already was -- NULL for a never-resolved row) --
    `ltf_candles` may simply not reach far enough past `captured_at` yet
    to say either way; that's not an error, just insufficient evidence
    THIS pass. The next call (a later paper-trading pass, with fresher
    candles) retries it.

    `now` (optional): the "current time" used both for the expiry check
    and as the `resolved_at` value written on any resolution this call
    performs. Defaults to `datetime.now(timezone.utc)`. Exposed as a
    parameter (rather than always computing it internally) so tests can
    pin it deterministically -- same pattern
    `app.portfolio.journal.PaperTradingJournal.generate_daily_report`'s
    `as_of` parameter already establishes in this codebase.

    Returns a summary dict:
      {
        "examined": int,        # open signals for `symbol` looked at this call
        "resolved_tp": int,
        "resolved_sl": int,
        "expired": int,         # includes both time-based expiries AND
                                 # gap-past-TP-before-entry resolutions
        "still_open": int,      # examined but insufficient evidence yet
        "missed_entries": int,  # subset of "expired": gapped past the
                                 # target before the delayed entry could
                                 # fill -- excluded from evidence rather
                                 # than optimistically credited as a win
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
        "missed_entries": 0,
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
            fill_entry: float | None = None

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

                # ENTRY DELAY (part (a)): the first strictly-after candle
                # with a usable open is the entry candle -- its open
                # (slippage-adjusted) becomes fill_entry, not
                # sig.entry_price.
                is_entry_candle = fill_entry is None
                if is_entry_candle:
                    entry_open = _get(candle, "open")
                    if entry_open is None:
                        continue  # can't fill without an open -- try the next candle
                    fill_entry = _fill_entry(entry_open, is_long)

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
                # assumption."). This also naturally covers a gap straight
                # through the stop on the entry candle itself (low <=
                # open <= stop implies hit_sl already).
                if hit_sl:
                    _resolve_sl(sig, fill_entry, resolve_time)
                    summary["resolved_sl"] += 1
                    resolved = True
                    break

                if is_entry_candle:
                    gapped_tp = (
                        fill_entry >= sig.take_profit
                        if is_long
                        else fill_entry <= sig.take_profit
                    )
                    if gapped_tp:
                        # Gapped straight past the target before the
                        # delayed entry could even fill -- see this
                        # module's docstring, part (a). Excluded from
                        # evidence, not optimistically credited as a win.
                        sig.outcome = "expired"
                        sig.resolved_r = None
                        sig.resolved_at = resolve_time
                        sig.resolution_model = RESOLUTION_MODEL
                        summary["expired"] += 1
                        summary["missed_entries"] += 1
                        resolved = True
                        break

                if hit_tp:
                    _resolve_tp(sig, fill_entry, resolve_time)
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
                sig.resolution_model = RESOLUTION_MODEL
                summary["expired"] += 1
            else:
                summary["still_open"] += 1

    return summary
