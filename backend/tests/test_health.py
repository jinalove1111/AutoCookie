"""Placeholder test suite.

Milestone 1 only wires up infra (dependencies, Docker image, CLI stubs);
no application or domain logic exists yet to test. Real tests should be
added per-module as app/api, app/data, app/strategy, app/risk, and
app/execution are actually implemented (e.g. test_candle_fetcher.py,
test_risk_manager.py, etc.), plus an eventual real API health-check test
once app/main.py and a /health route exist.
"""


def test_placeholder():
    assert True
