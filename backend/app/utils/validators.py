"""Simple, generic validation helpers. No strategy/risk decision logic."""

from __future__ import annotations


def is_valid_rr(rr: float, min_rr: float) -> bool:
    """Return True if a risk/reward ratio meets or exceeds the minimum required."""
    return rr >= min_rr


def is_positive_number(value: float) -> bool:
    """Return True if value is a finite number greater than zero."""
    return isinstance(value, (int, float)) and value > 0


def is_within_percent_bounds(value: float, min_percent: float, max_percent: float) -> bool:
    """Return True if value falls within [min_percent, max_percent] inclusive."""
    return min_percent <= value <= max_percent


def is_non_empty_string(value: str) -> bool:
    """Return True if value is a string with non-whitespace content."""
    return isinstance(value, str) and value.strip() != ""
