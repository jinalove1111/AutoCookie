"""Unit tests for app.risk.circuit_breaker.CircuitBreaker: the
trip/is_tripped/reset state machine."""

from __future__ import annotations

from app.risk.circuit_breaker import CircuitBreaker


def test_circuit_breaker_starts_untripped():
    breaker = CircuitBreaker()

    assert breaker.is_tripped() is False
    assert breaker.reason is None
    assert breaker.tripped_at is None


def test_circuit_breaker_trip_sets_state():
    breaker = CircuitBreaker()

    breaker.trip("daily loss limit breached")

    assert breaker.is_tripped() is True
    assert breaker.reason == "daily loss limit breached"
    assert breaker.tripped_at is not None


def test_circuit_breaker_reset_clears_state():
    breaker = CircuitBreaker()
    breaker.trip("exchange API failure")

    breaker.reset()

    assert breaker.is_tripped() is False
    assert breaker.reason is None
    assert breaker.tripped_at is None


def test_circuit_breaker_trip_after_reset_works_again():
    breaker = CircuitBreaker()
    breaker.trip("first trip")
    breaker.reset()

    breaker.trip("second trip")

    assert breaker.is_tripped() is True
    assert breaker.reason == "second trip"
