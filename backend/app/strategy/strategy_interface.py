"""Common Strategy interface (operator directive, 2026-07-15): "Strategies
are modules... every strategy must implement the same interface so they
are interchangeable." Protocol-based (structural typing), not an ABC --
see docs/ADAPTIVE_ARCHITECTURE.md section 6 for the full rationale
(neither Legacy's `entry_model.build_entry_model` nor Jade's
`jade_trade_plan.build_trade_plan` were designed around an inheritance
hierarchy; a Protocol lets both conform without restructuring either).

Adapters here WRAP existing, already-tested pipelines (SignalEngine's
legacy path and Jade path) via `SignalEngine` itself -- they do not
duplicate or modify any detector/composition logic. This is deliberate:
zero risk of behavioral drift between "what SignalEngine already does"
and "what a strategy module does", and zero new trading logic introduced
by this file. See docs/ADAPTIVE_ARCHITECTURE.md section 4 for where this
fits in the target pipeline (Market Data -> Market Regime Detection ->
Strategy Selection Engine -> Risk Management -> Execution -> Performance
Evaluation -> Continuous Learning) -- this module is the foundation the
Strategy Selection Engine (not yet built) will depend on.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .signal_engine import SignalEngine, TradeSignal


@runtime_checkable
class Strategy(Protocol):
    """Structural contract every strategy module must satisfy.

    `name` identifies the strategy for logging/persistence (e.g. the
    `Trade.strategy_config`/future `strategy_used` DB fields -- see
    docs/ADAPTIVE_ARCHITECTURE.md section 4 item #3, Performance Database
    extensions, not yet built). `generate_signal` must never place
    orders -- same "detection only" contract
    `SignalEngine.generate_signal` already documents; any resulting
    signal is validated by the Risk Engine before reaching Execution,
    unchanged.
    """

    name: str

    def generate_signal(
        self, symbol: str, ltf_candles: list, htf_candles: list
    ) -> "TradeSignal | None":
        """Analyze `ltf_candles`/`htf_candles` and return a TradeSignal,
        or None if no valid setup exists right now."""
        ...


class LegacyStrategy:
    """Strategy A (operator directive, 2026-07-15) -- the current
    production baseline, UNCHANGED. Wraps `SignalEngine.generate_signal`
    with `use_jade_engine=False` (its existing default) -- delegates
    entirely to the already-tested legacy pipeline (bias/sweep/CHOCH/FVG/
    order-block/breaker confluence via `entry_model.build_entry_model`).
    Still the only strategy live in paper trading; this adapter exists so
    it CAN be selected polymorphically once a Strategy Selection Engine
    is built, not because paper trading has been switched to use it yet.
    """

    name = "legacy"

    def generate_signal(
        self, symbol: str, ltf_candles: list, htf_candles: list
    ) -> "TradeSignal | None":
        return SignalEngine().generate_signal(
            symbol, ltf_candles, htf_candles, use_jade_engine=False
        )


class JadeStrategy:
    """Strategy B (operator directive, 2026-07-15) -- the full Jade
    methodology (5 entry models, exit targets, HTF confluence, trendline,
    CRT, session bias -- ENGINEERING_DECISIONS.md #23-#33), already built
    and tested, never before wired into production. Wraps
    `SignalEngine.generate_signal` with `use_jade_engine=True`, the exact
    same integration point ENGINEERING_DECISIONS.md #34 already
    established -- this adapter adds no new Jade logic, it only gives the
    existing integration a name and a shared interface. `ENGINEERING_DECISIONS.md`
    #36's first A/B result (negative, on the LEGACY-pipeline-replacement
    reading of Jade) does not disqualify Jade as a candidate STRATEGY
    MODULE in the new adaptive architecture -- a module that underperforms
    when forced to compete head-to-head as a wholesale replacement may
    still be the best module for specific regimes once a real Strategy
    Selection Engine exists to route to it conditionally rather than
    all-or-nothing.
    """

    name = "jade"

    def generate_signal(
        self, symbol: str, ltf_candles: list, htf_candles: list
    ) -> "TradeSignal | None":
        return SignalEngine().generate_signal(
            symbol, ltf_candles, htf_candles, use_jade_engine=True
        )


# Registry (operator directive: "Strategy A / Strategy B / ..."), kept as
# a plain dict rather than a class -- the Strategy Selection Engine
# (docs/ADAPTIVE_ARCHITECTURE.md section 4 item #5, not yet built) is
# what will eventually decide WHICH of these to invoke per regime; this
# registry only answers "what strategy modules currently exist and
# conform to the interface."
AVAILABLE_STRATEGIES: dict[str, Strategy] = {
    "legacy": LegacyStrategy(),
    "jade": JadeStrategy(),
}
