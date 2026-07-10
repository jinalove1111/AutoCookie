"""Circuit breaker.

Part of the Risk Engine. Disables new trade entries when tripped (e.g.
daily loss limit reached, exchange API failure).

Milestone 4 (capital-protection follow-up): `CircuitBreaker` itself stays
100% in-memory and DB-decoupled -- it must remain trivially constructible
with no args for unit tests (see tests/test_circuit_breaker.py) and must
not gain a hard dependency on app.portfolio/app.database (that would
violate the same execution/portfolio Iron Wall decoupling pattern used
elsewhere in this codebase -- see HANDOFF.md). Persistence across process
restarts is instead layered on top via `PersistentCircuitBreaker`, a thin
wrapper that the *caller* (scripts/run_paper.py) constructs by injecting
two plain callables (`state_loader` / `state_saver`) -- typically
`app.portfolio.positions.load_circuit_breaker_state` /
`.save_circuit_breaker_state`, but any callable with the same shape works
(e.g. a fake in tests), so this module never imports app.portfolio.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable


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

        This method itself only resets in-memory state on request -- it has
        no day-boundary logic of its own. Day-boundary auto-reset (was
        previously a documented gap here) is now handled by the caller:
        `scripts/run_paper.py::_check_drawdown_and_maybe_trip` calls this
        automatically once a fresh daily/weekly check both pass again,
        relying on `TradeJournal`'s reports already being UTC-day/ISO-week
        scoped rather than adding date math to this class. See that
        function's docstring for the full rationale and its documented
        caveat (assumes every trip routes through that one drawdown-check
        call site).
        """
        self.tripped = False
        self.reason = None
        self.tripped_at = None


# State-loader hooks return this shape: {"tripped": bool, "reason": str |
# None, "tripped_at": datetime | None}. State-saver hooks accept
# (tripped, reason, tripped_at) positionally and persist them; their return
# value is ignored.
StateLoader = Callable[[], dict]
StateSaver = Callable[[bool, "str | None", "datetime | None"], object]


class PersistentCircuitBreaker:
    """DB-backed CircuitBreaker wrapper: reflects prior persisted tripped
    state immediately on construction, and persists synchronously on every
    trip()/reset() call.

    Composes a plain `CircuitBreaker` (so the trip/is_tripped/reset state
    machine lives in exactly one place) and layers persistence on top via
    two caller-injected hooks -- `state_loader` / `state_saver` -- rather
    than importing app.portfolio directly, so this module keeps zero
    dependency on the database/portfolio layer. The caller that owns a
    long-lived breaker instance across a process's lifetime (currently
    scripts/run_paper.py's loop mode) constructs this with real DB-backed
    hooks; tests can inject fakes instead.

    Exposes the exact same duck-typed surface `RiskManager.evaluate()`
    relies on (`.is_tripped()`, `.reason`), plus `.tripped` / `.tripped_at`
    for parity with the plain `CircuitBreaker`, so it's a drop-in
    replacement wherever a `CircuitBreaker` instance is passed around.
    """

    def __init__(self, state_loader: StateLoader, state_saver: StateSaver) -> None:
        self._breaker = CircuitBreaker()
        self._save = state_saver

        # Load prior persisted state (if any) and apply it to the
        # in-memory breaker immediately -- this is what makes a respawned
        # process observe a real prior trip instead of silently resuming
        # trading. Never persists here (a load is read-only); persistence
        # only happens on an explicit trip()/reset() call below.
        prior = state_loader()
        if prior.get("tripped"):
            self._breaker.tripped = True
            self._breaker.reason = prior.get("reason")
            self._breaker.tripped_at = prior.get("tripped_at")

    def trip(self, reason: str) -> None:
        """Trip the breaker and persist the new state synchronously."""
        self._breaker.trip(reason)
        self._save(self._breaker.tripped, self._breaker.reason, self._breaker.tripped_at)

    def is_tripped(self) -> bool:
        """Return True if the breaker is currently tripped."""
        return self._breaker.is_tripped()

    def reset(self) -> None:
        """Clear tripped state (in-memory and persisted) back to untripped."""
        self._breaker.reset()
        self._save(self._breaker.tripped, self._breaker.reason, self._breaker.tripped_at)

    @property
    def tripped(self) -> bool:
        return self._breaker.tripped

    @property
    def reason(self) -> str | None:
        return self._breaker.reason

    @property
    def tripped_at(self) -> datetime | None:
        return self._breaker.tripped_at
