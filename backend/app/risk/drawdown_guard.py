"""Drawdown guard stub.

Part of the Risk Engine. Checks realized daily and weekly PnL against
configured max-loss thresholds to determine whether new trades may be
opened. Feeds into RiskManager approval and CircuitBreaker tripping.
"""

from __future__ import annotations


class DrawdownGuard:
    """Checks daily and weekly loss thresholds against realized PnL.

    Boolean convention (both methods): return ``True`` == safe to continue
    trading (limit NOT breached). Return ``False`` == limit breached, block
    further trading.
    """

    def check_daily_loss(self, daily_pnl: float, max_daily_loss_percent: float) -> bool:
        """Return True if trading may continue given today's PnL.

        ``daily_pnl`` and ``max_daily_loss_percent`` are both percent-of-account
        figures (consistent with the ``MAX_DAILY_LOSS_PERCENT`` env var). A
        loss is breached when ``daily_pnl < 0`` and
        ``abs(daily_pnl) >= max_daily_loss_percent``, in which case this
        returns ``False`` (blocked). Otherwise returns ``True`` (allowed).
        """
        if daily_pnl < 0 and abs(daily_pnl) >= max_daily_loss_percent:
            return False
        return True

    def check_weekly_loss(self, weekly_pnl: float, max_weekly_loss_percent: float) -> bool:
        """Return True if trading may continue given this week's PnL.

        ``weekly_pnl`` and ``max_weekly_loss_percent`` are both percent-of-account
        figures (consistent with the ``MAX_WEEKLY_LOSS_PERCENT`` env var). A
        loss is breached when ``weekly_pnl < 0`` and
        ``abs(weekly_pnl) >= max_weekly_loss_percent``, in which case this
        returns ``False`` (blocked). Otherwise returns ``True`` (allowed).
        """
        if weekly_pnl < 0 and abs(weekly_pnl) >= max_weekly_loss_percent:
            return False
        return True
