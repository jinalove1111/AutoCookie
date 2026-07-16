"""Tests for `app.portfolio.rolling_regime_performance`: Milestone 15's
rolling per-(strategy, regime-bucket) performance evidence layer,
docs/ADAPTIVE_ARCHITECTURE.md section 4.3, ENGINEERING_DECISIONS.md #55.

`app.*` modules are imported INSIDE each test function, not at module
level -- see conftest.py's module docstring: `app.database.session`
binds a real SQLAlchemy engine to `settings.DATABASE_URL` at IMPORT
time, so importing eagerly at collection time would bind to a stale
engine from whichever test happened to import first.

Real `ShadowSignal`/`Trade` rows are inserted via the ORM against the
same real-migration-driven temp-DB fixtures (`migrated_db`/`db_session`)
`test_shadow_observability_schema.py` and `test_performance_snapshots.py`
already use -- this proves the full read path (real sqlite file ->
`collect_regime_evidence`'s own queries -> arithmetic), not just the
arithmetic in isolation against hand-built dicts.

`collect_regime_evidence` has no `now=` override parameter (not part of
its contract), so "inside/outside the window" is expressed relative to
`NOW = datetime.now(timezone.utc)` computed once at import time here --
each test's synthetic rows are timestamped as an offset from `NOW`, and
`collect_regime_evidence` itself computes its own window relative to
the real wall clock at call time. A `window_days` large enough to
comfortably contain the small offsets used below (and small enough to
exclude the "out of window" offsets) keeps this robust against slow
test runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime.now(timezone.utc)


# --------------------------------------------------------------------
# empty DB
# --------------------------------------------------------------------


def test_empty_db_returns_empty_dict(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    assert collect_regime_evidence(db_session) == {}


# --------------------------------------------------------------------
# shadow evidence: arithmetic, expired/open exclusion, window, untagged
# --------------------------------------------------------------------


def _shadow_signal(
    *,
    strategy_name: str,
    market_regime: dict | None,
    outcome: str | None,
    resolved_r: float | None,
    captured_days_ago: float,
    resolved_days_ago: float | None,
    rr: float = 2.0,
    resolution_model: str | None = "__CURRENT__",
):
    """Build a `ShadowSignal` row. `resolution_model` defaults to the
    CURRENT resolver's `RESOLUTION_MODEL` (Milestone 18c,
    docs/RESEARCH_ROUND_1.md recommendation #3) -- the sentinel
    `"__CURRENT__"` is resolved lazily here (not at module import time)
    for the same reason `app.*` imports live inside test functions
    throughout this module (see this module's own docstring). Pass
    `resolution_model=None` explicitly to simulate a legacy row resolved
    under the pre-Milestone-18c optimistic model.
    """
    from app.database.models import ShadowSignal
    from app.portfolio.shadow_resolver import RESOLUTION_MODEL

    if resolution_model == "__CURRENT__":
        resolution_model = RESOLUTION_MODEL

    return ShadowSignal(
        captured_at=NOW - timedelta(days=captured_days_ago),
        symbol="BTCUSDT",
        strategy_name=strategy_name,
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=100.0 + rr * 5.0,
        rr=rr,
        market_regime=market_regime,
        outcome=outcome,
        resolved_at=(NOW - timedelta(days=resolved_days_ago)) if resolved_days_ago is not None else None,
        resolved_r=resolved_r,
        resolution_model=resolution_model,
    )


def test_shadow_cell_win_rate_and_expectancy_hand_computed(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "strong_trend", "volatility": "high_volatility"}
    rows = [
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome="tp",
            resolved_r=2.0, captured_days_ago=2, resolved_days_ago=1,
        )
        for _ in range(3)
    ] + [
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome="sl",
            resolved_r=-1.0, captured_days_ago=2, resolved_days_ago=1,
        )
        for _ in range(2)
    ]
    for row in rows:
        db_session.add(row)
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    key = ("jade_v1", "strong_trend/high_volatility", "shadow")
    assert key in evidence
    cell = evidence[key]
    assert cell.n == 5
    assert cell.win_rate == 3 / 5
    assert cell.expectancy_r == (2.0 + 2.0 + 2.0 - 1.0 - 1.0) / 5  # 0.8
    assert cell.n_excluded == 0
    assert cell.window_days == 30
    assert cell.sufficient is False  # 5 < MIN_TRADES_FOR_CONFIDENCE (20)


def test_shadow_expired_and_open_excluded_from_n_but_counted_in_n_excluded(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "range", "volatility": "normal_volatility"}
    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome="tp",
            resolved_r=2.0, captured_days_ago=2, resolved_days_ago=1,
        )
    )
    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome="expired",
            resolved_r=None, captured_days_ago=2, resolved_days_ago=1,
        )
    )
    # Still-open: no outcome, no resolved_at -- windowed off captured_at.
    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome=None,
            resolved_r=None, captured_days_ago=1, resolved_days_ago=None,
        )
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    cell = evidence[("jade_v1", "range/normal_volatility", "shadow")]
    assert cell.n == 1
    assert cell.n_excluded == 2
    assert cell.win_rate == 1.0
    assert cell.expectancy_r == 2.0


def test_shadow_window_filtering_by_resolved_at_and_captured_at(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "strong_trend", "volatility": "low_volatility"}
    # In window: resolved 5 days ago.
    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome="tp",
            resolved_r=2.0, captured_days_ago=6, resolved_days_ago=5,
        )
    )
    # Out of window: resolved 45 days ago (window is 30 days).
    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome="sl",
            resolved_r=-1.0, captured_days_ago=46, resolved_days_ago=45,
        )
    )
    # Out of window, still open: captured 45 days ago, never resolved.
    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome=None,
            resolved_r=None, captured_days_ago=45, resolved_days_ago=None,
        )
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    cell = evidence[("jade_v1", "strong_trend/low_volatility", "shadow")]
    assert cell.n == 1
    assert cell.win_rate == 1.0
    assert cell.n_excluded == 0  # the out-of-window sl and open rows are dropped entirely


def test_shadow_untagged_bucket_when_market_regime_none_or_incomplete(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime=None, outcome="tp",
            resolved_r=2.0, captured_days_ago=2, resolved_days_ago=1,
        )
    )
    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime={"trend": "range"}, outcome="tp",
            resolved_r=2.0, captured_days_ago=2, resolved_days_ago=1,
        )
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    cell = evidence[("jade_v1", "untagged", "shadow")]
    assert cell.n == 2


# --------------------------------------------------------------------
# resolution_model: legacy (NULL) rows excluded from n, Milestone 18c
# (v2_realistic_fills) rows counted (docs/RESEARCH_ROUND_1.md
# recommendation #3)
# --------------------------------------------------------------------


def test_shadow_legacy_resolution_model_excluded_v2_counted(db_session):
    """A tp/sl-resolved row with `resolution_model IS NULL` (resolved
    under the pre-Milestone-18c optimistic instant-fill model) is a
    DIFFERENT measurement instrument than a row resolved under the
    current model -- it must not be silently pooled into `n` alongside
    it. `collect_regime_evidence` excludes it into `n_excluded` instead;
    only the current-model row counts toward `n`/`win_rate`/
    `expectancy_r`."""
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "range", "volatility": "normal_volatility"}
    # Legacy row: resolved "tp" under the OLD model (resolution_model
    # NULL) -- observed, but not current-model evidence.
    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome="tp",
            resolved_r=2.0, captured_days_ago=2, resolved_days_ago=1,
            resolution_model=None,
        )
    )
    # Current-model row: resolved "sl" under RESOLUTION_MODEL -- counts.
    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome="sl",
            resolved_r=-1.02, captured_days_ago=2, resolved_days_ago=1,
        )
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    cell = evidence[("jade_v1", "range/normal_volatility", "shadow")]
    assert cell.n == 1
    assert cell.win_rate == 0.0
    assert cell.expectancy_r == pytest.approx(-1.02)
    assert cell.n_excluded == 1


def test_shadow_resolution_model_other_than_current_also_excluded(db_session):
    """A row resolved under some OTHER non-NULL model string (e.g. a
    future v3) is excluded from `n` the same way a NULL/legacy row is --
    only rows matching the resolver's CURRENT `RESOLUTION_MODEL` count."""
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "range", "volatility": "normal_volatility"}
    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome="tp",
            resolved_r=2.0, captured_days_ago=2, resolved_days_ago=1,
            resolution_model="v3_hypothetical_future_model",
        )
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    cell = evidence[("jade_v1", "range/normal_volatility", "shadow")]
    assert cell.n == 0
    assert cell.n_excluded == 1


# --------------------------------------------------------------------
# live (Trade) evidence: arithmetic, NULL r_multiple, missing regime, window
# --------------------------------------------------------------------


def _closed_trade(
    *,
    strategy_name: str | None,
    market_regime: dict | None,
    r_multiple: float | None,
    closed_days_ago: float,
    pnl: float = 1.0,
):
    from app.database.models import Trade

    return Trade(
        symbol="BTCUSDT",
        direction="long",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        exit_price=105.0,
        size=1.0,
        pnl=pnl,
        status="closed",
        mode="paper",
        opened_at=NOW - timedelta(days=closed_days_ago, hours=1),
        closed_at=NOW - timedelta(days=closed_days_ago),
        strategy_name=strategy_name,
        market_regime=market_regime,
        r_multiple=r_multiple,
    )


def test_live_cell_win_rate_and_expectancy_hand_computed(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "range", "volatility": "normal_volatility"}
    for r in (2.0, -1.0, 3.0):
        db_session.add(
            _closed_trade(
                strategy_name="legacy", market_regime=regime, r_multiple=r, closed_days_ago=1
            )
        )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    cell = evidence[("legacy", "range/normal_volatility", "live")]
    assert cell.n == 3
    assert cell.win_rate == 2 / 3  # 2.0 and 3.0 are wins, -1.0 is not
    assert cell.expectancy_r == (2.0 - 1.0 + 3.0) / 3
    assert cell.n_excluded == 0


def test_live_null_r_multiple_excluded_but_counted(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "range", "volatility": "normal_volatility"}
    db_session.add(
        _closed_trade(
            strategy_name="legacy", market_regime=regime, r_multiple=2.0, closed_days_ago=1
        )
    )
    db_session.add(
        _closed_trade(
            strategy_name="legacy", market_regime=regime, r_multiple=None, closed_days_ago=1
        )
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    cell = evidence[("legacy", "range/normal_volatility", "live")]
    assert cell.n == 1
    assert cell.n_excluded == 1
    assert cell.win_rate == 1.0
    assert cell.expectancy_r == 2.0


def test_live_missing_market_regime_excluded_entirely(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    db_session.add(
        _closed_trade(
            strategy_name="legacy", market_regime=None, r_multiple=2.0, closed_days_ago=1
        )
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    assert evidence == {}  # no bucket to attribute it to -- not even "untagged"


def test_live_missing_strategy_name_excluded_entirely(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "range", "volatility": "normal_volatility"}
    db_session.add(
        _closed_trade(strategy_name=None, market_regime=regime, r_multiple=2.0, closed_days_ago=1)
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    assert evidence == {}


def test_live_window_filtering_by_closed_at(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "range", "volatility": "normal_volatility"}
    db_session.add(
        _closed_trade(
            strategy_name="legacy", market_regime=regime, r_multiple=2.0, closed_days_ago=5
        )
    )
    db_session.add(
        _closed_trade(
            strategy_name="legacy", market_regime=regime, r_multiple=-1.0, closed_days_ago=45
        )
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    cell = evidence[("legacy", "range/normal_volatility", "live")]
    assert cell.n == 1
    assert cell.expectancy_r == 2.0


def test_live_open_or_cancelled_trades_ignored(db_session):
    """Only `status == "closed"` trades are evidence -- open/cancelled
    trades never reached a real outcome."""
    from app.database.models import Trade
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "range", "volatility": "normal_volatility"}
    db_session.add(
        Trade(
            symbol="BTCUSDT",
            direction="long",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            size=1.0,
            status="open",
            mode="paper",
            opened_at=NOW - timedelta(days=1),
            strategy_name="legacy",
            market_regime=regime,
        )
    )
    db_session.add(
        Trade(
            symbol="BTCUSDT",
            direction="long",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            size=1.0,
            status="cancelled",
            mode="paper",
            opened_at=NOW - timedelta(days=1),
            closed_at=NOW - timedelta(days=1),
            strategy_name="legacy",
            market_regime=regime,
            r_multiple=2.0,
        )
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    assert evidence == {}


# --------------------------------------------------------------------
# shadow/live cells kept separate
# --------------------------------------------------------------------


def test_shadow_and_live_cells_kept_separate_for_same_strategy_and_bucket(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "strong_trend", "volatility": "high_volatility"}
    db_session.add(
        _shadow_signal(
            strategy_name="jade_v1", market_regime=regime, outcome="tp",
            resolved_r=2.0, captured_days_ago=2, resolved_days_ago=1,
        )
    )
    db_session.add(
        _closed_trade(
            strategy_name="jade_v1", market_regime=regime, r_multiple=-1.0, closed_days_ago=1
        )
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    shadow_key = ("jade_v1", "strong_trend/high_volatility", "shadow")
    live_key = ("jade_v1", "strong_trend/high_volatility", "live")
    assert shadow_key in evidence
    assert live_key in evidence
    assert evidence[shadow_key].n == 1
    assert evidence[shadow_key].win_rate == 1.0
    assert evidence[live_key].n == 1
    assert evidence[live_key].win_rate == 0.0
    # Not merged: two separate cells, not one pooled 2-sample cell.
    assert evidence[shadow_key] != evidence[live_key]


# --------------------------------------------------------------------
# sufficient flag boundary: 19 vs 20
# --------------------------------------------------------------------


def test_sufficient_flag_false_at_19_true_at_20(db_session):
    from app.portfolio.rolling_regime_performance import (
        MIN_TRADES_FOR_CONFIDENCE,
        collect_regime_evidence,
    )

    assert MIN_TRADES_FOR_CONFIDENCE == 20
    regime = {"trend": "range", "volatility": "normal_volatility"}
    for _ in range(19):
        db_session.add(
            _closed_trade(
                strategy_name="legacy", market_regime=regime, r_multiple=1.0, closed_days_ago=1
            )
        )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    cell = evidence[("legacy", "range/normal_volatility", "live")]
    assert cell.n == 19
    assert cell.sufficient is False

    db_session.add(
        _closed_trade(
            strategy_name="legacy", market_regime=regime, r_multiple=1.0, closed_days_ago=1
        )
    )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30)
    cell = evidence[("legacy", "range/normal_volatility", "live")]
    assert cell.n == 20
    assert cell.sufficient is True


def test_min_samples_override(db_session):
    from app.portfolio.rolling_regime_performance import collect_regime_evidence

    regime = {"trend": "range", "volatility": "normal_volatility"}
    for _ in range(5):
        db_session.add(
            _closed_trade(
                strategy_name="legacy", market_regime=regime, r_multiple=1.0, closed_days_ago=1
            )
        )
    db_session.commit()

    evidence = collect_regime_evidence(db_session, window_days=30, min_samples=5)
    cell = evidence[("legacy", "range/normal_volatility", "live")]
    assert cell.n == 5
    assert cell.sufficient is True
