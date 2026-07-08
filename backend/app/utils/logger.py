"""Basic structured logging setup using stdlib logging. No trading logic."""

from __future__ import annotations

import logging
import sys

_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once with a consistent stream format."""
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. by a previous call or test harness).
        root.setLevel(level.upper())
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))

    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger, configuring root logging if needed."""
    if not logging.getLogger().handlers:
        configure_logging()
    return logging.getLogger(name)
