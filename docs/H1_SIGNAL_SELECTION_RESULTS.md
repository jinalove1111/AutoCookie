# H1 — Quality-Ranked Signal Selection Results — Milestone 26

Evaluation Agent deliverable (2026-07-18), CTO directive. This closes out
`docs/HYPOTHESES_ROUND_1.md` section 2 (H1): the pre-registered
chronological-FIFO-vs-quality-ranked signal selection comparison, holding
`MAX_TRADES_PER_DAY` fixed at 2 throughout. New research-only harness
`scripts/research_signal_selection.py` (+
`backend/tests/test_research_signal_selection.py`, 15 tests) was
implemented and verified by a prior agent; this round runs the
pre-registered configuration on both standard anchors and applies the
pre-registered keep-rule. `RiskManager.evaluate()`'s live sequential-
approval logic is untouched — this harness re-batches and re-ranks
signals for research purposes only, mirroring `BacktestEngine`'s existing
fee/slippage/fill/PnL mechanics unchanged. Every number below is
transcribed from `scripts/reports/research_signal_selection.json`. Full
suite: 716/716 passed (701 prior + 15 new), 0 failures.

## 1. Purpose and methodology

**The gap this closes**: `docs/LEGACY_DELAY_ROBUSTNESS.md` §2 (Milestone
23 instrumentation) measured that Legacy's `RiskManager.evaluate()`
rejects the overwhelming majority of its own raw signal stream purely on
`MAX_TRADES_PER_DAY 2 reached` — 92.5% in 2025, 89.1% in 2024, both years
with FIFO (chronological arrival-order) approval. `ENGINEERING_DECISIONS.md`
#62 records this as a real, disclosed finding and explicitly does NOT act
on it, since `MAX_TRADES_PER_DAY` is a risk-limit constant, not a
signal-quality parameter, and changing it is operator-gated territory. H1
asks a narrower, safer question: **holding the cap fixed at 2, does
selecting the two highest-QUALITY signals of the day (instead of the
first two chronologically) improve expectancy?**

**New instrumentation** (research-only, does not touch `RiskManager`'s
live sequential-approval logic): `scripts/research_signal_selection.py`
collects every candidate signal generated per simulated trading day,
scores each by a disclosed-not-tuned formula (`rr` = `TradeSignal.rr`
alone; `rr_confluence` = `rr + confluence_count`, both declared in
`docs/HYPOTHESES_ROUND_1.md` §2 before any run), and replays execution
using only the top-`MAX_TRADES_PER_DAY` signals per day by score instead
of by arrival order. All downstream mechanics (fees, slippage, fills,
PnL) reuse `BacktestEngine` unchanged.

**Anchor (identical across both years, three variants each)**:
`--symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6
--walk-forward`, varying only `--end-date` (`2026-07-10`, `2025-07-10`)
and the selection variant (`chronological` baseline, `rr`,
`rr_confluence`).

**Baseline reproduction check** (comparability confirmed before trusting
the comparison, per this project's standing discipline — decisions #14/
#15): the `chronological` variant's Net Profit, trade count, profitable-
period count, and walk-forward outcome matched the already-documented
FIFO baseline exactly in both anchors — 2025: $1,714.56 to the cent,
matching `docs/LEGACY_DELAY_ROBUSTNESS.md`; 2026: $3,400.62, matching
`docs/ATR_FLOOR_EVALUATION.md`.

**One disclosed discrepancy, not root-caused this round**: this harness's
own Profit Factor for the `chronological` variant (4.378 in 2026, 3.498
in 2025) is consistently LOWER than the previously-published baseline PF
for the same runs (5.024 in 2026, 4.593 in 2025), despite identical Net
Profit, trade count, and walk-forward outcome. The gap runs the same
direction in both anchors, pointing to a PF-aggregation methodology
difference in the new harness (e.g. possibly per-period-averaged vs.
pooled gross-profit/gross-loss) rather than a behavioral difference in
`BacktestEngine` — every other figure matches byte-for-byte. This does
NOT affect this round's verdict (the deciding metric is Net Profit, which
reproduced the baseline exactly — see section 3), but is flagged as an
open follow-up item that should be resolved before this specific harness
is reused for a future hypothesis round. See section 6.

## 2. Results, both anchors

**2026 anchor** (`--end-date 2026-07-10`):

| Variant | Net Profit | Profit Factor | Trades | Profitable periods | Walk-forward |
|---|---|---|---|---|---|
| chronological (baseline) | $3,400.6210 | 4.377805 | 111 | 6/6 | PASSED |
| rr | $2,579.9927 | 4.662186 | 82 | 6/6 | PASSED |
| rr_confluence | $1,737.1609 | 2.883269 | 77 | 5/6 | PASSED (ratio 0.8333, 1 losing streak) |

**2025 anchor** (`--end-date 2025-07-10`):

| Variant | Net Profit | Profit Factor | Trades | Profitable periods | Walk-forward |
|---|---|---|---|---|---|
| chronological (baseline) | $1,714.5596 | 3.497933 | 65 | 6/6 | FAILED (pre-existing, documented degradation) |
| rr | $1,644.2028 | 8.335659 | 43 | 6/6 | PASSED |
| rr_confluence | $968.0440 | 2.707848 | 46 | 5/6 | FAILED (degradation) |

**Deltas (ranked variant vs. chronological baseline, relative)**:

| Year | Variant | Net Profit Δ | Profit Factor Δ | Trade count Δ |
|---|---|---|---|---|
| 2026 | rr | -24.13% | +6.53% | -26.13% (111→82) |
| 2026 | rr_confluence | -48.91% | -34.13% | -30.63% (111→77) |
| 2025 | rr | -4.10% | +138.32% | -33.85% (65→43) |
| 2025 | rr_confluence | -43.55% | -22.60% | -29.23% (65→46) |

## 3. Keep-rule verdict — applied literally, per variant, both anchors

Quoting `docs/HYPOTHESES_ROUND_1.md` section 2's keep-rule verbatim:

> **Keep-rule (declared now)**: KEEP (promote to further validation, NOT
> to production/paper) only if a ranked variant **beats the chronological
> baseline on Net Profit AND Profit Factor in BOTH the 2026 and 2025
> anchors**, AND does not newly fail walk-forward relative to the
> baseline's own result. A ranked variant that wins one year and loses
> the other, or wins on PF but not Net Profit, is REJECT — same
> discipline `docs/PROFITABILITY_EXPERIMENT_REPORT.md` §13.1 applied to
> XRP's tied drawdown and §14 applied to SOL's mixed cross-year result.

**Applying the rule to `rr`**: wins Profit Factor in BOTH anchors (+6.5%
in 2026, +138.3% in 2025) but LOSES Net Profit in BOTH anchors (-24.1% in
2026, -4.1% in 2025). Disqualified directly by the rule's own explicit
"wins on PF but not Net Profit, is REJECT" clause — independently true in
both years, not a marginal or ambiguous case.

**Applying the rule to `rr_confluence`**: loses BOTH Net Profit and
Profit Factor in BOTH anchors outright. No path to KEEP under any reading
of the rule.

**VERDICT: REJECT for both variants.** Not ambiguous, not MIXED (compare
Milestone 25's H4 verdict, which genuinely did not resolve to one branch)
— this is a clean negative result on the rule exactly as pre-registered,
with no bullet requiring interpretation or a materiality band to weigh.

## 4. Mechanism note: why quality-ranking traded away throughput

Both ranked variants realize markedly fewer trades than the chronological
baseline under the SAME fixed `MAX_TRADES_PER_DAY=2` cap — 2026: `rr` 82
/ `rr_confluence` 77 vs. baseline 111; 2025: `rr` 43 / `rr_confluence` 46
vs. baseline 65. This is a disclosed structural property of the harness
(documented by Engineering during implementation): a day's top-scored
candidates can cluster in time such that after the first fills, the
second-ranked candidate's window overlaps the still-open first trade and
is skipped rather than force-opened concurrently, whereas chronological
FIFO naturally spreads fills as signals arrive live rather than
retrospectively picking the best two of a whole day's supply. Quality-
ranking traded away raw trade throughput for higher per-trade selectivity
(visible in the PF-per-trade improvement, most sharply in 2025's `rr` PF
+138%) — but that throughput loss cost more aggregate Net Profit than the
per-trade quality gain recovered, in both tested years, without
exception.

**Reading**: on this platform, Legacy's edge scales more with trade
FREQUENCY under the fixed cap than with per-trade selectivity. This
directly reinforces two things already on record:

1. **`docs/strategy_spec.md` §6's prior finding that
   `require_full_confluence=True` does NOT reliably produce
   higher-quality trades** (cited as prior art in
   `docs/HYPOTHESES_ROUND_1.md` §2, which H1 had to survive contact with
   — it did not survive). This is now a second data point in the same
   direction: `rr_confluence` performed WORSE than plain `rr` on both
   Net Profit and Profit Factor in both years, meaning adding
   confluence-count to the score actively hurt rather than helped.
2. **The already-disclosed, deliberately NOT-acted-on 89-92%
   signal-rejection-by-cap finding** (`ENGINEERING_DECISIONS.md` #62).
   H1 tested whether better SELECTION within the fixed cap could capture
   some of that discarded opportunity without touching the cap itself,
   and found it cannot — at least not via `rr` or `rr+confluence_count`
   scoring. The opportunity appears to require trade THROUGHPUT (i.e.,
   raising the cap itself), which remains explicitly operator-gated
   territory (decision #62's own boundary), not something this result
   argues for changing.

## 5. Secondary observation, not a KEEP driver

`rr`'s 2025 walk-forward PASSED where the chronological baseline's is a
known, already-documented FAILURE (degradation, `docs/PROJECT_STATUS.md`
milestone 25 / `docs/LEGACY_DELAY_ROBUSTNESS.md`). This is an interesting
directional note worth recording, but it does not rescue the verdict —
Net Profit already disqualifies `rr` under the pre-registered rule, and
the rule is explicit that Net Profit AND Profit Factor must both win;
walk-forward is only a non-regression check in this rule's own text, not
a substitute pass condition.

## 6. Open follow-up: PF-aggregation methodology discrepancy

As disclosed in section 1: `scripts/research_signal_selection.py`'s own
computed Profit Factor for the `chronological` (baseline-reproducing)
variant is consistently lower than the previously-published baseline PF
for the identical run — 2026: 4.378 (harness) vs. 5.024 (published); 2025:
3.498 (harness) vs. 4.593 (published). Net Profit, trade count,
profitable-period count, and walk-forward outcome all matched byte-for-
byte in both years, isolating the discrepancy to PF computation
specifically, not to any behavioral difference in trade generation or
`BacktestEngine`. Plausible cause (not verified this round): a
per-period-averaged PF vs. a pooled-gross-profit/gross-loss PF — the two
formulas diverge whenever period-level gross profit/loss ratios vary,
which they do across this project's 6-period splits. **This does not
affect this round's REJECT verdict** (Net Profit is the metric that
matters for section 3's determination, and it reproduced exactly), but it
IS flagged as a standing follow-up: this harness's PF numbers should not
be cited as directly comparable to `run_backtest.py`'s own PF output
until root-caused, and the discrepancy should be resolved before
`scripts/research_signal_selection.py` is reused for a future hypothesis
round.

## 7. Promotion path

**NONE — this was a REJECT.** Per H1's own pre-registered promotion-path
text (`docs/HYPOTHESES_ROUND_1.md` §2, "Promotion path if KEEP"): even a
KEEP would not have been a promotion by itself — any live/paper change to
how signals are selected within the day is a risk-and-behavior change
(live trading sees signals stream in real time and would need a genuine
intraday deferred-decision architecture to "wait and pick best-of-day"),
squarely operator-gated, same category as `MAX_TRADES_PER_DAY` itself per
decision #62. This is moot here since the result is REJECT.

**Legacy's live/paper trading behavior is completely unchanged by this
milestone.** This was a 100% backtest-only, read-only research round:
`RiskManager.evaluate()`, `scripts/run_paper.py`, and `BacktestEngine`
internals are all byte-for-byte unchanged, verified by Engineering during
implementation. No orders were placed; no writes to
`backend/paper_validation.db` occurred.

## 8. Caveats

- **One asset (BTCUSDT), one timeframe (15m), two Jan-Jul windows
  (2025, 2026)** — same standing caveat as every other document in this
  evidence chain. Not cross-asset checked; 2024 was not run for this
  hypothesis (unlike H4's 3-year anchor set, H1's pre-registered
  experiment in `docs/HYPOTHESES_ROUND_1.md` §2 specifies only the two
  standard anchors).
- **Two scoring variants only** (`rr`, `rr_confluence`), both
  disclosed-not-tuned per the pre-registration — no other scoring
  formula (e.g. distance-to-structure-target, HTF-bias alignment weight)
  was tested this round. A different, untested scoring function remains
  a theoretical possibility not ruled out by this REJECT, though the
  mechanism note in section 4 (throughput loss under the fixed cap,
  regardless of which two signals are chosen) suggests any ranking-based
  approach faces the same structural tension.
- **The PF-aggregation discrepancy (section 6) is disclosed, not
  root-caused.** Net Profit is unaffected and is the deciding metric for
  this round's verdict, but a future round reusing this harness should
  resolve the discrepancy before trusting its PF output directly.
- **No code was touched, no live/paper system was modified.** This is a
  read-only evidence document per the department's scope — the
  mechanism note in section 4 is a finding, not a change; the
  `MAX_TRADES_PER_DAY` cap itself remains untouched and out of scope,
  exactly as H1's own design required (`docs/HYPOTHESES_ROUND_1.md` §2's
  "Rejected ideas" section, "Raising `MAX_TRADES_PER_DAY` directly").
