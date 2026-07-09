"""
Milestone 3: real persistence for the trade journal -- logging the reasoning
behind trades and generating aggregate paper-trading reports -- backed by
app.database.session/models.

Capital-protection follow-up (date-scoped PnL): `generate_journal_report()`'s
original contract is all-time/cumulative with no date filtering whatsoever
(see its docstring). That is exactly right for an all-time summary, but it
is NOT a "daily loss" or "weekly loss" figure -- callers that need a
real-time drawdown check (circuit breaker, RiskManager) need PnL realized
within a specific UTC calendar window instead. `generate_journal_report()`
now accepts optional `start`/`end` bounds (still defaulting to the original
all-time, no-args behavior so existing callers/tests are unaffected), and
`generate_daily_report()` / `generate_weekly_report()` are thin convenience
wrappers that compute the "today" / "this trading week" UTC window and call
it. See the "Daily/weekly boundary convention" note in docs/risk_rules.md
for why UTC-calendar-day / ISO-calendar-week were chosen.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.database.models import StrategyLog, Trade
from app.portfolio.trades import session_scope

logger = logging.getLogger(__name__)


class TradeJournal:
    """Journals trade decisions and produces aggregate paper-trading reports."""

    def log_trade_reason(self, trade_id: int, reason: str) -> None:
        """
        Insert a StrategyLog row documenting why `trade_id` was opened.

        StrategyLog has no trade_id FK (only signal_id), so trade_id is
        stashed inside candle_context (JSON) to avoid a schema mismatch:
        module="execution", decision="trade_opened",
        candle_context={"trade_id": trade_id}.
        """
        with session_scope() as db:
            log = StrategyLog(
                module="execution",
                decision="trade_opened",
                reason=reason,
                candle_context={"trade_id": trade_id},
                timestamp=datetime.now(timezone.utc),
            )
            db.add(log)

    def save_chart_snapshot(self, trade_id: int, snapshot: Any) -> None:
        """
        Deferred past Milestone 3: there is no chart-snapshot table/column
        yet. Cleanly no-ops (logs at debug level) rather than raising, since
        this method is now reachable from the real paper-trading flow.
        """
        logger.debug(
            "save_chart_snapshot is a no-op in Milestone 3 (trade_id=%s); "
            "chart snapshot persistence is deferred to a later milestone.",
            trade_id,
        )

    def generate_journal_report(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict:
        """
        Aggregate paper-mode (mode == "paper") trades into:
          {"total_trades": int, "win_rate": float, "total_pnl": float}

        Default (start=None, end=None) -- UNCHANGED all-time/cumulative
        contract: total_trades counts every paper trade ever recorded (open
        + closed). win_rate is the fraction of CLOSED trades with pnl > 0
        (among closed trades only). total_pnl sums pnl over closed trades,
        treating a None pnl as 0. Returns all zeros when there are no
        trades (no division error). This is the original Milestone 3
        contract, relied on by existing tests/callers -- left byte-for-byte
        equivalent when called with no args.

        When `start`/`end` are BOTH given (both are required together --
        raises ValueError if only one is set), this switches to a
        REALIZED-PnL-WINDOW query instead: only trades with
        status == "closed" AND `closed_at` in the inclusive range
        [start, end] are considered at all (a trade's PnL only counts once
        realized/closed, so open trades -- which have no `closed_at` --
        cannot belong to a realized-PnL window and are excluded from
        `total_trades` in this mode, unlike the all-time default where
        `total_trades` also includes still-open trades). win_rate/total_pnl
        are computed identically over that closed, date-scoped set.
        `start`/`end` must be timezone-aware datetimes (raises ValueError
        otherwise) to avoid silently comparing local-naive and UTC values --
        callers should pass UTC (see `generate_daily_report`/
        `generate_weekly_report` below, which build correct UTC bounds).
        """
        if (start is None) != (end is None):
            raise ValueError("start and end must be provided together (or both omitted)")
        if start is not None and (start.tzinfo is None or end.tzinfo is None):  # type: ignore[union-attr]
            raise ValueError("start and end must be timezone-aware datetimes")

        with session_scope() as db:
            if start is None:
                rows = db.execute(select(Trade).where(Trade.mode == "paper")).scalars().all()
                total_trades = len(rows)
                closed = [row for row in rows if row.status == "closed"]
            else:
                closed = (
                    db.execute(
                        select(Trade).where(
                            Trade.mode == "paper",
                            Trade.status == "closed",
                            Trade.closed_at >= start,
                            Trade.closed_at <= end,
                        )
                    )
                    .scalars()
                    .all()
                )
                total_trades = len(closed)

            wins = sum(1 for row in closed if (row.pnl or 0) > 0)
            total_pnl = sum(row.pnl or 0.0 for row in closed)
            win_rate = (wins / len(closed)) if closed else 0.0
            return {
                "total_trades": total_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
            }

    def generate_daily_report(self, as_of: datetime | None = None) -> dict:
        """
        Realized paper-mode PnL for "today" -- the UTC calendar day
        containing `as_of` (defaults to now, UTC). Boundary:
        [00:00:00.000000, 23:59:59.999999] UTC on that date, inclusive.

        This mirrors the UTC-calendar-day convention `run_paper.py`'s
        `_count_trades_opened_today` already uses (`.date()` in UTC) --
        chosen for consistency rather than introducing a second, different
        notion of "day" in the same pipeline. See docs/risk_rules.md.
        """
        as_of = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
        day = as_of.date()
        day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        day_end = datetime.combine(day, time.max, tzinfo=timezone.utc)
        return self.generate_journal_report(start=day_start, end=day_end)

    def generate_weekly_report(self, as_of: datetime | None = None) -> dict:
        """
        Realized paper-mode PnL for "this trading week" -- the ISO
        calendar week (Monday 00:00:00.000000 UTC through Sunday
        23:59:59.999999 UTC, inclusive) containing `as_of` (defaults to
        now, UTC).

        ISO calendar week (not a rolling 7-day window) is the deterministic
        rule adopted here specifically for consistency with the existing
        UTC-calendar-day convention used for "daily" throughout this
        pipeline (see `generate_daily_report` above and
        `run_paper.py::_count_trades_opened_today`): both "day" and "week"
        are then simple, non-overlapping UTC calendar buckets rather than
        sliding windows, which keeps "has the boundary rolled over yet"
        unambiguous. See docs/risk_rules.md's "Daily/weekly boundary
        convention" section.
        """
        as_of = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
        monday = as_of.date() - timedelta(days=as_of.date().weekday())
        sunday = monday + timedelta(days=6)
        week_start = datetime.combine(monday, time.min, tzinfo=timezone.utc)
        week_end = datetime.combine(sunday, time.max, tzinfo=timezone.utc)
        return self.generate_journal_report(start=week_start, end=week_end)
