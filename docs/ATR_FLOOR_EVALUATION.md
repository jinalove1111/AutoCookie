# ATR Stop-Distance Floor Evaluation — Milestone 20b

Backtest Agent deliverable (2026-07-16/17), CTO directive. The A/B evidence
round that decides whether the Milestone 18b ATR stop-distance floor
(`RiskManager.evaluate()`'s `min_stop_atr_mult` gate, exercisable via
`scripts/run_backtest.py --min-stop-atr` since Milestone 20a) may ever be
enabled. **The question** (from `docs/ROBUSTNESS_REPORT.md` test 2 and
`docs/RESEARCH_ROUND_1.md` recommendation #2): the platform's only validated
candidate died from delay fragility caused by stops averaging 0.17–0.23% of
price; does enforcing a minimum stop distance (in ATR multiples) improve
DELAY ROBUSTNESS without destroying profitability? This is **evidence
collection only** — run, measure, record honestly. No parameters were tuned,
no code was touched, every number below is transcribed from the actual run
logs (`scripts/reports/eval_m20_baseline.log`, `scripts/reports/eval_m20_atr15.log`).

## 1. Purpose and methodology

**Anchor (identical across all runs)**: `--symbol BTCUSDT --timeframe 15m
--candles 3000 --periods 6 --end-date 2026-07-10 --walk-forward
--delay-check`. Every configuration fetched the SAME 18,000 LTF (15m)
candles and the SAME 1,125 HTF (4h) candles from OKX, split into the same 6
non-overlapping chronological periods (2026-01-03 12:00 UTC through
2026-07-09 23:45 UTC — byte-identical period boundaries across both
completed runs, verified in the logs). This is the same standard anchor used
by `docs/EXPERIMENTAL_STRATEGY_EVALUATION.md`, and the baseline run
reproduced that document's Legacy numbers exactly (111 trades, +$3,400.62,
6/6 profitable, walk-forward PASSED) — confirming apples-to-apples
comparability with the prior evidence base.

**Engine**: `BacktestEngine.run()` via `scripts/run_backtest.py`, standard
fee/slippage defaults (0.05% fee, 0.02% slippage, matching
`app.execution.paper_broker`), $10,000 fresh balance per period. Read-only:
no orders placed, no writes to the trades DB, `backend/paper_validation.db`
untouched.

**Delay gate** (`--delay-check`, Milestone 18a): re-runs the SAME
already-fetched candles through the identical config at
`entry_delay_candles=0` (baseline) and `entry_delay_candles=1`, then
compares profit factors. PASS requires PF retention ≥ 0.5 and no
profit→loss sign flip. Note the severity framing in section 4's caveat: on
this 15m anchor, 1 candle of delay = **15 minutes**, a harsher test than
the 5-minute delay `docs/ROBUSTNESS_REPORT.md` test 2 applied.

**Pre-declared configurations** (from `docs/RESEARCH_ROUND_1.md` section
4a's 1.5×–3× ATR literature convention — declared before any run, no
further tuning permitted this round):

1. **baseline** — no `--min-stop-atr` (floor disabled, production behavior)
2. **`--min-stop-atr 1.5`**
3. **`--min-stop-atr 2.0`**

**Evidence-based early stop — config 3 was deliberately NOT run.** CTO
decision after configs 1 and 2 completed, per the house "don't burn compute
on clearly dead configs" discipline (`docs/EXPERIMENTAL_STRATEGY_EVALUATION.md`
section 4 precedent): the 1.5× floor moved PF retention only 0.023 → 0.079
(criterion: ≥ 0.5) while still sign-flipping under delay AND breaking
walk-forward consistency (6/6 profitable periods → 3/6). A 2.0× floor — a
strictly more aggressive version of the same signal-rejection mechanism,
which at 1.5× already cut the trade count roughly in half — has no
plausible path from 0.079 to the 0.5 retention criterion while
simultaneously repairing the profitability damage the weaker floor caused.
This stop decision is documented here explicitly rather than smoothed over;
its consequence (the 2.0× value is formally untested) is listed in the
caveats.

**Rejected-signal counts**: the run output does NOT print how many signals
the floor rejected — the honest observable is the trade-count drop
(111 → 60, a 46% reduction), which is an effect of rejection but not a
direct count. Recorded as a reporting gap, not inferred.

## 2. Results

### Headline table

| Config | Trades | Win rate | Total PnL (6 periods) | Profitable periods | Worst-period max DD | Walk-forward | Baseline PF | Delayed PF | PF retention (≥0.5) | Sign flip | Delay gate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **baseline** (floor off) | 111 | 75.68% (84/111) | **+$3,400.62** | 6/6 | 1.64% | **PASSED** | 5.024 | 0.117 | 0.023 | **YES** | **FAILED** |
| `--min-stop-atr 1.5` | 60 | 56.67% (34/60)* | +$1,113.35 | 3/6 | 1.57% | **FAILED** | 2.346 | 0.184 | 0.079 | **YES** | **FAILED** |
| `--min-stop-atr 2.0` | — | — | — | — | — | not run | — | — | — | — | not run (early stop, section 1) |

\* Aggregate win rate for the 1.5× run is derived from the per-period log
lines (10+0+1+6+1+16 wins = 34 of 60); the log prints win rate per period,
not in aggregate. All other numbers are direct transcriptions.

Delay-gate detail (both from the combined gate summary in each log):

| Config | Baseline trades | Delayed trades | Combined gate (WF + delay) |
|---|---|---|---|
| baseline | 111 | 90 | walk-forward PASSED, delay FAILED → **OVERALL FAILED** |
| 1.5× | 60 | 57 | walk-forward FAILED, delay FAILED → **OVERALL FAILED** |

### Per-period detail

| Config | P1 (01/03–02/03) | P2 (02/03–03/06) | P3 (03/07–04/07) | P4 (04/07–05/08) | P5 (05/08–06/08) | P6 (06/08–07/09) |
|---|---|---|---|---|---|---|
| baseline | 17 tr, 94.12% WR, +$831.29, 0.35% DD | 20 tr, 60.00% WR, +$342.87, 1.16% DD | 8 tr, 62.50% WR, +$155.82, 0.74% DD | 21 tr, 95.24% WR, +$995.61, 0.33% DD | 17 tr, 64.71% WR, +$325.91, 0.76% DD | 28 tr, 71.43% WR, +$749.13, 1.64% DD |
| 1.5× | 13 tr, 76.92% WR, +$464.76, 0.55% DD | 5 tr, 0.00% WR, -$135.41, 1.35% DD | 4 tr, 25.00% WR, -$28.17, 0.84% DD | 11 tr, 54.55% WR, +$147.97, 0.74% DD | 6 tr, 16.67% WR, -$107.05, 1.57% DD | 21 tr, 76.19% WR, +$771.24, 0.35% DD |

Walk-forward detail:

| Config | Profitable ratio (≥66%) | Max losing streak (≤2) | First-half avg PnL | Second-half avg PnL | Degrading trend | Verdict |
|---|---|---|---|---|---|---|
| baseline | 100.0% | 0 | $443.33 | $690.21 | no | PASSED |
| 1.5× | 50.0% | 2 (at the criterion) | $100.39 | $270.72 | no | FAILED |

### Wall-clock timing (evidence for the performance backlog)

| Run | Start → end | Duration |
|---|---|---|
| baseline | 2026-07-16 21:54 → 2026-07-17 00:59 | ~3 h 05 m |
| 1.5× | 2026-07-17 01:16:20 → 02:33:33 | ~1 h 17 m |

Both far exceeded the ~5–15 min/config estimate. `--delay-check`
triples the simulation work (three full engine passes over 18,000 candles),
and the 1.5× run — with roughly half the trades to manage — ran ~2.4×
faster than baseline, suggesting runtime scales substantially with trade
management, not just candle count. Operational note: a first baseline
attempt (launched ~20:43 as a harness background task) was killed by the
task runner after ~1 h with no output; the successful runs were launched as
detached OS processes. Recorded for the timing round; not a strategy issue.

## 3. THE HEADLINE FINDING: the Legacy production baseline itself fails the delay gate

This round's most important result is not about the ATR floor at all.

**The Legacy production configuration — 6/6 profitable periods,
walk-forward PASSED, the platform's reference strategy — collapses under a
single candle of execution delay on this window: PF 5.024 → 0.117, PF
retention 0.023, profit→loss sign flip, DELAY-CHECK GATE FAILED.** With
delay, 21 of 111 trades (19%) don't fill at all, and what remains loses
money outright.

This was previously unknown. `docs/ROBUSTNESS_REPORT.md` test 2 delay-tested
only the `structure_tp` candidate (PF 5.24 → 0.16 at a 5-minute delay on a
5m timeframe) and attributed the fragility to that candidate's specific
0.17–0.23%-of-price stops. This round is the first time the delay gate
(built in Milestone 18a precisely to make that check cheap and repeatable)
has been run against Legacy itself — and Legacy fails it just as badly.

**Severity caveat, stated plainly**: this anchor is a 15m timeframe, so 1
candle of delay = **15 minutes** of simulated latency — three times harsher
than the 5-minute delay that killed `structure_tp`. A 15-minute execution
delay is a pessimistic model for an automated system; this result does NOT
mean Legacy loses money at realistic (seconds-scale) latency. What it does
mean cannot be softened: Legacy's backtested edge on this window is
entirely concentrated inside a sub-15-minute execution window.

**Implications**:

- **Delay fragility is a strategy-family property on this window, not a
  defect of one candidate.** Both the killed `structure_tp` candidate and
  production Legacy — different exit models, different stop profiles — show
  the same catastrophic delay collapse. The root cause identified in
  `docs/ROBUSTNESS_REPORT.md` (stops/targets tight relative to short-horizon
  price movement) evidently characterizes the shared entry pipeline, not
  the one configuration it was diagnosed on.
- **Phase-1 gate #4 (`docs/ADAPTIVE_ARCHITECTURE.md`, small live
  validation) must require verified low-latency execution** — measured
  signal-to-fill latency, not assumed — before any live capital decision
  leans on backtest or paper numbers from this family. Paper-trading fills
  that ignore latency will systematically overstate this strategy's live
  performance (consistent with `docs/RESEARCH_ROUND_1.md` #2's
  shadow-fill findings).
- The finer delay-granularity question (where between 0 and 15 minutes the
  edge actually dies) is measurable on a smaller-timeframe anchor and is a
  natural follow-up round; this round cannot answer it.

## 4. Verdict on the ATR floor — REJECTED (house keep-rule discipline)

The keep-rule set for this round: the floor earns a KEEP only if it
**materially improves PF retention / removes the sign flip AND does not
materially degrade Net Profit / PF / worst-period drawdown**.

Measured against that rule, the 1.5× floor:

- **Did not fix delay robustness.** PF retention 0.023 → 0.079 — a
  nominal tripling that is still 6× below the 0.5 criterion — and the
  profit→loss sign flip REMAINS (delayed PF 0.184, i.e. delayed trading
  still loses roughly $5 for every $1 won). The gate verdict is FAILED
  either way. This is not a material improvement; it is a slightly
  different flavor of catastrophic.
- **Materially degraded everything the keep-rule protects.** Net profit
  -67% (+$3,400.62 → +$1,113.35); zero-delay PF 5.024 → 2.346 (-53%);
  profitable periods 6/6 → 3/6; walk-forward PASSED → FAILED (50%
  profitable ratio vs. ≥66% required, losing streak of 2 sitting exactly
  at the ≤2 limit). Only worst-period drawdown is not degraded (1.64% →
  1.57%, essentially unchanged — with 46% fewer trades there is simply
  less activity to draw down).
- **"Improved delay robustness" vs. "just trades less" — it is the
  latter.** The floor's entire observable effect is rejecting ~46% of
  signals (111 → 60 trades). The surviving trades still sign-flip under
  delay, so the floor did not select FOR delay-robust trades — it merely
  thinned out a fragile population, discarding disproportionately many of
  the trades that made the baseline profitable (three periods flipped from
  profit to loss, including a 0%-win-rate period 2). The mechanism
  hypothesized in `docs/RESEARCH_ROUND_1.md` #2 — that wider ATR-scaled
  stops would survive one candle of adverse movement — is falsified on
  this evidence: whatever fills the delayed run takes still lose.

**VERDICT: the ATR stop-distance floor is REJECTED as a delay-robustness
fix on this evidence. `MIN_STOP_ATR_MULT` stays 0.0 (disabled) everywhere.
Do not enable it in paper trading; do not recommend it for promotion.**

Per `docs/RESEARCH_ROUND_1.md` section 4c's own falsifiability framing:
this is the negative result that section said would be "worth recording,
not something to quietly adjust the threshold to force a pass." Recorded.

## 5. Conclusion — may MIN_STOP_ATR_MULT be recommended for paper trading?

**No.** On the only evidence collected (one asset, one 6-month window), the
floor fails both halves of the keep-rule simultaneously: it does not repair
the delay fragility it was designed to fix, and it destroys the baseline's
walk-forward consistency in the process.

Had the result been positive, promotion would still have required
cross-asset (ETH at minimum) and cross-year (`--end-date` into a different
macro regime) confirmation plus an out-of-sample hold-out, per the
precedent in `docs/EXPERIMENTAL_STRATEGY_EVALUATION.md` section 4 /
`docs/ADAPTIVE_ARCHITECTURE.md` section 4.3. With a negative result on the
home anchor — the asset/window this strategy family is strongest on —
extending this specific floor to more assets/years would be spending
compute to re-confirm a rejection, and is not recommended. Future work
should target the actual finding of this round (section 3): the entry
pipeline's shared delay fragility, and measured-latency requirements for
Phase-1 gate #4.

## 6. Caveats

- **One asset, one window**: BTCUSDT only, 2026-01-03 → 2026-07-09, 15m.
  No claim about other assets, timeframes, or regimes. A floor that fails
  here could in principle behave differently elsewhere — but this is the
  window where the problem it targets was diagnosed, so failing here is
  decisive for THIS enablement decision.
- **15-minute delay granularity**: the delay gate's 1 candle equals 15
  minutes on this anchor — a deliberately harsh latency model (3× the
  5-minute delay of `docs/ROBUSTNESS_REPORT.md` test 2). The gate cannot
  resolve where between 0 and 15 minutes the edge dies; the headline
  finding should be read as "the edge lives inside a sub-15-minute
  window," not "Legacy fails at realistic seconds-scale latency."
- **Config 3 (2.0×) was not run** (section 1's early-stop decision). The
  rejection verdict rests on the 1.5× evidence plus the monotonicity
  argument that a stricter floor rejects strictly more signals. If the
  floor is ever revisited, 2.0× remains formally untested — but any
  revisit must first explain why more of the same mechanism would reverse,
  rather than deepen, the 1.5× result.
- **In-sample**: all 6 periods served as walk-forward evidence with no
  hold-out, matching `docs/EXPERIMENTAL_STRATEGY_EVALUATION.md`'s round-1
  methodology. Immaterial to a rejection (a config that fails in-sample
  cannot be rescued by out-of-sample data), but noted for consistency.
- **Rejected-signal counts are not printed** by the current run output;
  the 111 → 60 trade drop is the observable proxy. If a future round needs
  the exact rejection count, that is a (small) instrumentation gap in
  `run_backtest.py`/`RiskManager`, noted here rather than inferred.
- **Derived number disclosure**: the 1.5× aggregate win rate (56.67%) is
  computed from the six per-period win rates and trade counts in the log;
  every other number is a direct transcription from
  `scripts/reports/eval_m20_baseline.log` / `eval_m20_atr15.log` (kept on
  disk with the per-period reports/CSVs, `eval_m20_*`).
