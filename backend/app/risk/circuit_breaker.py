"""Circuit breaker.

Part of the Risk Engine. Disables new trade entries when tripped (e.g.
daily loss limit reached, exchange API failure).
"""

from __future__ import annotations

from datetime import datetime, timezone


class CircuitBreaker:
    """Halts new trade entries once tripped, until explicitly reset."""

    def __init__(self) -> None:
        self.tripped: bool = False
        self.reason: str | None = None
        self.tripped_at: datetime | None = None

    def trip(self, reason: str) -> None:
        """Trip the breaker, blocking all new trade entries until reset."""
        self.tripped = True
        self.reason = reason
        self.tripped_at = datetime.now(timezone.utc)

    def is_tripped(self) -> bool:
        """Return True if the breaker is currently tripped."""
        return self.tripped

    def reset(self) -> None:
        """Clear tripped state back to False and clear reason/timestamp.

        Note: this only resets the in-memory state on request. Day-boundary
        scheduling (auto-reset "until next trading day") is a future
        milestone's responsibility.
        """
        self.tripped = False
        self.reason = None
        self.tripped_at = None
