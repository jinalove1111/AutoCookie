# Profitability Experiment Report

Operator directive: "AUTONOMOUS 2-HOUR PROFITABILITY SPRINT" (2026-07-12).
Objective: build and validate the most robust profitable trading system,
Legacy engine remains the production baseline, every candidate feature
stays opt-in, nothing here changes production defaults.

## 1. Current production baseline

**Legacy pipeline** (`app.strategy.entry_model.build_entry_model`, the
default `SignalEngine` path). All experimental flags `False`:
`use_jade_engine`, `enable_breakeven`, `use_breaker_block`,
`use_partial_tp`, `require_full_confluence`, `require_ob_fvg_confluence`,
`use_structure_tp`, `require_premium_discount_filter`. This is the ONLY
production-approved configuration and remains unchanged by this sprint.

## 2. Paper-trading status

| | |
|---|---|
| Process | `scripts/run_paper.py --iterations 100000 --interval-seconds 300` |
| Started | 2026-07-12 19:29:11 (session-local) |
| Config | Legacy engine, all experimental flags off (matches production baseline exactly) |
| DB | `backend/paper_validation.db` (sqlite) |
| Trades so far | 0 (expected -- this strategy trades roughly once every 1-2 days at this timeframe/asset; not an error) |
| Errors | none |
| Status at sprint end | still running, untouched throughout this sprint |

**Known limitation**: this runs inside a coding sandbox, not a persistent
host. It survives as long as this environment stays alive but has no
cron/systemd/Docker keeping it running independently across environment
teardowns. For a real multi-day Gate #3 accumulation this needs to run
somewhere durable (see `ROADMAP.md`).

## 3. Experiment matrix

Built `scripts/experiment_runner.py` (Phase B): one candle fetch (LTF +
HTF), anchored to a **fixed** `--end-date 2026-07-12`, reused across every
config in one invocation -- guarantees every candidate is compared against
the literal same price data as the baseline. Periods split via the
existing `split_into_periods`; the newest period is held out as genuinely
untouched out-of-sample data. Every result appended to
`scripts/reports/experiment_results.json` (machine-readable, append-only).

**Config**: BTCUSDT, 5m, 3000 candles x 6 periods, anchored to
2026-07-12T00:00:00Z, 1 period (the newest) held out as out-of-sample,
`$10,000` starting balance, 0.05% fee, 0.02% slippage -- identical across
every config in this matrix.

**Reproduce any result**:
```
python scripts/experiment_runner.py --configs <name> --candles 3000 \
  --periods 6 --holdout-periods 1 --end-date 2026-07-12
```

Every feature tested is an EXISTING, already-implemented,
already-individually-switchable Legacy-pipeline flag. No new trading
concepts were introduced. `use_breaker_block`/`use_breakeven`/
`use_partial_tp`/`require_full_confluence`/`use_jade_engine` were
deliberately NOT re-tested -- already conclusively negative/inconsistent
across 4 assets x 2 years in prior sessions (`ENGINEERING_DECISIONS.md`
#10-#17, #34-#36); this sprint's own instruction is not to revive a
previously-conclusive negative feature without a documented implementation
defect, and none exists.

## 4. Results table

In-sample = periods 1-5 (the decision basis). Out-of-sample = period 6
(2026-07-08 -> 2026-07-12, held out, never used to pick a candidate).

| Config | In-sample Net Profit | PF | Win Rate | Max DD | Avg R | Trades | Walk-Fwd | Out-of-sample Net Profit | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **baseline** | $753.32 | 2.81 | 68.6% | 1.16% | 0.78 | 35 | PASSED (4/5) | $395.46 | BASELINE |
| `structure_tp` | **$2,731.46** | **6.29** | 60.6% | **1.14%** | 2.95 | 33 | PASSED (5/5, 0 streak) | $611.01 | **KEEP** |
| `ob_fvg_confluence` | $218.69 | 1.39 | 51.6% | 1.01% | 0.26 | 31 | PASSED (4/5) | $55.08 | REJECT |
| `premium_discount_filter` | $642.10 | 2.51 | 66.7% | 1.19% | 0.71 | 33 | PASSED (4/5) | $395.46 | REJECT |
| `structure_tp` + `premium_discount_filter` | $2,486.33 | 5.96 | 61.3% | 1.23% | 2.85 | 31 | PASSED (5/5, 0 streak) | $1,043.89 | REJECT (drawdown) |
| `structure_tp_capped_3r` (new, this sprint) | $1,068.15 | 4.01 | 73.5% | **1.14%** | 1.14 | 34 | PASSED (5/5, 0 streak) | $382.92 | **KEEP** |

Keep rule (operator directive, prior turn this session): keep only if Net
Profit AND Profit Factor AND Drawdown (worst in-sample period) all improve
over baseline, simultaneously. Ranking score (Phase C, implemented in
`experiment_runner.evaluate_candidate`): walk-forward pass > out-of-sample
profitability > Profit Factor > drawdown control > expectancy > adequate
trade count (>=20) > Net Profit, in that priority order.

## 5. Rejected candidates and reasons

- **`ob_fvg_confluence`**: worse on all three keep-rule metrics. Requiring
  both a matching OB/breaker AND a matching FVG filters out too many
  otherwise-good trades (Net Profit -71% vs. baseline, PF barely above
  break-even at 1.39).
- **`premium_discount_filter`**: Net Profit and drawdown both slightly
  worse; PF slightly better. Essentially a wash with marginally more risk
  -- same pattern this project already found for `require_full_confluence`.
- **`structure_tp` + `premium_discount_filter` (combo)**: the ONE
  "justified combination" tested (Phase B requirement #3). Highest
  absolute Net Profit and PF of every config tested, including the
  strongest out-of-sample result ($1,043.89, PF 23.55) -- but REJECTED
  anyway: in-sample worst-period drawdown (1.23%) is worse than both
  baseline (1.16%) AND `structure_tp` alone (1.14%). This is the ranking
  rule working as designed, not a bug: a very attractive out-of-sample
  number does not override a real in-sample drawdown regression. Adding
  the premium/discount filter on top of `structure_tp` does not help --
  it adds risk without a compensating drawdown benefit.

## 6. Best robust candidate

**`structure_tp`** (opt-in `use_structure_tp` on `build_entry_model`,
already shipped, already individually switchable, default `False`).
Clears all three keep-rule metrics in-sample, passes walk-forward at
100% profitable periods / 0 losing streak, and **confirms out-of-sample**
on data never touched during the decision ($611.01, 66.7% win rate,
PF 5.77 on the held-out period). This is the strongest evidence any
experimental feature has produced in this project to date.

**`structure_tp_capped_3r`** (new this sprint) also clears the bar with a
more conservative profile (lower Net Profit/PF, same drawdown, higher win
rate) -- see diagnosis below for what the cap actually reveals.

## 7. Does the Legacy baseline remain best?

**Yes, for production.** Per this sprint's explicit rule ("never replace
the production engine with an unproven strategy"), `structure_tp` clearing
this ONE experiment (1 asset, 1 time window, 5 in-sample + 1 out-of-sample
period) is evidence toward a future decision, not sufficient grounds to
flip a production default today. This project's own standing discipline
(`ENGINEERING_DECISIONS.md` #14/#15: a result must reproduce across
multiple assets AND multiple time windows before being treated as settled
-- break-even looked robust after 2 samples and reversed after a 3rd/4th)
applies here identically. Recommended next step: cross-asset validation
(Section 10) before any default changes.

## 8. Structure-TP drawdown diagnosis

**Context**: earlier in this session (before this sprint's rigorous
in-sample/out-of-sample runner existed), an ad-hoc same-day comparison
using ALL 6 periods combined (no holdout split) found `structure_tp`'s
worst-period drawdown (1.17%) worse than baseline's (0.77%), and rejected
it on that basis. Under THIS sprint's fixed-anchor, in-sample/
out-of-sample-disciplined methodology, the same feature's in-sample worst
drawdown (1.14%) is actually SLIGHTLY BETTER than baseline's (1.16%). Both
numbers are real and reproducible (both are in
`scripts/reports/experiment_results.json` and this session's tool-call
history) -- the discrepancy is a genuine, disclosed finding, not an error:
**walk-forward/drawdown conclusions are sensitive to exactly where the
period boundaries fall**, the same lesson `ENGINEERING_DECISIONS.md` #18
already documented for a different feature (BTCUSDT 2025 standard-scale
degradation). A few hours' difference in fetch anchor moved which specific
candles fell in which period, which changed which period showed the worst
drawdown. This is why the earlier "REJECT on drawdown" verdict is
superseded by this report's rigorous, fixed-anchor, held-out-out-of-sample
result -- not because the earlier number was wrong, but because it rested
on a less disciplined methodology (no fixed anchor, no held-out
confirmation).

**Separating the effects** (Phase D requirement):

- **Strategy edge (entry selection)**: IDENTICAL to baseline, by
  construction. `use_structure_tp` in `entry_model.build_entry_model`
  only overrides `take_profit`/`rr` AFTER the exact same
  bias/sweep/CHOCH/zone/stop_loss selection as the default path -- verified
  directly from the code, not inferred. Ruled out as a differentiator.
- **Position sizing effect**: identical formula
  (`calculate_position_size(account_balance, RISK_PER_TRADE_PERCENT,
  entry, stop_loss)`), same entry/stop distance for the same signal, so
  size is identical too. Ruled out as a differentiator.
- **Target distance effect**: the dominant, confirmed driver. Average R
  per trade jumped from 0.78 (baseline) to 2.95 (`structure_tp`) -- winning
  trades run much farther before resolving, which is the entire mechanism
  behind the ~3.6x Net Profit and ~2.2x Profit Factor improvement. Win
  rate drops (68.6% -> 60.6%) because a farther target is harder to reach
  before price reverses to the stop -- exactly what a "wins are rarer but
  much bigger" profile predicts.
- **Trade duration / concentration of losses / drawdown driver**: the
  `structure_tp_capped_3r` variant (new this sprint) isolates this
  directly. Capping the target's implied R at 3.0 pulls average R from
  2.95 down to 1.14 and cuts Net Profit by more than half ($2,731 ->
  $1,068) -- yet **worst-period drawdown does not change at all** (1.14%
  in both the capped and uncapped versions). This is the key diagnostic
  finding: **target distance drives profit, but is NOT the drawdown
  driver here** -- drawdown in this dataset is apparently set by which
  specific trades/periods lose, largely independent of how far the winners
  run. This refines (and partially corrects) the sprint's own framing --
  the earlier premise ("~3x profit but failed the drawdown rule") does not
  hold under rigorous measurement; profit and drawdown moved
  independently, not in the trade-off the premise assumed.
- **Regime dependence**: not yet tested (would require cross-asset/
  cross-year validation) -- see Section 10.

## 9. Conservative-exit variant implemented this sprint

`structure_tp_max_r: float | None = None` (new, opt-in, default `None` --
zero effect unless explicitly set), threaded through
`entry_model.build_entry_model` -> `signal_engine.generate_signal` ->
`backtest_engine.BacktestEngine.run()` -> `run_backtest.run_backtest()`.
Caps the structure target's implied reward:risk at the given ceiling,
clamping `take_profit` back toward `entry_price` when the uncapped
structure target would exceed it -- never changes entry/zone/stop
selection, so it can only ever make wins smaller, never introduce a new
failure mode. 3 new unit tests in `tests/test_strategy_entry_model.py`
(cap applies, cap is a no-op when already under the ceiling, cap has zero
effect when `use_structure_tp=False`). Not wired into paper trading or any
CLI flag yet -- available only via `experiment_runner.py`'s
`structure_tp_capped_3r` config pending a decision on whether to expose it
more broadly.

## 10. Recommended next experiment

1. **Cross-asset validation of `structure_tp`** (ETHUSDT/SOLUSDT/XRPUSDT,
   same fixed-anchor/in-sample/out-of-sample methodology) -- the single
   highest-value next step before any default-flipping discussion, per
   this project's own "a result must survive multiple assets before being
   trusted" discipline (`ENGINEERING_DECISIONS.md` #14/#15).
2. **Cross-year validation** (2025 anchor) on the same asset, for the same
   reason.
3. Only after both of the above: decide whether `structure_tp` (or the
   capped variant) is a candidate for a future, separate, deliberate
   default-flip decision -- never automatic just from clearing one
   experiment.

## 11. Known limitations

- Every result in this report is 1 asset (BTCUSDT), 1 fixed time window
  (anchored 2026-07-12), 5 in-sample + 1 out-of-sample period. This is
  the same "first real result, disclosed honestly, not yet broadly
  validated" status every other finding in this project starts at.
- `MIN_TRADES_FOR_CONFIDENCE = 20` (the runner's adequate-trade-count
  floor) is a disclosed, reasonable-default threshold, not itself
  backtest-derived.
- The Return/Drawdown ratio and Expectancy metrics are computed by this
  sprint's new runner and were not previously tracked anywhere else in
  this project -- no historical baseline to compare them against yet.
- Paper-trading observability gaps were found and fixed (Phase E): `Signal
  .rejection_reason`, `Trade.exit_reason`, `Trade.r_multiple`,
  `Trade.strategy_config` were all missing (only ever visible in a
  process's own stdout at the moment of the decision, never persisted).
  Fixed additively (nullable columns, backward-compatible optional
  parameters) -- source-only changes; the ALREADY-RUNNING paper-trading
  process (started before this fix) keeps using its old in-memory module
  definitions and its existing DB schema untouched. These improvements
  take effect on the next fresh `run_paper.py` start, not the currently
  running instance.
- The combo experiment (`structure_tp` + `premium_discount_filter`) is the
  only multi-feature combination tested, per this sprint's "small number
  of justified combinations" instruction -- not an exhaustive search.
