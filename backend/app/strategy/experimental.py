"""Experimental strategy registry (Milestone 9, 2026-07-16).

Quarantine discipline: this module holds strategy modules that are NOT yet
proven -- they have not been backtested/walk-forward-validated through
`app.backtesting.backtest_engine.BacktestEngine`, this repo's evidence
pipeline (same engine -- fees, slippage, walk-forward -- as the production
path). `EXPERIMENTAL_STRATEGIES` is a SEPARATE registry from
`app.strategy.strategy_interface.AVAILABLE_STRATEGIES` on purpose: the
production registry is the ONLY thing any real selector (the Strategy
Selection Engine, `app.strategy.selector`) ever consults, so a strategy
living only in `EXPERIMENTAL_STRATEGIES` cannot influence paper or live
trading no matter what it does here. Promotion of a strategy module from
`EXPERIMENTAL_STRATEGIES` into `AVAILABLE_STRATEGIES` requires real
backtest/walk-forward evidence, per this repo's existing discipline (see
ENGINEERING_DECISIONS.md's pattern of every new behavior being A/B tested
before being wired into paper/live) -- this module exists so future
strategy modules have somewhere to be evidenced BEFORE that promotion is
ever considered, not a shortcut around it.

`EXPERIMENTAL_STRATEGIES` is now POPULATED (Milestone 9 integration,
2026-07-16) with the four strategy modules that landed alongside this
quarantine mechanism -- `trend_following`, `range_trading`, `breakout`,
`volatility_expansion` -- each already conforming to the `Strategy`
Protocol. Population here is NOT promotion: none of these four has been
backtested/walk-forward-validated yet, so none is in
`AVAILABLE_STRATEGIES`, and the quarantine guarantee above still holds
in full -- no real selector consults this registry, so living here
cannot influence paper or live trading no matter what these modules do.
"""

from __future__ import annotations

from .breakout import BreakoutStrategy
from .range_trading import RangeTradingStrategy
from .strategy_interface import AVAILABLE_STRATEGIES, Strategy
from .trend_following import TrendFollowingStrategy
from .volatility_expansion import VolatilityExpansionStrategy

# Populated (Milestone 9 integration) with every experimental strategy
# module that exists and conforms to the `Strategy` Protocol, keyed by
# its own `.name`. None of these has backtest/walk-forward evidence yet
# -- see module docstring -- so none belongs in `AVAILABLE_STRATEGIES`.
EXPERIMENTAL_STRATEGIES: dict[str, Strategy] = {
    "trend_following": TrendFollowingStrategy(),
    "range_trading": RangeTradingStrategy(),
    "breakout": BreakoutStrategy(),
    "volatility_expansion": VolatilityExpansionStrategy(),
}


def all_strategies() -> dict[str, Strategy]:
    """Return every strategy the backtester can evaluate: production
    (`AVAILABLE_STRATEGIES`) plus experimental (`EXPERIMENTAL_STRATEGIES`).

    Returns a FRESH `dict` on every call (built via `{**a, **b}`, not a
    shared reference to either registry) -- a caller mutating the returned
    mapping (e.g. `scripts/run_backtest.py` doing a name lookup) can never
    corrupt either underlying registry.
    """
    return {**AVAILABLE_STRATEGIES, **EXPERIMENTAL_STRATEGIES}
