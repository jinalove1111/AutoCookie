"""Tests for `app.portfolio.shadow_resolver.resolve_open_shadow_signals`
(Milestone 14b, 2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md section 4.3,
ENGINEERING_DECISIONS.md #55; realistic-fill model, Milestone 18c,
2026-07-16, docs/RESEARCH_ROUND_1.md recommendation #3).

Uses the same real-migration-driven temp-DB fixtures
(`migrated_db`/`db_session`) `test_shadow_observability_schema.py` /
`test_shadow_recorder.py` use. Open `ShadowSignal` rows are inserted
directly via the ORM (this module doesn't touch strategy evaluation at
all, unlike `test_shadow_recorder.py`), then resolved against synthetic
candle lists built with REAL timezone-aware UTC `datetime` timestamps --
matching `app.data.data_normalizer.normalize_candle`'s actual output
shape, not a guessed ms-epoch-int or ISO-string format (see
`shadow_resolver`'s module docstring for how that was verified).

Every test pins `now=FIXED_NOW` explicitly rather than relying on the
wall clock, for full determinism (same pattern
`PaperTradingJournal.generate_daily_report`'s `as_of` parameter already
establishes in this codebase).

MILESTONE 18c EXPECTED-VALUE ARITHMETIC
========================================
`shadow_resolver` no longer fills at `sig.entry_price` with flat
+rr/-1.0 R multiples. Every tp/sl case below fills at the OPEN of the
first candle strictly after `captured_at` (the "entry candle"),
adjusted by REAL imported `app.execution.paper_broker` constants:

    SLIPPAGE_PERCENT = 0.0002   (a fraction, applied directly)
    FEE_PERCENT      = 0.05     (a percent -- FEE_RATE = FEE_PERCENT/100
                                  = 0.0005, mirroring
                                  BacktestEngine._simulate_trade's own
                                  `fee_rate = fee_percent / 100`)

    fill_entry = entry_open * (1 + SLIPPAGE_PERCENT)   [long]
               = entry_open * (1 - SLIPPAGE_PERCENT)   [short]

    risk = abs(fill_entry - stop_loss)

    TP:  fee_cost = FEE_RATE * (fill_entry + take_profit)
         resolved_r = (abs(take_profit - fill_entry) - fee_cost) / risk

    SL:  fee_cost = FEE_RATE * (fill_entry + stop_loss)
         resolved_r = -(risk + fee_cost) / risk

`_expected_r_tp`/`_expected_r_sl` below implement exactly this
(independently of `shadow_resolver`'s own `_resolve_tp`/`_resolve_sl` --
both are direct transcriptions of the milestone's specified formula, not
one calling the other) so each test can show its arithmetic inline via
`entry_open`/`fill_entry` comments while still asserting a
float-precision-safe expected value (`pytest.approx`) rather than a
hand-truncated decimal literal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.execution.paper_broker import FEE_PERCENT, SLIPPAGE_PERCENT

FIXED_NOW = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)

FEE_RATE = FEE_PERCENT / 100


def _fill_entry(entry_open: float, is_long: bool) -> float:
    return entry_open * (1 + SLIPPAGE_PERCENT) if is_long else entry_open * (1 - SLIPPAGE_PERCENT)


def _expected_r_tp(fill_entry: float, stop_loss: float, take_profit: float) -> float:
    risk = abs(fill_entry - stop_loss)
    fee_cost = FEE_RATE * (fill_entry + take_profit)
    return (abs(take_profit - fill_entry) - fee_cost) / risk


def _expected_r_sl(fill_entry: float, stop_loss: float) -> float:
    risk = abs(fill_entry - stop_loss)
    fee_cost = FEE_RATE * (fill_entry + stop_loss)
    return -(risk + fee_cost) / risk


def _candle(ts: datetime, high: float, low: float, open_: float | None = None) -> dict:
    return {
        "timestamp": ts,
        "open": (high + low) / 2 if open_ is None else open_,
        "high": high,
        "low": low,
        "close": (high + low) / 2,
        "volume": 10.0,
    }


def _insert_signal(db_session, **overrides):
    from app.database.models import ShadowSignal

    kwargs = dict(
        captured_at=FIXED_NOW - timedelta(hours=1),
        symbol="BTCUSDT",
        strategy_name="jade_v1",
        strategy_version="1.0",
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        rr=2.0,
    )
    kwargs.update(overrides)
    row = ShadowSignal(**kwargs)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row.id


def _reload(db_session, signal_id: int):
    from app.database.models import ShadowSignal

    db_session.expire_all()
    return db_session.get(ShadowSignal, signal_id)


def test_long_tp_hit_resolves_tp_with_realistic_r(migrated_db, db_session):
    """(a) A long signal whose take-profit is touched (without the stop
    also being touched) resolves "tp" with resolved_r computed from the
    delayed/slipped fill and both-leg fees, and resolution_model stamped.
    """
    from app.portfolio.shadow_resolver import RESOLUTION_MODEL, resolve_open_shadow_signals

    captured_at = FIXED_NOW - timedelta(hours=1)
    signal_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        rr=2.0,
    )
    # Entry candle (first strictly after captured_at): high=111, low=100
    # -> open = (111 + 100) / 2 = 105.5 -> fill_entry = 105.5 * 1.0002
    # = 105.5211. high(111) >= take_profit(110) -> tp hit on this same
    # (entry) candle.
    candles = [_candle(captured_at + timedelta(minutes=5), high=111.0, low=100.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 1,
        "resolved_tp": 1,
        "resolved_sl": 0,
        "expired": 0,
        "still_open": 0,
        "missed_entries": 0,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome == "tp"
    fill_entry = _fill_entry(105.5, is_long=True)
    assert row.resolved_r == pytest.approx(_expected_r_tp(fill_entry, 95.0, 110.0))
    assert row.resolved_at is not None
    assert row.resolution_model == RESOLUTION_MODEL


def test_long_sl_hit_resolves_sl_with_realistic_r_worse_than_negative_one(migrated_db, db_session):
    """(b) A long signal whose stop-loss is touched resolves "sl" with
    resolved_r strictly worse than -1.0 (fee_cost > 0 guarantees this),
    and resolution_model stamped."""
    from app.portfolio.shadow_resolver import RESOLUTION_MODEL, resolve_open_shadow_signals

    captured_at = FIXED_NOW - timedelta(hours=1)
    signal_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        rr=2.0,
    )
    # Entry candle: high=101, low=90 -> open = 95.5 -> fill_entry
    # = 95.5 * 1.0002 = 95.5191. low(90) <= stop_loss(95) -> sl hit.
    candles = [_candle(captured_at + timedelta(minutes=5), high=101.0, low=90.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 1,
        "resolved_tp": 0,
        "resolved_sl": 1,
        "expired": 0,
        "still_open": 0,
        "missed_entries": 0,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome == "sl"
    fill_entry = _fill_entry(95.5, is_long=True)
    expected = _expected_r_sl(fill_entry, 95.0)
    assert row.resolved_r == pytest.approx(expected)
    assert row.resolved_r < -1.0
    assert row.resolved_at is not None
    assert row.resolution_model == RESOLUTION_MODEL


def test_short_signals_mirror_long_logic(migrated_db, db_session):
    """(c) SHORT direction mirrors the long checks:
    hit_sl = high >= stop_loss, hit_tp = low <= take_profit; fill_entry
    slips DOWN for a short entry. Two rows in the same call, resolved by
    the SAME candle list (each signal computes its own independent
    entry-delay fill), prove both the tp and sl mirror paths.
    """
    from app.portfolio.shadow_resolver import RESOLUTION_MODEL, resolve_open_shadow_signals

    captured_at = FIXED_NOW - timedelta(hours=1)

    tp_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        strategy_name="short_tp_strategy",
        direction="short",
        entry_price=100.0,
        stop_loss=105.0,
        take_profit=90.0,
        rr=2.5,
    )
    sl_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        strategy_name="short_sl_strategy",
        direction="short",
        entry_price=100.0,
        stop_loss=101.0,
        take_profit=80.0,
        rr=3.0,
    )

    # candle1 (entry candle for both signals): high=95, low=89 -> open=92
    # -> fill_entry = 92 * 0.9998 = 91.9816.
    #   short-tp: hit_sl (high 95 >= 105)? no. gapped_tp (91.9816 <= 90)?
    #     no. hit_tp (low 89 <= 90)? yes -> resolved here.
    #   short-sl: hit_sl (high 95 >= 101)? no. gapped_tp (91.9816 <= 80)?
    #     no. hit_tp (low 89 <= 80)? no -> not resolved by candle1.
    # candle2: high=102, low=85. short-sl: hit_sl (high 102 >= 101)? yes
    #   -> resolved here (not the entry candle -- fill_entry already set
    #   from candle1's open, unchanged).
    candles = [
        _candle(captured_at + timedelta(minutes=5), high=95.0, low=89.0),
        _candle(captured_at + timedelta(minutes=10), high=102.0, low=85.0),
    ]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 2,
        "resolved_tp": 1,
        "resolved_sl": 1,
        "expired": 0,
        "still_open": 0,
        "missed_entries": 0,
    }

    tp_fill_entry = _fill_entry(92.0, is_long=False)
    tp_row = _reload(db_session, tp_id)
    assert tp_row.outcome == "tp"
    assert tp_row.resolved_r == pytest.approx(_expected_r_tp(tp_fill_entry, 105.0, 90.0))
    assert tp_row.resolution_model == RESOLUTION_MODEL

    sl_fill_entry = _fill_entry(92.0, is_long=False)
    sl_row = _reload(db_session, sl_id)
    assert sl_row.outcome == "sl"
    assert sl_row.resolved_r == pytest.approx(_expected_r_sl(sl_fill_entry, 101.0))
    assert sl_row.resolved_r < -1.0
    assert sl_row.resolution_model == RESOLUTION_MODEL


def test_both_levels_in_one_candle_resolves_conservative_sl(migrated_db, db_session):
    """(d) When a single candle's range contains BOTH the stop and the
    target, the signal resolves "sl" -- the conservative worst-case
    assumption mirroring BacktestEngine._simulate_trade's documented
    same-candle convention (never optimistically "tp")."""
    from app.portfolio.shadow_resolver import RESOLUTION_MODEL, resolve_open_shadow_signals

    captured_at = FIXED_NOW - timedelta(hours=1)
    signal_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=105.0,
        rr=2.0,
    )
    # Entry candle: high=110 would hit take_profit (105); low=90 would
    # hit stop_loss (95) -- both within this one candle. open = 100 ->
    # fill_entry = 100 * 1.0002 = 100.02.
    candles = [_candle(captured_at + timedelta(minutes=5), high=110.0, low=90.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result["resolved_sl"] == 1
    assert result["resolved_tp"] == 0
    row = _reload(db_session, signal_id)
    assert row.outcome == "sl"
    fill_entry = _fill_entry(100.0, is_long=True)
    assert row.resolved_r == pytest.approx(_expected_r_sl(fill_entry, 95.0))
    assert row.resolved_r < -1.0
    assert row.resolution_model == RESOLUTION_MODEL


def test_delayed_entry_gaps_through_stop_resolves_sl_worse_than_negative_one(
    migrated_db, db_session
):
    """(j) NEW (Milestone 18c): the entry candle's OWN open already gaps
    past the stop for the trade's direction before the delayed entry can
    fill. This is not special-cased -- it falls out of the ordinary
    hit_sl check (low <= open <= stop for a long), and resolves "sl"
    with the same fee/risk formula, which is always worse than -1.0."""
    from app.portfolio.shadow_resolver import RESOLUTION_MODEL, resolve_open_shadow_signals

    captured_at = FIXED_NOW - timedelta(hours=1)
    signal_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        rr=2.0,
    )
    # Entry candle gaps down hard: high=92, low=88 -> open=90 -> fill_entry
    # = 90 * 1.0002 = 90.018, already below stop_loss(95). low(88) <= 95
    # -> hit_sl true on the entry candle itself.
    candles = [_candle(captured_at + timedelta(minutes=5), high=92.0, low=88.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 1,
        "resolved_tp": 0,
        "resolved_sl": 1,
        "expired": 0,
        "still_open": 0,
        "missed_entries": 0,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome == "sl"
    fill_entry = _fill_entry(90.0, is_long=True)
    assert fill_entry < 95.0  # confirms this really is a gap-through, not an ordinary touch
    assert row.resolved_r == pytest.approx(_expected_r_sl(fill_entry, 95.0))
    assert row.resolved_r < -1.0
    assert row.resolution_model == RESOLUTION_MODEL


def test_delayed_entry_gaps_past_take_profit_resolves_expired_and_counts_missed_entry(
    migrated_db, db_session
):
    """(k) NEW (Milestone 18c): the entry candle's OWN open already gaps
    PAST the take-profit before the delayed entry can fill. Crediting
    this as a win would be an impossible fill -- per this milestone's
    explicit design decision, no new outcome value is introduced; it
    resolves "expired" (resolved_r NULL) and is additionally counted in
    "missed_entries" (on top of "expired", not instead of it)."""
    from app.portfolio.shadow_resolver import RESOLUTION_MODEL, resolve_open_shadow_signals

    captured_at = FIXED_NOW - timedelta(hours=1)
    signal_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        rr=2.0,
    )
    # Entry candle gaps up hard: high=120, low=110 -> open=115 ->
    # fill_entry = 115 * 1.0002 = 115.023, already above take_profit(110).
    # low(110) <= stop_loss(95)? no. fill_entry >= take_profit(110)? yes
    # -> gap-past-TP, not a hit_sl.
    candles = [_candle(captured_at + timedelta(minutes=5), high=120.0, low=110.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 1,
        "resolved_tp": 0,
        "resolved_sl": 0,
        "expired": 1,
        "still_open": 0,
        "missed_entries": 1,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome == "expired"
    assert row.resolved_r is None
    assert row.resolved_at is not None
    assert row.resolution_model == RESOLUTION_MODEL


def test_candle_at_or_before_captured_at_is_ignored(migrated_db, db_session):
    """(e) Candles at or before the signal's own captured_at are never
    considered, even if their high/low would otherwise trigger a level --
    no lookback resolution. Only a strictly-later candle (here, one that
    doesn't trigger anything even as the delayed-entry candle) is
    examined, so the signal stays open."""
    from app.portfolio.shadow_resolver import resolve_open_shadow_signals

    captured_at = FIXED_NOW - timedelta(hours=1)
    signal_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        rr=2.0,
    )
    candles = [
        # Strictly BEFORE captured_at -- would hit stop_loss if considered.
        _candle(captured_at - timedelta(minutes=5), high=101.0, low=80.0),
        # Exactly AT captured_at -- would hit stop_loss if considered.
        _candle(captured_at, high=101.0, low=80.0),
        # Strictly AFTER captured_at -- becomes the entry candle
        # (open=100 -> fill_entry=100.02); doesn't trigger anything.
        _candle(captured_at + timedelta(minutes=5), high=101.0, low=99.0),
    ]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 1,
        "resolved_tp": 0,
        "resolved_sl": 0,
        "expired": 0,
        "still_open": 1,
        "missed_entries": 0,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome is None
    assert row.resolved_at is None
    assert row.resolved_r is None
    assert row.resolution_model is None


def test_old_unresolved_signal_expires(migrated_db, db_session):
    """(f) A signal older than EXPIRY_HOURS (168h / 7 days) with no
    resolving candle expires: outcome="expired", resolved_r stays NULL,
    resolved_at is set, resolution_model is stamped (this IS a
    resolution, just a time-based one)."""
    from app.portfolio.shadow_resolver import (
        EXPIRY_HOURS,
        RESOLUTION_MODEL,
        resolve_open_shadow_signals,
    )

    assert EXPIRY_HOURS == 168

    captured_at = FIXED_NOW - timedelta(hours=200)
    signal_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        rr=2.0,
    )
    # No candle touches either level; the entry candle (open=100 ->
    # fill_entry=100.02) doesn't gap through anything either.
    candles = [_candle(captured_at + timedelta(minutes=5), high=101.0, low=99.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 1,
        "resolved_tp": 0,
        "resolved_sl": 0,
        "expired": 1,
        "still_open": 0,
        "missed_entries": 0,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome == "expired"
    assert row.resolved_r is None
    assert row.resolved_at is not None
    assert row.resolution_model == RESOLUTION_MODEL


def test_recent_unresolved_signal_stays_open(migrated_db, db_session):
    """(g) A signal well within EXPIRY_HOURS with no resolving candle is
    left completely untouched -- still "open" (outcome NULL,
    resolution_model NULL), ready to be retried on a later pass with
    fresher candles."""
    from app.portfolio.shadow_resolver import resolve_open_shadow_signals

    captured_at = FIXED_NOW - timedelta(hours=10)
    signal_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        rr=2.0,
    )
    candles = [_candle(captured_at + timedelta(minutes=5), high=101.0, low=99.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 1,
        "resolved_tp": 0,
        "resolved_sl": 0,
        "expired": 0,
        "still_open": 1,
        "missed_entries": 0,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome is None
    assert row.resolved_at is None
    assert row.resolved_r is None
    assert row.resolution_model is None


def test_other_symbol_signals_untouched(migrated_db, db_session):
    """(h) Resolving for "BTCUSDT" never touches an open "ETHUSDT" row,
    even when the supplied candles would trigger a level for it."""
    from app.portfolio.shadow_resolver import resolve_open_shadow_signals

    captured_at = FIXED_NOW - timedelta(hours=1)
    other_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        symbol="ETHUSDT",
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        rr=2.0,
    )
    # Would hit ETHUSDT's stop_loss if it were examined.
    candles = [_candle(captured_at + timedelta(minutes=5), high=101.0, low=90.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 0,
        "resolved_tp": 0,
        "resolved_sl": 0,
        "expired": 0,
        "still_open": 0,
        "missed_entries": 0,
    }
    row = _reload(db_session, other_id)
    assert row.outcome is None
    assert row.resolved_at is None
    assert row.resolved_r is None
    assert row.resolution_model is None


def test_already_resolved_rows_are_not_re_examined(migrated_db, db_session):
    """(i) A row that already has a non-NULL outcome is excluded by the
    query entirely (outcome IS NULL filter) -- never re-examined, even
    against candles that would otherwise flip its outcome. Its
    resolution_model (unset here, simulating a legacy pre-Milestone-18c
    row) is left exactly as it was -- proof legacy rows keep their
    honest NULL label rather than being silently upgraded."""
    from app.portfolio.shadow_resolver import resolve_open_shadow_signals

    captured_at = FIXED_NOW - timedelta(hours=1)
    already_resolved_at = FIXED_NOW - timedelta(minutes=30)
    signal_id = _insert_signal(
        db_session,
        captured_at=captured_at,
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        rr=2.0,
        outcome="tp",
        resolved_at=already_resolved_at,
        resolved_r=2.0,
        # resolution_model intentionally omitted -- simulates a legacy
        # row resolved before Milestone 18c existed.
    )
    # Would hit stop_loss if this row were re-examined.
    candles = [_candle(captured_at + timedelta(minutes=5), high=101.0, low=90.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 0,
        "resolved_tp": 0,
        "resolved_sl": 0,
        "expired": 0,
        "still_open": 0,
        "missed_entries": 0,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome == "tp"
    assert row.resolved_r == 2.0
    assert row.resolution_model is None
    # `resolved_at` round-trips through SQLite as naive (see
    # shadow_resolver's module docstring); compare on naive-UTC values
    # rather than the aware datetime originally written.
    assert row.resolved_at.replace(tzinfo=None) == already_resolved_at.astimezone(
        timezone.utc
    ).replace(tzinfo=None)
