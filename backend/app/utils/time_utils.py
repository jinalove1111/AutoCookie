"""Time helpers — UTC clock and timeframe-string parsing. No trading logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_UNIT_TO_KWARG = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def timeframe_to_timedelta(timeframe: str) -> timedelta:
    """Convert a timeframe string like '5m', '4h', '1d' into a timedelta.

    Supported unit suffixes: s (seconds), m (minutes), h (hours), d (days),
    w (weeks).
    """
    timeframe = timeframe.strip().lower()
    if len(timeframe) < 2:
        raise ValueError(f"Invalid timeframe: {timeframe!r}")

    unit = timeframe[-1]
    value_str = timeframe[:-1]

    if unit not in _UNIT_TO_KWARG:
        raise ValueError(f"Unsupported timeframe unit {unit!r} in {timeframe!r}")

    try:
        value = int(value_str)
    except ValueError as exc:
        raise ValueError(f"Invalid timeframe numeric value in {timeframe!r}") from exc

    return timedelta(**{_UNIT_TO_KWARG[unit]: value})
