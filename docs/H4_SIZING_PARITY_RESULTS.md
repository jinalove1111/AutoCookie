# H4 — Backtest/Live Position-Sizing Parity Results — Milestone 25

Evaluation Agent deliverable (2026-07-18), CTO directive. This closes out
`docs/HYPOTHESES_ROUND_1.md` section 5 (H4): the pre-registered,
three-year `--vol-scaled-sizing` comparison against the already-recorded
unscaled baselines in `docs/LEGACY_DELAY_ROBUSTNESS.md` and
`docs/ATR_FLOOR_EVALUATION.md`. No code was touched — the
`--vol-scaled-sizing` flag (Milestone 25, 78 focused tests passing) was
implemented and verified by a prior agent; this round only runs the
pre-registered configuration and applies the pre-registered keep-rule.
Every number below is transcribed from the actual run logs
(`scripts/reports/h4_vol_scaled_2026.log`, `h4_vol_scaled_2025.log`,
`h4_vol_scaled_2024.log`) or from the cited prior documents.

## 1. Purpose and methodology

**The gap this closes**: `BacktestEngine.run()` never passed a
`volatility` argument to `calculate_position_size(...)`, so every
backtest number in this platform's evidence base was computed at a
uniform 1.0x risk scalar — while live paper trading has been running
Milestone 7's `volatility_risk_scalar` (0.5x in `high_volatility`, 1.0x
otherwise) since 2026-07-15. H4 asks whether closing that gap changes
any existing headline finding.

**Anchor (identical across all six runs — three unscaled baselines
already on record, three vol-scaled runs performed this round)**:
`--symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6
--walk-forward --delay-check`, varying only `--end-date`
(`2026-07-10`, `2025-07-10`, `2024-07-10`) and the presence/absence of
`--vol-scaled-sizing`. Same 18,000 LTF (15m) + 1,125 HTF (4h) candles
per year, same 6 non-overlapping chronological periods, same fee/
slippage defaults (0.05% fee, 0.02% slippage), $10,000 fresh balance per
period. Read-only: no orders, no writes to the trades DB.

**Runs performed this round** (the 2026 comparison was already measured
and orchestrator-verified prior to this round; only 2025 and 2024 were
run here):

```
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2025-07-10 --vol-scaled-sizing --walk-forward --delay-check --output scripts/reports/h4_vol_scaled_2025.md
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2024-07-10 --vol-scaled-sizing --walk-forward --delay-check --output scripts/reports/h4_vol_scaled_2024.md
```

Both completed cleanly on the first attempt (no OKX transient failures,
no retries needed), well under the 20-minute estimate: 2025 finished in
a few minutes; 2024 (higher trade/signal density) took roughly 10-16
minutes, consistent with the ~16.5-minute 2024 wall time recorded for
the unscaled baseline in `docs/LEGACY_DELAY_ROBUSTNESS.md` §7.

**Baselines** (unscaled, `--vol-scaled-sizing` unset, already on record —
not re-run this round):

- 2026: `docs/ATR_FLOOR_EVALUATION.md` baseline row.
- 2025 and 2024: `docs/LEGACY_DELAY_ROBUSTNESS.md` §2 and §7.

## 2. Three-year comparison table

| Year | Config | Trades | Net PnL | Baseline PF (0-delay) | Worst-period max DD | Walk-forward | Delay-gate PF retention | Delay verdict |
|---|---|---|---|---|---|---|---|---|
| 2026 | Unscaled | 111 | +$3,400.62 | 5.024 | 1.64% | PASSED | 0.023 | FAILED |
| 2026 | Vol-scaled | 111 | +$2,910.07 | 5.184 | 1.42% | PASSED | 0.025 | FAILED |
| 2025 | Unscaled | 65 | +$1,714.56 | 4.593 | 0.88% | FAILED (degrading) | 0.015 | FAILED |
| 2025 | Vol-scaled | 65 | +$1,593.60 | 4.665 | 0.88% | FAILED (degrading) | 0.015 | FAILED |
| 2024 | Unscaled | 73 | +$1,807.75 | 2.959 | 1.25% | PASSED | 0.026 | FAILED |
| 2024 | Vol-scaled | 73 | +$1,764.10 | 3.095 | 1.08% | PASSED | 0.025 | FAILED |

**Deltas (vol-scaled vs. unscaled, relative)**:

| Year | Net PnL Δ | Baseline PF Δ | Worst-period max DD Δ | Trade count Δ | Delay retention Δ |
|---|---|---|---|---|---|
| 2026 | **-14.42%** | +3.18% | -13.41% (improves) | 0 (identical) | +0.002 (noise) |
| 2025 | -7.06% | +1.57% | 0.00% (unchanged) | 0 (identical) | 0.000 (unchanged) |
| 2024 | -2.42% | +4.60% | -13.60% (improves) | 0 (identical) | -0.001 (noise) |

Trade count and win/loss classification are identical between scaled and
unscaled in all three years, as expected — `--vol-scaled-sizing` only
changes position size, not entries/stops/targets/fills, so which trades
fire and whether each wins or loses is untouched. Only the currency-
denominated metrics (Net PnL, drawdown, PF) move.

### Per-period detail

**2026** (unscaled → vol-scaled max drawdown by period):
P1 0.35%→0.35%, P2 1.16%→1.16%, P3 0.74%→0.59%, P4 0.33%→0.33%, P5
0.76%→0.99%, P6 1.64%→1.42% (worst period both configs; P5 is the one
period where scaled drawdown is *worse* than unscaled — not every period
moves in the drawdown-improving direction, only the worst one net does).

**2025** (unscaled → vol-scaled max drawdown by period): P1 0.00%→0.00%,
P2 0.37%→0.37%, P3 0.40%→0.40%, P4 0.88%→0.88%, P5 0.42%→0.42%, P6
0.61%→0.46%. Only period 6 moved; the worst period (P4, 0.88%) is
byte-identical between configs.

**2024** (unscaled → vol-scaled max drawdown by period): P1 0.29%→0.14%,
P2 0.71%→0.78%, P3 0.30%→0.30%, P4 1.25%→0.92%, P5 0.56%→0.42%, P6
1.08%→1.08%. The worst period shifts from P4 (unscaled) to P6
(vol-scaled), and the new worst value (1.08%) is lower than the old worst
value (1.25%) — a genuine worst-case improvement, not just a reshuffle.

## 3. Keep-rule verdict — applied literally, per year, then in aggregate

Quoting `docs/HYPOTHESES_ROUND_1.md` section 5's keep-rule verbatim:

> - **If max drawdown improves and Net Profit/PF are materially
>   unchanged (within ~10%) in at least 2 of 3 years**: record this as a
>   confirmed, real improvement to risk-adjusted metrics consistent with
>   the external literature — and, critically, **re-open every existing
>   finding whose headline number could plausibly move**, starting with
>   the delay-gate retention figures (0.026/0.015/0.023) and the
>   walk-forward degradation checks, since those are exactly the
>   currency-sensitive metrics a sizing change could shift.
> - **If Net Profit or PF materially degrades**: this is itself
>   important — it would mean Milestone 7's disclosed-not-tuned 0.5x
>   scalar, currently live in paper trading, is costing real expectancy
>   with no compensating drawdown benefit large enough to justify it, an
>   operator-relevant finding independent of this round's original
>   purpose.
> - **If nothing moves materially in either direction**: also a valid,
>   useful result — it means the evidence base's silent 1.0x-everywhere
>   assumption was harmless in practice on this asset/window, closing the
>   gap as a documentation fix rather than a numeric one.

**Applied per year** (using the ~10% band on Net PnL/PF, and worst-period
max drawdown as the drawdown metric — the same convention
`docs/ATR_FLOOR_EVALUATION.md` §4 used):

- **2024**: drawdown improves (1.25% → 1.08%, -13.6%) AND Net PnL/PF
  materially unchanged (-2.42% / +4.60%, both within ~10%). Matches the
  first bullet's per-year pattern.
- **2025**: drawdown unchanged (0.88% → 0.88%, exactly flat) and Net
  PnL/PF materially unchanged (-7.06% / +1.57%, both within ~10%).
  Matches the third bullet's pattern — nothing moved materially in
  either direction.
- **2026**: Net PnL moves -14.42%, outside the ~10% band — a material
  degradation. (Drawdown also improves here, -13.4%, but the first
  bullet requires drawdown-improves **AND** PnL/PF-unchanged together;
  2026 fails the "unchanged" half, so it does not qualify for the first
  bullet regardless of the drawdown side.) Matches the second bullet's
  condition.

**Aggregate verdict, applying the rule's own literal thresholds**: the
first bullet's own condition is a conjunction — drawdown improves AND
Net PnL/PF unchanged, in the SAME years, at least 2 of 3 times. Checking
whether both halves actually co-occur (not just whether each half occurs
somewhere): drawdown improves in 2024 and 2026, but PnL/PF is only
"unchanged" in 2024 among those two (2026's PnL move is outside the
band) — so the conjunction holds in exactly **1 of 3 years (2024)**, not
2. **The first bullet's explicit 2-of-3 bar is not cleared.** The
"confirmed, real improvement" branch does **not** fire as an overall
verdict.

The second bullet carries no minimum-year qualifier in the text as
written, and its condition is literally met in 2026 (Net Profit -14.4%,
outside the ~10% band) — so **that branch's finding fires and must be
reported**: on this evidence, the live 0.5x volatility scalar is
measurably costing expectancy in at least one of the three tested years,
without a large enough compensating drawdown benefit in that same year
to net out as a win under the rule's own comparison. 2025 separately and
independently matches the third bullet's "nothing moves materially"
description for its own year.

**Stated plainly, the honest three-year read is MIXED** — no single one
of the three pre-registered bullets covers all three years, because the
rule was written to be applied per-year then aggregated, and the three
years did not land on the same branch. Applying it exactly as written
(not softened toward the first bullet, not ignored in favor of an
overall "average" characterization) surfaces the second bullet's
"materially degrades" reporting obligation as the operationally relevant
one, since it is the branch whose triggering condition is real
(2026, a year with no minimum-count requirement attached to it) — while
the first bullet's stronger "confirmed improvement" claim is correctly
withheld because its own 2-of-3 bar is not met.

Per the document's own framing: "There is no REJECT branch in the usual
sense — this experiment's value is in the answer, not in clearing a
promotion bar." This is reported as the honest three-year answer, not as
a pass/fail grade on the flag itself.

## 4. Operator-relevant implication

Per the keep-rule's second bullet, verbatim: this would mean **Milestone
7's disclosed-not-tuned 0.5x scalar, currently live in paper trading, is
costing real expectancy with no compensating drawdown benefit large
enough to justify it, an operator-relevant finding independent of this
round's original purpose.** The 2026 window (the platform's highest-
activity, highest-Net-Profit tested year, 111 trades) is the one where
this shows up most clearly: -14.4% Net Profit for a -13.4% relative
worst-period drawdown improvement — a trade of real dollars for a
reduction in an already-small (1.64%→1.42%) worst-case drawdown number.
2024 shows a much smaller version of the same trade-off (-2.4% PnL for
-13.6% drawdown, within the "unchanged" band). 2025 shows no version of
it at all (both metrics flat).

This document does **not** recommend changing the live 0.5x scalar —
that is squarely an operator decision, the same boundary
`ENGINEERING_DECISIONS.md` #62 draws around `MAX_TRADES_PER_DAY`. It
states the finding only: whether the current live scalar's cost is worth
its benefit is now something the operator has actual backtest evidence
to weigh, where before this round none existed.

## 5. Footnote check — do existing findings need correction?

The first keep-rule bullet's re-open instruction (delay-gate retention
figures, walk-forward degradation checks) is conditioned on its own
2-of-3-years bar being cleared, which it was not (section 3). Applying
the instruction's spirit anyway — checking honestly rather than assuming
"bar not cleared" means "nothing to check" — here is what actually moved:

**Delay-gate PF retention, unscaled → vol-scaled**:

| Year | Unscaled retention | Vol-scaled retention | Δ | Verdict change? |
|---|---|---|---|---|
| 2026 | 0.023 | 0.025 | +0.002 | No — both FAILED, both far below 0.5 |
| 2025 | 0.015 | 0.015 | 0.000 | No — both FAILED, identical |
| 2024 | 0.026 | 0.025 | -0.001 | No — both FAILED, both far below 0.5 |

All three deltas are noise at this magnitude (the 0.5 criterion is 20x
the largest observed value). The sign flip (profit→loss under delay)
is present in all six runs, scaled and unscaled alike. **No footnote
correcting `docs/LEGACY_DELAY_ROBUSTNESS.md`'s STRUCTURAL, 3-for-3 delay-
fragility verdict is warranted** — the vol-scaled re-run reproduces the
same catastrophic failure at the same magnitude in all three years. The
appropriate footnote is confirmatory, not corrective: the STRUCTURAL
verdict now holds under both the pre-Milestone-7 sizing model this
platform's evidence base used and the sizing model actually live in
paper trading.

**Walk-forward degradation checks**: no verdict changed. 2026 PASSED →
PASSED, 2025 FAILED-degrading → FAILED-degrading (same reason: second-
half PnL retention well under the 66%/degradation-free bar in both
configs), 2024 PASSED → PASSED. `docs/ATR_FLOOR_EVALUATION.md` and
`docs/LEGACY_DELAY_ROBUSTNESS.md` need no walk-forward correction
either.

**`docs/REGIME_PERFORMANCE_ANALYSIS.md` and
`docs/PROFITABILITY_EXPERIMENT_REPORT.md`**: not re-run this round (out
of scope for H4's pre-registered experiment, which only specifies the
BTCUSDT/15m/6-period anchor). Given the consistent, small-magnitude
directional pattern observed here (PF nudges up 1.6-4.6%, Net PnL nudges
down 2-14%, worst-period drawdown flat-to-improved), any headline
expectancy or regime-bucket-ranking conclusion in those documents that
rests on Net Profit margins narrower than roughly 10-15% could plausibly
flip under vol-scaled sizing and would need a targeted re-check before
being treated as final — this is flagged as a caveat, not verified here.

## 6. Caveats

- **One asset (BTCUSDT), one timeframe (15m), Jan-Jul windows only** —
  same standing caveat as every other document in this evidence chain.
  Not cross-asset or cross-timeframe checked.
- **The ~10% "materially unchanged" band is the document's own
  language, not a statistically derived confidence interval.** 2025's
  -7.06% Net PnL move and 2024's +4.60% PF move are close enough to the
  band's edge that a stricter or looser threshold could relabel either
  year; the deltas themselves (reported in section 2) are the ground
  truth, and the ~10% framing is applied exactly as the pre-registered
  document specified it, not tightened or loosened here.
- **"Worst-period max drawdown" is a single-number summary of a
  six-period run**, matching the convention `docs/ATR_FLOOR_EVALUATION.md`
  §4 used for its own keep-rule application. Section 2's per-period
  detail is included precisely because the worst-period number alone
  hides period-level reversals (e.g., 2026 P5 got worse while the
  overall worst-period number improved).
- **Trade classification (win/loss, entry/stop/target) is unchanged by
  design** — `--vol-scaled-sizing` only rescales position size, verified
  directly by the identical trade counts and per-period win rates across
  every scaled/unscaled pair in section 2. This experiment could not, by
  construction, discover a new profitable/unprofitable trade; it could
  only reveal whether the sizing gap changes currency-denominated
  metrics, which it does, modestly, in the direction described above.
- **No code was touched, no live/paper system was modified.** This is a
  read-only evidence document per the department's scope; the operator-
  relevant finding in section 4 is a finding, not a change.
