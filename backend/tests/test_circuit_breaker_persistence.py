"""Regression tests for circuit-breaker persistence across process
restarts (capital-protection follow-up to Milestone 4).

Covers:
  - app.portfolio.positions.{load,save}_circuit_breaker_state round-trip
    against a real (migrated, temp) SQLite database.
  - app.risk.circuit_breaker.PersistentCircuitBreaker: trips persist to
    DB, and a genuinely fresh instance built with a NEW `load` call against
    the SAME DB row (not the same in-memory object -- simulating a real
    process restart) observes the tripped state.
  - reset() clears persisted state too, observable by a subsequent fresh
    instance.
  - the plain app.risk.circuit_breaker.CircuitBreaker stays fully
    DB-decoupled (no persistence, unaffected by any of the above).

Tests import DB-backed modules inside the test body (after depending on
`migrated_db`), per the pattern documented in conftest.py.
"""

from __future__ import annotations


def test_load_circuit_breaker_state_defaults_to_untripped(migrated_db):
    from app.portfolio.positions import load_circuit_breaker_state

    state = load_circuit_breaker_state()

    assert state == {"tripped": False, "reason": None, "tripped_at": None}


def test_save_and_load_circuit_breaker_state_round_trip(migrated_db):
    from datetime import datetime, timezone

    from app.portfolio.positions import (
        load_circuit_breaker_state,
        save_circuit_breaker_state,
    )

    now = datetime.now(timezone.utc)
    save_circuit_breaker_state(True, "daily loss limit breached", now)

    state = load_circuit_breaker_state()

    assert state["tripped"] is True
    assert state["reason"] == "daily loss limit breached"
    assert state["tripped_at"] is not None


def test_save_circuit_breaker_state_is_idempotent_singleton_row(migrated_db):
    """Calling save twice must update the SAME bot_state row, not create a
    second one (mirrors test_get_or_create_bot_state_is_idempotent's
    guarantee for the mode column)."""
    from app.portfolio.positions import (
        get_or_create_bot_state,
        load_circuit_breaker_state,
        save_circuit_breaker_state,
    )

    save_circuit_breaker_state(True, "first trip", None)
    save_circuit_breaker_state(False, None, None)

    state = load_circuit_breaker_state()
    assert state["tripped"] is False
    assert state["reason"] is None

    # Still exactly one bot_state row.
    row = get_or_create_bot_state()
    assert row["id"] == 1


def test_persistent_circuit_breaker_trip_persists_to_db(migrated_db):
    from app.portfolio.positions import (
        load_circuit_breaker_state,
        save_circuit_breaker_state,
    )
    from app.risk.circuit_breaker import PersistentCircuitBreaker

    breaker = PersistentCircuitBreaker(
        state_loader=load_circuit_breaker_state,
        state_saver=save_circuit_breaker_state,
    )
    assert breaker.is_tripped() is False

    breaker.trip("daily loss limit breached")

    assert breaker.is_tripped() is True
    assert breaker.reason == "daily loss limit breached"
    assert breaker.tripped_at is not None

    # Persisted independently of the in-memory object: a raw load call
    # (not going through `breaker` at all) sees the same state.
    persisted = load_circuit_breaker_state()
    assert persisted["tripped"] is True
    assert persisted["reason"] == "daily loss limit breached"
    assert persisted["tripped_at"] is not None


def test_persistent_circuit_breaker_fresh_instance_observes_prior_trip_after_restart(
    migrated_db,
):
    """The core capital-protection guarantee: simulate a process restart
    by constructing a genuinely NEW PersistentCircuitBreaker (a fresh
    object, via a fresh `load` call against the same DB row -- not the
    same in-memory instance) and confirm it immediately reflects the
    prior trip, rather than silently coming back untripped.
    """
    from app.portfolio.positions import (
        load_circuit_breaker_state,
        save_circuit_breaker_state,
    )
    from app.risk.circuit_breaker import PersistentCircuitBreaker

    first = PersistentCircuitBreaker(
        state_loader=load_circuit_breaker_state,
        state_saver=save_circuit_breaker_state,
    )
    first.trip("exchange API failure")
    assert first.is_tripped() is True

    # --- Simulate a process restart ---
    # A brand-new PersistentCircuitBreaker instance, unrelated in memory to
    # `first`, constructed with its own fresh `load_circuit_breaker_state`
    # call against the same underlying DB row.
    second = PersistentCircuitBreaker(
        state_loader=load_circuit_breaker_state,
        state_saver=save_circuit_breaker_state,
    )

    assert second is not first
    assert second.is_tripped() is True
    assert second.reason == "exchange API failure"
    assert second.tripped_at is not None


def test_persistent_circuit_breaker_reset_clears_persisted_state(migrated_db):
    from app.portfolio.positions import (
        load_circuit_breaker_state,
        save_circuit_breaker_state,
    )
    from app.risk.circuit_breaker import PersistentCircuitBreaker

    first = PersistentCircuitBreaker(
        state_loader=load_circuit_breaker_state,
        state_saver=save_circuit_breaker_state,
    )
    first.trip("daily loss limit breached")
    assert first.is_tripped() is True

    first.reset()

    assert first.is_tripped() is False
    assert first.reason is None
    assert first.tripped_at is None

    # Persisted clear, observable both via a raw load call and via a fresh
    # instance (simulated restart) -- reset() must not leave stale tripped
    # state behind in the DB.
    persisted = load_circuit_breaker_state()
    assert persisted["tripped"] is False
    assert persisted["reason"] is None
    assert persisted["tripped_at"] is None

    third = PersistentCircuitBreaker(
        state_loader=load_circuit_breaker_state,
        state_saver=save_circuit_breaker_state,
    )
    assert third.is_tripped() is False


def test_persistent_circuit_breaker_trip_after_restart_and_reset_works_again(
    migrated_db,
):
    """Full lifecycle: trip -> restart (fresh load observes trip) -> reset
    -> restart again (fresh load observes cleared state) -> trip again."""
    from app.portfolio.positions import (
        load_circuit_breaker_state,
        save_circuit_breaker_state,
    )
    from app.risk.circuit_breaker import PersistentCircuitBreaker

    def fresh_instance() -> PersistentCircuitBreaker:
        return PersistentCircuitBreaker(
            state_loader=load_circuit_breaker_state,
            state_saver=save_circuit_breaker_state,
        )

    a = fresh_instance()
    a.trip("first trip")

    b = fresh_instance()  # simulated restart #1
    assert b.is_tripped() is True
    assert b.reason == "first trip"

    b.reset()

    c = fresh_instance()  # simulated restart #2
    assert c.is_tripped() is False
    assert c.reason is None

    c.trip("second trip")
    assert c.is_tripped() is True
    assert c.reason == "second trip"

    d = fresh_instance()  # simulated restart #3
    assert d.is_tripped() is True
    assert d.reason == "second trip"


def test_plain_circuit_breaker_stays_db_decoupled(migrated_db):
    """The plain (non-persistent) CircuitBreaker must remain fully
    in-memory: tripping it must NOT write anything to bot_state, and it
    must stay constructible with zero args (no DB dependency forced into
    the class)."""
    from app.portfolio.positions import load_circuit_breaker_state
    from app.risk.circuit_breaker import CircuitBreaker

    breaker = CircuitBreaker()
    breaker.trip("some reason")

    assert breaker.is_tripped() is True

    # bot_state was never touched by the plain CircuitBreaker.
    persisted = load_circuit_breaker_state()
    assert persisted == {"tripped": False, "reason": None, "tripped_at": None}
