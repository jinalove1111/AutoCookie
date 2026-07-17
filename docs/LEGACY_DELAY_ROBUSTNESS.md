# Legacy Delay Robustness — Cross-Year Evidence Round (Milestone 24 candidate)

Backtest Agent deliverable (2026-07-17), CTO directive. **The question**:
`docs/ATR_FLOOR_EVALUATION.md` section 3 found that the Legacy production
baseline itself fails the 1-candle (15-minute) execution-delay gate on the
standard 2026 window — PF 5.024 → 0.117, PF retention 0.023, profit→loss
sign flip. That was a single window in a single year. The house cross-year
discipline (applied to break-even, partial TP, the tuned defaults, and the
unified candidate before any of them were treated as settled) requires
testing the time axis before a finding is labeled structural. This round
answers: **is Legacy's delay fragility a structural property of the
strategy family, or a regime-specific artifact of 2026 conditions?**

This is evidence collection only — one pre-declared run, no parameters
tuned, no code touched. Every number below is transcribed from the actual
run log (`scripts/reports/eval_m24_baseline_2025.log`) or cited from
`docs/ATR_FLOOR_EVALUATION.md` (the 2026 comparison row was NOT re-run;
it is quoted from the committed document, per the directive).

## 1. Methodology

**The one run**: `--symbol BTCUSDT --timeframe 15m --candles 3000
--periods 6 --end-date 2025-07-10 --walk-forward --delay-check` — the
standard 2025 anchor used by every prior cross-year round (first
introduced with `--end-date` itself, then reused for the tuned-defaults
2025 validation; see ROADMAP/CHANGELOG BTC-2025 history). 18,000 LTF
(15m) candles + 1,125 HTF (4h) candles fetched from OKX, split into 6
non-overlapping chronological periods spanning 2025-01-03 12:00 UTC
through 2025-07-09 23:45 UTC. Standard fee/slippage defaults (0.05% fee,
0.02% slippage), $10,000 fresh balance per period. Read-only: no orders,
no writes to the trades DB, `backend/paper_validation.db` untouched.

**Delay gate** (`--delay-check`, Milestone 18a): re-runs the SAME
already-fetched candles through the identical config at
`entry_delay_candles=0` vs `=1` and compares profit factors. PASS
requires PF retention ≥ 0.5 and no profit→loss sign flip. On this 15m
anchor, 1 candle of delay = **15 minutes** of simulated latency.

**Comparison row**: the 2026 numbers are the baseline row of
`docs/ATR_FLOOR_EVALUATION.md` (same command with `--end-date
2026-07-10`, run 2026-07-16/17). Identical config, identical gate,
different year — a clean two-point time axis.

**Sanity check on comparability**: this run reproduced the known
BTC-2025 baseline profile exactly — $1,714.56 total, 6/6 profitable
periods, walk-forward FAILED on the degradation criterion (second-half
avg PnL $149.39 vs first-half $422.13, 35.4% retention) — matching the
CHANGELOG's cross-year-validation round to the cent. The window and
config are therefore confirmed apples-to-apples with the existing
BTC-2025 evidence base.

**Wall time**: launched 2026-07-17 13:14:56 (local), log last write
13:26:01 — **~11 minutes** total including the OKX fetch and three full
engine passes (baseline + delayed + walk-forward accounting). The
equivalent 2026 run took ~3 h 05 m before the Milestone 22 performance
work; the ~5x-faster engine estimate was, if anything, conservative
(~17x here, though the 2025 window has far fewer trades to manage, which
`docs/ATR_FLOOR_EVALUATION.md` section 2 already identified as a major
runtime driver).

## 2. Results

### Headline: delay gate, 2026 vs 2025

| Window | Trades (Σ periods) | Total PnL | Profitable periods | Walk-forward | Baseline PF | Delayed PF | PF retention (≥0.5) | Sign flip | Delay gate |
|---|---|---|---|---|---|---|---|---|---|
| **2026** (`ATR_FLOOR_EVALUATION.md`) | 111 | +$3,400.62 | 6/6 | PASSED | 5.024 | 0.117 | 0.023 | **YES** | **FAILED** |
| **2025** (this round) | 65 | +$1,714.56 | 6/6 | FAILED (degradation)* | 4.593 | 0.068 | **0.015** | **YES** | **FAILED** |

\* The walk-forward FAIL is the pre-existing, already-documented BTC-2025
degradation (35.4% second-half retention vs ≥50% required; every period
still individually profitable) — reproduced identically here, not a new
finding of this round.

Delay-gate detail (transcribed from the gate block of the log):

| Window | Baseline trades (gate pass) | Delayed trades | Baseline PF | Delayed PF | Retention | Verdict |
|---|---|---|---|---|---|---|
| 2026 | 111 | 90 | 5.024 | 0.117 | 0.023 | FAILED |
| 2025 | 63† | 52 | 4.593 | 0.068 | 0.015 | FAILED |

† The gate's own baseline pass reports 63 trades vs the 65 summed across
the 6 independent periods — recorded as observed from the log, not
reconciled by inference (the gate runs its own pass over the window; the
2-trade difference does not affect any gate criterion, which compares
the gate's own baseline vs delayed passes).

**Combined promotion-gate summary (2025)**: walk-forward FAILED,
execution-delay gate FAILED → **OVERALL FAILED**.

### Per-period detail (2025)

| Period | Dates (UTC) | Trades | Win rate | PnL | Max DD |
|---|---|---|---|---|---|
| 1 | 01/03–02/03 | 2 | 100.00% | +$96.18 | 0.00% |
| 2 | 02/03–03/06 | 15 | 93.33% | +$718.73 | 0.37% |
| 3 | 03/07–04/07 | 14 | 78.57% | +$451.48 | 0.40% |
| 4 | 04/07–05/08 | 12 | 50.00% | +$48.65 | 0.88% |
| 5 | 05/08–06/08 | 9 | 55.56% | +$95.45 | 0.42% |
| 6 | 06/08–07/09 | 13 | 69.23% | +$304.09 | 0.61% |

Walk-forward detail (2025): profitable ratio 100.0% (≥66% ✓), max losing
streak 0 (≤2 ✓), first-half avg PnL $422.13, second-half avg PnL
$149.39, degrading trend YES → **FAILED** (matches the CHANGELOG's
documented BTC-2025 standard-scale result exactly).

### Risk-rejection summary (Milestone 23 instrumentation, first use in an evidence round)

New observability since the 2026 round — the runner now prints how many
signals the risk gate rejected and why (closing the gap recorded in
`docs/ATR_FLOOR_EVALUATION.md` section 6):

| Period | Signals | Approved | Rejected | Top reason |
|---|---|---|---|---|
| 1 | 5 | 2 | 3 | `trades_today 2 reached MAX_TRADES_PER_DAY 2` (3) |
| 2 | 227 | 15 | 212 | same (212) |
| 3 | 329 | 14 | 315 | same (315) |
| 4 | 83 | 12 | 71 | same (71) |
| 5 | 138 | 9 | 129 | same (129) |
| 6 | 87 | 13 | 74 | same (74) |
| **Σ** | **869** | **65** | **804** | `trades_today 2 reached MAX_TRADES_PER_DAY 2` (804) |

Context this adds: the 2025 window's low trade count (65 vs 111 in 2026)
is NOT a signal drought — the entry pipeline generated 869 raw signals,
and 92.5% were rejected by the `MAX_TRADES_PER_DAY` cap alone (the only
rejection reason that fired). Signal generation is clustered far more
densely than the daily cap allows. No 2026 equivalent exists (the
instrumentation postdates that run), so this is context, not a
cross-year comparison.

## 3. Verdict: STRUCTURAL

**Legacy's delay fragility is structural on the evidence collected — it
fails the delay gate in both tested years, and fails it slightly WORSE
in 2025 (retention 0.015 vs 0.023) despite 2025 being a materially
different regime.**

The two windows differ in almost every regime-relevant observable:
trade density (65 vs 111 trades), profitability ($1,714.56 vs
$3,400.62), walk-forward behavior (FAILED-degrading vs PASSED), and
per-period texture (2025 period 1 had 2 trades; 2026's quietest period
had 8). If the delay collapse were a product of 2026-specific
conditions — the tight-stop regime hypothesized when the finding was
made — a regime this different should have moved the retention number
materially toward the 0.5 criterion. Instead it moved from 0.023 to
0.015 (both catastrophic; the difference between them is noise at this
magnitude), with the same profit→loss sign flip: delayed 2025 trading
wins roughly $1 for every $15 lost (PF 0.068).

Stated per the pre-declared decision rule for this round:

- **STRUCTURAL** (fails both years) — **this is the observed outcome.**
  The edge fundamentally lives inside sub-candle (sub-15-minute)
  execution, in both a high-activity profitable-and-consistent regime
  (2026) and a low-activity degrading regime (2025).
- REGIME-DEPENDENT (passes or degrades mildly in 2025) — falsified:
  retention 0.015 is neither a pass nor mild.
- MIXED — not applicable; both windows fail decisively and in the same
  direction.

Known-context check (per the directive, respecting the BTC-2025
history): 2025's weaker baseline profile — fewer trades, smaller PnL,
the standard-scale walk-forward degradation FAIL — was all documented
BEFORE this round (CHANGELOG cross-year validation; ROADMAP backlog item
#1 on the Apr–Jun 2025 weakness) and reproduced here exactly. None of it
is new, and none of it rescues the delay result: the delay gate failed
in 2026 where everything else PASSED, and failed in 2025 where the
baseline was already softer. The fragility is present regardless of
whether the surrounding window is Legacy's best or worst documented
behavior — that is precisely what "structural" means here.

## 4. What this changes for Phase-1 gate #4

The gate #4 latency requirement (`docs/ADAPTIVE_ARCHITECTURE.md`,
hardened after `docs/ATR_FLOOR_EVALUATION.md` section 3) is already the
right requirement; this round changes its **justification wording**, not
its substance:

- The requirement note should now read: **"structural property of the
  Legacy strategy family, confirmed across two independent years (2025,
  2026) on BTCUSDT"** — not "observed in the 2026 window." The
  measured-latency requirement (verified signal-to-fill latency, not
  assumed) is not waivable by pointing at a different backtest window,
  because the fragility does not depend on the window.
- Corollary that follows from the strengthened wording: any future paper
  or live evidence for this family remains systematically overstated
  wherever fills ignore latency, in ALL regimes tested so far — the
  shadow-fill concern of `docs/RESEARCH_ROUND_1.md` #2 applies
  year-round, not conditionally.
- What this round does NOT justify: tightening gate #4 further, or
  treating Legacy as unviable. The gate measures a 15-minute delay — a
  deliberately harsh latency model. The correct response remains
  "measure real latency before trusting the edge," unchanged.

## 5. Caveats

- **One asset**: BTCUSDT only. No claim about ETH/SOL/XRP delay
  behavior; the cross-year rounds for those assets never ran
  `--delay-check`.
- **15-minute delay granularity**: 1 candle on a 15m anchor. The gate
  cannot resolve where between 0 and 15 minutes the edge dies. "The
  edge lives inside a sub-15-minute execution window in both years" is
  the defensible claim; "Legacy fails at seconds-scale latency" is not.
- **Two windows are still a small sample of regimes.** Two independent
  years, both failing decisively, is the house evidence bar for calling
  a finding cross-year robust (the same bar used for partial TP's
  -32.6%/-32.1%) — but 2024 (a genuinely third macro period, already on
  the ROADMAP backlog for other reasons) remains untested, and both
  windows are Jan–Jul halves. "Structural" here means "not explained by
  the 2026 regime," not "proven in all possible regimes."
- **Gate trade-count discrepancy**: the delay gate's own baseline pass
  reports 63 trades vs 65 summed across periods (footnote in section
  2). Recorded as observed; does not affect any gate criterion.
- **The 2026 row was not re-run** (per the directive) — it is quoted
  from `docs/ATR_FLOOR_EVALUATION.md`, whose baseline was itself
  verified byte-identical to the prior evidence base at the time.
- **Risk-rejection counts have no 2026 counterpart** (instrumentation
  is newer than that run); the section 2 rejection table contextualizes
  2025 only.

## 6. Artifacts

- Run log: `scripts/reports/eval_m24_baseline_2025.log` (source of
  every 2025 number above)
- Per-period reports/CSVs: `scripts/reports/eval_m24_baseline_2025_period{1..6}.{md,csv}`
- Comparison row source: `docs/ATR_FLOOR_EVALUATION.md` (committed,
  2026-07-17)
