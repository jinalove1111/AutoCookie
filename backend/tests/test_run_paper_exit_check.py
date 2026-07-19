"""Regression coverage for `scripts.run_paper._check_and_close_open_positions`
-- the first automated test of any kind for this function (validation-phase
finding, 2026-07-19: `scripts/run_paper.py` had no direct pytest coverage
at all before this file, per `CLAUDE.md`'s own disclosure, which is
exactly why the bug below went undetected).

Uses the same `migrated_db` fixture (real `alembic upgrade head` against a
throwaway temp SQLite file) every `app.portfolio.*` test in this suite
already uses -- never touches the real `backend/paper_validation.db`.
`scripts/` is a sibling directory to `backend/`, not a package under it,
so it's added to `sys.path` explicitly (same pattern every
`test_research_*.py` file in this suite already uses).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


@pytest.mark.xfail(
    reason=(
        "docs/PAPER_TRADING_VALIDATION_REPORT.md finding #1: "
        "_check_and_close_open_positions's holding_time_seconds computation "
        "subtracts a freshly-created timezone-AWARE closed_at "
        "(datetime.now(timezone.utc)) from opened_at as READ BACK FROM "
        "SQLITE -- SQLite's dialect does not preserve tz-awareness on "
        "round-trip even though Trade.opened_at is declared "
        "DateTime(timezone=True), so opened_at comes back naive and the "
        "subtraction raises TypeError. The crash happens BEFORE "
        "TradeTracker.close_trade() is called, so the position never "
        "closes -- and since run_once()'s concurrency guard skips all "
        "future signal generation while any position remains open, this "
        "permanently halts the paper trader the first time any real "
        "trade's stop-loss or take-profit is actually reached on a pass "
        "AFTER the one that opened it. Requires explicit operator "
        "sign-off before fixing (scripts/run_paper.py is a gated file, "
        "CLAUDE.md section 2) -- this test exists to make the bug "
        "permanently visible and to turn green automatically once fixed."
    ),
    strict=True,
)
def test_check_and_close_open_positions_handles_db_roundtripped_opened_at(migrated_db):
    from app.portfolio.trades import TradeTracker

    import run_paper

    tracker = TradeTracker()
    trade_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 50010.0,
            "stop_loss": 49000.0,
            "take_profit": 52500.0,
            "size": 0.025,
            "status": "open",
            "mode": "paper",
            "opened_at": datetime.now(timezone.utc),
        }
    )

    # Price comfortably above take_profit for a long -- forces a real exit.
    closed_ids = run_paper._check_and_close_open_positions(52600.0)

    assert trade_id in closed_ids
    closed = next(t for t in tracker.get_closed_trades() if t["id"] == trade_id)
    assert closed["status"] == "closed"
    assert closed["exit_reason"] == "take_profit"
    assert closed["pnl"] > 0
