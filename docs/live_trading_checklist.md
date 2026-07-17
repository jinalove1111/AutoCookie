# Live Trading Safety Checklist

Before any real order is placed in Live Mode, all 10 of the following must
be true:

1. `LIVE_TRADING_ENABLED=true`
2. `TRADING_MODE=live`
3. API key has no withdrawal permission
4. Risk Engine approves the trade
5. Stop loss exists
6. Take profit exists
7. Position size is calculated
8. RR is at least 1:2
9. Daily loss limit not reached
10. Exchange connection is healthy

## Gate #4 hardening: verified execution latency

Gate #4 ("Risk Engine approves the trade") is not satisfied by static
approval alone -- **verified low-latency (sub-candle, ideally
seconds-scale) execution infrastructure is a hard prerequisite**,
measured signal-to-fill latency, not assumed. `docs/ATR_FLOOR_EVALUATION.md`
found that the production Legacy strategy's backtested edge did not
survive a 15-minute entry delay on the tested BTCUSDT window (profit
factor 5.024 -> 0.117, profit-to-loss sign flip, under one 15m candle of
delay) -- the edge lives inside a sub-15-minute execution window on that
evidence. Paper-trading fills that ignore latency will systematically
overstate live performance for this strategy family. Do not clear gate
#4 on backtest/paper numbers alone; measured live signal-to-fill latency
must be part of the evidence.

## Failure Behaviors

- **SL placement fails** → immediately close the position.
- **Exchange API fails** → stop new entries.
- **Daily loss reached** → disable trading until next trading day.
