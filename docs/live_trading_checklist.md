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

## Failure Behaviors

- **SL placement fails** → immediately close the position.
- **Exchange API fails** → stop new entries.
- **Daily loss reached** → disable trading until next trading day.
