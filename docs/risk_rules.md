# Risk Engine — Risk Rules

The Risk Engine validates every trade signal produced by the Strategy Engine
before it is allowed to reach the Execution Engine. If any rule fails, the
trade is blocked.

## Rules

- **RR minimum 1:2** — every trade signal must have a risk/reward ratio of at
  least 1:2 or it is rejected.
- **`MAX_DAILY_LOSS_PERCENT`** — maximum percentage of account equity that
  may be lost in a single trading day.
- **`MAX_WEEKLY_LOSS_PERCENT`** — maximum percentage of account equity that
  may be lost in a single trading week.
- **`RISK_PER_TRADE_PERCENT`** — percentage of account equity risked on any
  single trade; used to calculate position size.
- **`MAX_TRADES_PER_DAY`** — maximum number of trades allowed in a single
  trading day.

## Behavior

If daily loss is reached: disable trading until next trading day.

## Notes

- These values are configured via environment variables (see
  `.env.example`): `MAX_DAILY_LOSS_PERCENT`, `MAX_WEEKLY_LOSS_PERCENT`,
  `RISK_PER_TRADE_PERCENT`, `MAX_TRADES_PER_DAY`, `MIN_RR`.
- The Risk Engine always sits between the Strategy Engine and the Execution
  Engine. No trade signal reaches the Execution Engine without passing
  through the Risk Engine first.
- Actual validation logic implementation is scheduled for Milestone 2 (see
  `next_milestone_plan.md`). This document defines the rule set only.
