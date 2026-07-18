# H5 — Session-Conditional Position Sizing, Step 0 Grounding Check Results — Milestone 29

Evaluation deliverable (2026-07-19). This closes out `docs/HYPOTHESES_ROUND_1.md`
section 6 (H5)'s pre-registered **Step 0 gate** — the precondition check
declared before any `session_risk_scalar` sizing code was written. New
analysis-only harness `scripts/research_h5_step0_session_grounding.py`
(+ `backend/tests/test_research_h5_step0_session_grounding.py`, 8 tests)
was implemented and verified this round. `RiskManager.evaluate()`'s live
sequential-approval logic and `scripts/run_paper.py` are untouched — this
harness buckets `BacktestEngine`'s already-produced trade output
(`opened_at` timestamps) by UTC entry hour; it adds no new detector, no
new engine parameter, no new CLI flag. Full suite: 756/756 passed (748
prior + 8 new), 0 failures. Every number below is transcribed from
`scripts/reports/research_h5_step0_session_grounding.json`.

## 1. Purpose and methodology

**The gap this closes**: `docs/HYPOTHESES_ROUND_1.md` section 6 disclosed
a grounding gap in H5 that its original 2026-07-17 ranking-table entry
did not surface — H5's sole motivating evidence, `docs/ROBUSTNESS_REPORT.md`
Test 6 (Asian PF 4.65 > London PF 2.41, n=41/19, pooled across 2 years),
was measured on BTCUSDT **5-minute** timeframe against the `structure_tp`
candidate, not the BTCUSDT **15-minute** Legacy default-exit candidate
H5's proposed `session_risk_scalar` would actually size. Step 0 exists to
check whether that gradient replicates on the correct candidate/timeframe
BEFORE any sizing mechanism is built — per the hypothesis's own
pre-registered text, a REJECT here ends H5 without Step 1 (implementing
`session_risk_scalar`/`--session-scaled-sizing`) ever being written.

**New instrumentation** (analysis-only, reuses `BacktestEngine` and
`run_backtest()` completely unchanged — no `vol_scaled_sizing`-style new
parameter of any kind): `scripts/research_h5_step0_session_grounding.py`
runs the plain, no-kwargs Legacy baseline (byte-identical to the
already-published baseline in `docs/LEGACY_DELAY_ROBUSTNESS.md`) for each
anchor, then buckets the resulting trades by entry-candle UTC hour into
the same three windows Test 6 used (Asian 00:00–08:00, London
08:00–16:00, NY/other 16:00–24:00 — the first two already-disclosed
constants from `backend/app/strategy/session_liquidity.py`/
`signal_engine.py`'s `_SESSION_WINDOWS`, the third Test 6's own residual
bucket, not a new detector) and computes Profit Factor per bucket.

**Anchor (identical across all three years, matching this document's
established 3-anchor standard)**: `--symbol BTCUSDT --timeframe 15m
--candles 3000 --periods 6`, varying only the end-date (`2026-07-10`,
`2025-07-10`, `2024-07-10`) — no `use_structure_tp`, no other opt-in
flags, the plain Legacy default-exit path.

**Baseline reproduction check (trust the harness before trusting its
new numbers)**: total trade counts this run produced — 111 (2026), 65
(2025), 73 (2024) — match the already-published Legacy baseline exactly
(`docs/LEGACY_DELAY_ROBUSTNESS.md` §7: 111 trades 2026, 65 trades 2025;
`docs/H2_LIMIT_ENTRY_RESULTS.md`'s Legacy comparison column: 73–77 trades
2024). Confirms this harness's plain run replays the identical baseline
every other H1–H4 result in this evidence base already cites, before any
new session-bucketing logic is trusted.

## 2. Results, all three anchors

| Anchor | Total trades | Asian N / PF | London N / PF | NY/other N / PF | Gradient holds (Asian PF > London PF)? | Sample floor met (both ≥10)? |
|---|---|---|---|---|---|---|
| 2026-07-10 | 111 | 71 / 3.565 | 24 / 5.303 | 16 / 10.488 | **FALSE** | true |
| 2025-07-10 | 65 | 42 / 2.690 | 17 / 4.451 | 6 / inf | **FALSE** | true |
| 2024-07-10 | 73 | 47 / 3.916 | 20 / 2.753 | 6 / 1.544 | **TRUE** | true |

Net Profit by bucket (context, not a gate criterion): 2026 — Asian
+$1,921.07, London +$801.96, NY/other +$677.59; 2025 — Asian +$905.68,
London +$518.97, NY/other +$289.90; 2024 — Asian +$1,324.78, London
+$427.97, NY/other +$55.00. Asian dominates trade VOLUME in every year
(consistent with Test 6's own observation on the unrelated
candidate/timeframe), but that is not what the pre-registered gate
tests — the gate tests PF direction, not volume.

## 3. Step-0 gate verdict — applied literally

Quoting `docs/HYPOTHESES_ROUND_1.md` section 6's Step-0 gate verbatim:

> **Step-0 gate (declared now)**: H5's mechanism proceeds to Step 1 only
> if Legacy/15m shows the SAME qualitative gradient direction Test 6
> found (Asian PF > London PF) in at least 2 of the 3 tested years, AND
> at least the Asian and London buckets individually reach n≥10 trades in
> the year(s) counted toward that check... If this gate fails, H5 is
> REJECTED at step 0 without building `session_risk_scalar` at all.

**Applying the rule across all three anchors**: the sample floor (n≥10 on
both Asian and London) is met in all three years, so no year is
disqualified on sample size — but the gradient direction itself (Asian PF
> London PF) holds in only **1 of 3 years** (2024). In both 2026 and 2025
— including the year with the LARGER combined trade count (2026, 111
trades, the single most-evidenced anchor in this platform's history) —
**London's PF exceeds Asian's**, the opposite of Test 6's own finding.
NY/other's PF is the highest of all three buckets in 2026 and 2025 (and
is `inf` in 2025, a small-n=6 result — exactly the kind of number
`docs/ROBUSTNESS_REPORT.md` itself already disclosed as probable noise
for this bucket, now reproduced independently on a different
candidate/timeframe).

**VERDICT: REJECT at Step 0.** Gradient direction clears the required
2-of-3 threshold in exactly 1 of 3 years — below the pre-registered bar.
Per H5's own text, this REJECTS the hypothesis outright; `session_risk_scalar`
and `--session-scaled-sizing` are not implemented, and H5's Step 1 (the
actual sizing-mechanism test) does not run.

## 4. The substantive finding: Test 6's session gradient does not transfer across candidate/timeframe

This is a cleaner, more informative result than "H5 failed" — it is a
direct, disclosed confirmation of the grounding gap section 6 flagged
before this run: **a session-quality gradient measured on one
candidate/timeframe (BTCUSDT 5m, `structure_tp` exits) does not carry
over to a different candidate/timeframe (BTCUSDT 15m, Legacy default
exits)**, even on the same asset and the same UTC session-window
convention. The two candidates' actual session ranking INVERTS in 2 of 3
years (London beats Asian on 15m/Legacy where Asian beat London on
5m/`structure_tp`). This is a genuinely new, standalone finding for this
platform's evidence base, independent of H5's own REJECT: session-quality
characterizations are not transferable across a strategy's exit-logic
family or timeframe without being re-verified on the actual candidate
being sized — a caveat any future hypothesis wanting to condition on
Test 6's numbers should carry forward explicitly, not assume.

## 5. Promotion path

**NONE — this was a REJECT at the precondition stage.** Per H5's own
pre-registered text, Step 1 (`session_risk_scalar` implementation, the
keep-rule with its drawdown/Net-Profit/delay-gate conditions) never runs
when Step 0 fails — there is no partial credit for a mechanism whose
grounding did not replicate on the candidate it would size.

**Legacy's live/paper trading behavior is completely unchanged by this
milestone.** 100% backtest-only, read-only research round:
`RiskManager.evaluate()`, `scripts/run_paper.py`, and `BacktestEngine`
internals are all byte-for-byte unchanged. No orders were placed; no
writes to `backend/paper_validation.db` occurred; no new `BacktestEngine`
parameter or CLI flag was added (unlike H1/H3/H4's harnesses, this one
needed none).

## 6. Caveats

- **One asset (BTCUSDT), one timeframe (15m), three anchors (2024, 2025,
  2026)** — matching this document's standard 3-anchor set. Not
  cross-asset checked; per this project's own standing discipline this
  would not have mattered for a REJECT even if it were.
- **This REJECT is specific to Legacy's own default-exit candidate at
  15m.** It does not re-test whether Test 6's original gradient still
  holds on the ORIGINAL candidate/timeframe (BTCUSDT 5m, `structure_tp`)
  — that original finding is not disputed or re-run here, only shown not
  to transfer to a different candidate.
- **The n≥10 sample floor is deliberately lower than H1/H3's n≥20
  promotion-gate convention**, by design (a precondition check, not a
  promotion gate, per section 6's own text) — a future re-read of this
  result should not conflate the two floors.
- **No code changed production behavior.** This is a read-only evidence
  document; `scripts/research_h5_step0_session_grounding.py` is a new
  research-only script, never imported by any production or paper-trading
  path.
