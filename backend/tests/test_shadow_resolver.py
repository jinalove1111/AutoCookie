"""Tests for `app.portfolio.shadow_resolver.resolve_open_shadow_signals`
(Milestone 14b, 2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md section 4.3,
ENGINEERING_DECISIONS.md #55).

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
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

FIXED_NOW = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)


def _candle(ts: datetime, high: float, low: float) -> dict:
    return {
        "timestamp": ts,
        "open": (high + low) / 2,
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


def test_long_tp_hit_resolves_tp_with_positive_rr(migrated_db, db_session):
    """(a) A long signal whose take-profit is touched (without the stop
    also being touched) resolves "tp" with resolved_r == the row's own rr.
    """
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
    candles = [_candle(captured_at + timedelta(minutes=5), high=111.0, low=100.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 1,
        "resolved_tp": 1,
        "resolved_sl": 0,
        "expired": 0,
        "still_open": 0,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome == "tp"
    assert row.resolved_r == 2.0
    assert row.resolved_at is not None


def test_long_sl_hit_resolves_sl_with_negative_one_r(migrated_db, db_session):
    """(b) A long signal whose stop-loss is touched resolves "sl" with
    resolved_r == -1.0."""
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
    candles = [_candle(captured_at + timedelta(minutes=5), high=101.0, low=90.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 1,
        "resolved_tp": 0,
        "resolved_sl": 1,
        "expired": 0,
        "still_open": 0,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome == "sl"
    assert row.resolved_r == -1.0
    assert row.resolved_at is not None


def test_short_signals_mirror_long_logic(migrated_db, db_session):
    """(c) SHORT direction mirrors the long checks:
    hit_sl = high >= stop_loss, hit_tp = low <= take_profit. Two rows in
    the same call, resolved by two different candles in the SAME candle
    list, prove both the tp and sl mirror paths independently.
    """
    from app.portfolio.shadow_resolver import resolve_open_shadow_signals

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

    candles = [
        # Touches short-tp's take_profit (low <= 90) but neither of
        # short-sl's levels.
        _candle(captured_at + timedelta(minutes=5), high=95.0, low=89.0),
        # Touches short-sl's stop_loss (high >= 101).
        _candle(captured_at + timedelta(minutes=10), high=102.0, low=85.0),
    ]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 2,
        "resolved_tp": 1,
        "resolved_sl": 1,
        "expired": 0,
        "still_open": 0,
    }

    tp_row = _reload(db_session, tp_id)
    assert tp_row.outcome == "tp"
    assert tp_row.resolved_r == 2.5

    sl_row = _reload(db_session, sl_id)
    assert sl_row.outcome == "sl"
    assert sl_row.resolved_r == -1.0


def test_both_levels_in_one_candle_resolves_conservative_sl(migrated_db, db_session):
    """(d) When a single candle's range contains BOTH the stop and the
    target, the signal resolves "sl" -- the conservative worst-case
    assumption mirroring BacktestEngine._simulate_trade's documented
    same-candle convention (never optimistically "tp").
    """
    from app.portfolio.shadow_resolver import resolve_open_shadow_signals

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
    # high=110 would hit take_profit (105); low=90 would hit stop_loss (95)
    # -- both within this one candle.
    candles = [_candle(captured_at + timedelta(minutes=5), high=110.0, low=90.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result["resolved_sl"] == 1
    assert result["resolved_tp"] == 0
    row = _reload(db_session, signal_id)
    assert row.outcome == "sl"
    assert row.resolved_r == -1.0


def test_candle_at_or_before_captured_at_is_ignored(migrated_db, db_session):
    """(e) Candles at or before the signal's own captured_at are never
    considered, even if their high/low would otherwise trigger a level --
    no lookback resolution. Only a strictly-later candle (here, one that
    doesn't trigger anything) is examined, so the signal stays open.
    """
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
        # Strictly AFTER captured_at -- doesn't trigger anything.
        _candle(captured_at + timedelta(minutes=5), high=101.0, low=99.0),
    ]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 1,
        "resolved_tp": 0,
        "resolved_sl": 0,
        "expired": 0,
        "still_open": 1,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome is None
    assert row.resolved_at is None
    assert row.resolved_r is None


def test_old_unresolved_signal_expires(migrated_db, db_session):
    """(f) A signal older than EXPIRY_HOURS (168h / 7 days) with no
    resolving candle expires: outcome="expired", resolved_r stays NULL,
    resolved_at is set.
    """
    from app.portfolio.shadow_resolver import EXPIRY_HOURS, resolve_open_shadow_signals

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
    # No candle touches either level.
    candles = [_candle(captured_at + timedelta(minutes=5), high=101.0, low=99.0)]

    result = resolve_open_shadow_signals("BTCUSDT", candles, now=FIXED_NOW)

    assert result == {
        "examined": 1,
        "resolved_tp": 0,
        "resolved_sl": 0,
        "expired": 1,
        "still_open": 0,
    }
    row = _reload(db_session, signal_id)
    assert row.outcome == "expired"
    assert row.resolved_r is None
    assert row.resolved_at is not None


def test_recent_unresolved_signal_stays_open(migrated_db, db_session):
    """(g) A signal well within EXPIRY_HOURS with no resolving candle is
    left completely untouched -- still "open" (outcome NULL), ready to be
    retried on a later pass with fresher candles.
    """
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
    }
    row = _reload(db_session, signal_id)
    assert row.outcome is None
    assert row.resolved_at is None
    assert row.resolved_r is None


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
    }
    row = _reload(db_session, other_id)
    assert row.outcome is None
    assert row.resolved_at is None
    assert row.resolved_r is None


def test_already_resolved_rows_are_not_re_examined(migrated_db, db_session):
    """(i) A row that already has a non-NULL outcome is excluded by the
    query entirely (outcome IS NULL filter) -- never re-examined, even
    against candles that would otherwise flip its outcome."""
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
    }
    row = _reload(db_session, signal_id)
    assert row.outcome == "tp"
    assert row.resolved_r == 2.0
    # `resolved_at` round-trips through SQLite as naive (see
    # shadow_resolver's module docstring); compare on naive-UTC values
    # rather than the aware datetime originally written.
    assert row.resolved_at.replace(tzinfo=None) == already_resolved_at.astimezone(
        timezone.utc
    ).replace(tzinfo=None)
