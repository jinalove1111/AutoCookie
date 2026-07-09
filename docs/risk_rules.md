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

## Daily/weekly boundary convention

Both "daily" and "weekly" PnL windows are simple, non-overlapping UTC
calendar buckets, never sliding windows:

- **Daily** = the UTC calendar day, `[00:00:00.000000, 23:59:59.999999]`
  UTC.
- **Weekly** = the ISO calendar week, Monday `00:00:00.000000` UTC through
  Sunday `23:59:59.999999` UTC (inclusive).

ISO calendar week (rather than e.g. a rolling 7-day window) was chosen
specifically for consistency with the UTC-calendar-day convention already
used elsewhere in this pipeline (`scripts/run_paper.py`'s
`_count_trades_opened_today` already buckets by `.date()` in UTC) — both
"day" and "week" boundaries are then simple calendar buckets with an
unambiguous "has this rolled over yet" answer, rather than two different
notions of time window coexisting in the same system.

Realized (closed) trade PnL is attributed to whichever day/week its
`closed_at` timestamp falls in — a trade's PnL only counts once
realized/closed, never at open. Implemented in
`app.portfolio.journal.TradeJournal.generate_daily_report()` /
`generate_weekly_report()`, consumed by both `RiskManager.evaluate()`
(per-signal daily/weekly loss checks) and `scripts/run_paper.py`'s
loop-mode circuit-breaker drawdown check.

## Behavior

**What actually happens today (precise, not aspirational):** when the loop
mode circuit breaker (`PersistentCircuitBreaker`, DB-persisted across
process restarts) detects a real daily OR weekly loss-limit breach, it
trips and blocks every subsequent signal via `RiskManager.evaluate()` —
independently, `RiskManager.evaluate()` also rejects any individual signal
whenever the real daily/weekly PnL% itself breaches the configured limit,
circuit breaker or not.

There is currently **no automatic day-boundary (or week-boundary) reset**.
Once tripped, the circuit breaker stays tripped until a human explicitly
calls `.reset()` — it does NOT auto-clear at UTC midnight or at the start
of a new ISO week, even though the underlying daily/weekly PnL% figures
themselves will naturally roll off old losses once those trades age out of
the window. This is a deliberate decision, not an oversight: this is
currently a single-trader system, and requiring a human to look at *why*
a loss limit was hit before resuming may well be the right design, not a
gap. It is stated plainly here so the documented behavior never implies
something the code doesn't do. Implementing automatic day/week-boundary
reset (if ever desired) is a larger, separate design question — out of
scope for this document to resolve; the correct semantics of "reset at
which exact boundary, and should a genuinely fresh day/week with a
still-tripped breaker require re-confirmation" need explicit product
discussion first.

Single-pass mode (`scripts/run_paper.py` run with no `--iterations`, i.e.
`run_once()` called with no circuit breaker at all) has no persistent
breaker to trip in the first place, but is still protected at the
per-signal level: `RiskManager.evaluate()` always receives the real,
freshly-queried daily/weekly PnL% on every invocation (not from
in-process memory), so a real loss-limit breach is independently
re-detected and re-rejected on every single-pass run for as long as it
remains within the UTC-day/ISO-week window — this does not depend on any
state surviving between separate process invocations.

## Notes

- These values are configured via environment variables (see
  `.env.example`): `MAX_DAILY_LOSS_PERCENT`, `MAX_WEEKLY_LOSS_PERCENT`,
  `RISK_PER_TRADE_PERCENT`, `MAX_TRADES_PER_DAY`, `MIN_RR`.
- The Risk Engine always sits between the Strategy Engine and the Execution
  Engine. No trade signal reaches the Execution Engine without passing
  through the Risk Engine first.
- `MAX_WEEKLY_LOSS_PERCENT` is enforced the same way `MAX_DAILY_LOSS_PERCENT`
  is: via `DrawdownGuard.check_weekly_loss()` inside `RiskManager.evaluate()`
  (per-signal) and via the loop-mode circuit-breaker drawdown check in
  `scripts/run_paper.py` (see "Behavior" above and "Daily/weekly boundary
  convention" above for exactly what window it uses).
- Actual validation logic implementation is scheduled for Milestone 2 (see
  `next_milestone_plan.md`). This document defines the rule set only.
