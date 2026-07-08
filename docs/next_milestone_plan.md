# Milestone 2 Plan (Proposed)

Milestone 1 produced architecture and documentation only. Milestone 2 is
the first milestone to introduce real logic, scoped as follows:

1. **Implement Strategy Engine detection logic** (bias, liquidity sweep,
   CHOCH/MSS, FVG, Order Block/Breaker Block) against real historical
   candles.
2. **Implement `candle_fetcher.py` + `data_normalizer.py`** against one real
   exchange — read-only market data only, no API keys needed.
3. **Implement `backtest_engine.py`** to run generated signals through a
   simulated fill model.
4. **Wire the Risk Engine's real validation logic** (RR check, position
   sizing, daily/weekly loss checks, max trades per day) against the signals
   produced above.

## Explicitly Out of Scope for Milestone 2

Milestone 2 still does **not** touch live order placement or real API keys
with trading permission. All work in Milestone 2 operates in Backtest Mode
using read-only, no-key market data access.
