"""Regression coverage for `scripts.run_paper._check_and_close_open_positions`
-- the first automated test of any kind for this function (validation-phase
finding, 2026-07-19: `scripts/run_paper.py` had no direct pytest coverage
at all before this file, per `CLAUDE.md`'s own disclosure, which is
exactly why the bug these tests guard against went undetected).

Uses the same `migrated_db` fixture (real `alembic upgrade head` against a
throwaway temp SQLite file) every `app.portfolio.*` test in this suite
already uses -- never touches the real `backend/paper_validation.db`.
`scripts/` is a sibling directory to `backend/`, not a package under it,
so it's added to `sys.path` explicitly (same pattern every
`test_research_*.py` file in this suite already uses).

Fixed 2026-07-19 (docs/PAPER_TRADING_VALIDATION_REPORT.md Finding #1,
ENGINEERING_DECISIONS.md #72, operator-approved): these tests previously
ran `xfail(strict=True)` -- `holding_time_seconds`'s
`(closed_at - opened_at).total_seconds()` crashed with `TypeError: can't
subtract offset-naive and offset-aware datetimes` because SQLite's
SQLAlchemy dialect silently drops the timezone-awareness
`Trade.opened_at` is declared with (`DateTime(timezone=True)`), so
`opened_at` read back via `TradeTracker.get_open_positions()` is naive
while `closed_at = datetime.now(timezone.utc)` is aware. The crash
happened BEFORE `close_trade()` ever ran, so the position never closed
and every later pass's one-trade-open-at-a-time concurrency guard then
skipped signal generation forever. Fix: normalize `opened_at` to
UTC-aware if naive before the subtraction -- bookkeeping-only, does not
touch signal generation, risk evaluation, or exit-trigger logic.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _fresh_run_paper():
    """`conftest.py`'s `fresh_app_env` fixture only purges `app`/`app.*`
    from `sys.modules` between tests -- `run_paper` lives outside that
    namespace, so a cached import from an earlier test would stay bound
    to that earlier test's own (already torn down) temp database. Purge
    and re-import it fresh here, same reasoning as `conftest.py`'s own
    `_purge_app_modules`, extended to this one extra module.
    """
    sys.modules.pop("run_paper", None)
    import run_paper

    return run_paper


def _open_synthetic_trade(tracker, *, direction: str, entry: float, stop: float, target: float):
    return tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": direction,
            "entry_price": entry,
            "stop_loss": stop,
            "take_profit": target,
            "size": 0.025,
            "status": "open",
            "mode": "paper",
            "opened_at": datetime.now(timezone.utc),
        }
    )


def test_check_and_close_open_positions_handles_db_roundtripped_opened_at_take_profit(migrated_db):
    from app.portfolio.trades import TradeTracker

    run_paper = _fresh_run_paper()

    tracker = TradeTracker()
    trade_id = _open_synthetic_trade(tracker, direction="long", entry=50010.0, stop=49000.0, target=52500.0)

    # Price comfortably above take_profit for a long -- forces a real exit.
    closed_ids = run_paper._check_and_close_open_positions(52600.0)

    assert trade_id in closed_ids
    closed = next(t for t in tracker.get_closed_trades() if t["id"] == trade_id)
    assert closed["status"] == "closed"
    assert closed["exit_reason"] == "take_profit"
    assert closed["pnl"] > 0
    assert closed["holding_time_seconds"] is not None
    assert closed["holding_time_seconds"] >= 0


def test_check_and_close_open_positions_handles_db_roundtripped_opened_at_stop_loss(migrated_db):
    from app.portfolio.trades import TradeTracker

    run_paper = _fresh_run_paper()

    tracker = TradeTracker()
    trade_id = _open_synthetic_trade(tracker, direction="long", entry=50010.0, stop=49000.0, target=52500.0)

    # Price comfortably below stop_loss for a long -- forces a real exit.
    closed_ids = run_paper._check_and_close_open_positions(48900.0)

    assert trade_id in closed_ids
    closed = next(t for t in tracker.get_closed_trades() if t["id"] == trade_id)
    assert closed["status"] == "closed"
    assert closed["exit_reason"] == "stop_loss"
    assert closed["pnl"] < 0
    assert closed["holding_time_seconds"] is not None
    assert closed["holding_time_seconds"] >= 0
