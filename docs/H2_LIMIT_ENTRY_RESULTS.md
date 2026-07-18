# H2 — Passive Limit-at-Level Entry Results — Milestone 28

Evaluation Agent deliverable (2026-07-18), CTO directive. This closes out
`docs/HYPOTHESES_ROUND_1.md` section 4 (H2): the pre-registered test of
whether a passive resting limit order at the structural entry zone
(instead of an immediate market fill) is a genuinely delay-robust
alternative entry model. Unlike H1 and H3, which were pure
analysis/aggregation layers atop already-existing, already-validated
flags, H2 required real new fill-timing logic: two new opt-in CLI flags,
`--limit-at-level` and `--limit-timeout-candles N`, wired into
`BacktestEngine.run()` and `entry_model.py` (`scripts/run_backtest.py`
exposes both). Default off, byte-identical to today's behavior when
unset, confirmed by 2 dedicated regression tests in
`backend/tests/test_backtest_engine.py`. `RiskManager.evaluate()`'s live
sequential-approval logic and `scripts/run_paper.py` are untouched. Full
suite: 748/748 passed at evaluation time (up from 739 prior), 0
failures. Every number below is transcribed from the recorded backtest
runs for this round, cross-referenced against
`docs/LEGACY_DELAY_ROBUSTNESS.md` for the Legacy baseline figures.

## 1. Purpose and methodology

**The gap this closes**: every delay-robustness fix tried on this
platform so far shares one property — it keeps the IMMEDIATE-marketable-
fill entry model and tries to compensate downstream. The ATR
stop-distance floor widened stops uniformly and was REJECTED
(`docs/ATR_FLOOR_EVALUATION.md`) — it did not confer delay robustness,
it just thinned the trade population. The entry-confirmation drift gate
(`max_entry_drift_pct`) tried to skip a still-immediate fill if price
had already drifted too far by delayed execution time, and was also
REJECTED — it helped partially in one tested year and provided
essentially no benefit in the other
(`docs/CONTINUOUS_RESEARCH_LOG.md` Experiment 4). H2 targets the entry
model itself, not the stop/target or a drift filter on top of an
immediate fill: instead of requiring a fill at (or near) the signal
candle's close, place a passive limit order at the actual structural
entry zone — the OB/FVG/sweep level the signal is already built from
(`docs/strategy_spec.md` §§2-5) — and let a subsequent candle's retest
fill it, with a bounded timeout that expires the order unfilled after N
candles if price never returns. `docs/RESEARCH_ROUND_1.md` §4b had
already named this technique ("limit-entry-with-timeout") and deferred
it for lack of live order-book infrastructure — but that deferral
reasoning does not fully apply to a backtest-only research question,
and the same document named the fallback this hypothesis adopts: "a
synthetic candle-only approximation," checking whether a later candle's
high/low range crosses the zone level, with no tick/L2 feed required.

**Implementation design decisions** (disclosed explicitly — these affect
how to interpret the result below):

- **Fill price**: when a limit triggers, the fill price is the zone
  level itself (`signal.entry_price`, already exactly the OB/FVG/sweep
  zone edge per `entry_model.build_entry_model`), with slippage applied
  identically to the existing immediate-fill path. Only WHEN/WHETHER the
  fill happens changed — never the price formula.
- **`entry_delay_candles` interpretation**: `entry_delay_candles` (used
  by `--delay-check`) was interpreted, as a necessary implementation
  judgment call, as placement/dispatch latency — it shifts when the
  resting order's scan window *starts*, while `limit_timeout_candles`
  still measures the window length from that point. This is the
  specific mechanism being tested: a delay in WHEN you place a resting
  order, not a delay in an immediate fill's execution price.
- **Unfilled/expired signals**: signals whose price never retested the
  zone within the timeout are not recorded as trades or losses —
  consistent with "expired signal, not a loss," matching this
  platform's existing precedent for other filtered-out signal types.

**New instrumentation**: `--limit-at-level` (rest a limit order at the
structural zone edge instead of an immediate market fill) and
`--limit-timeout-candles N` (disclosed-not-tuned default, 4 — expire
unfilled after N candles), both opt-in and default off.

**Anchor (identical across all three years)**: `--symbol BTCUSDT
--timeframe 15m --candles 3000 --periods 6 --limit-at-level
--limit-timeout-candles 4 --walk-forward --delay-check`, varying only
`--end-date` (`2026-07-10`, `2025-07-10`, `2024-07-10`), compared
against the already-recorded Legacy market-order baseline for all three
years (`docs/LEGACY_DELAY_ROBUSTNESS.md`).

## 2. Results, all three anchors

**Legacy DEFAULT-exit baseline** (already recorded,
`docs/LEGACY_DELAY_ROBUSTNESS.md`):

| Year | Net Profit | Baseline PF | Delayed PF | PF retention | Sign flip | Delay gate |
|---|---|---|---|---|---|---|
| 2026 | +$3,400.62 | 5.024 | 0.117 | 0.023 | YES | FAILED |
| 2025 | +$1,714.56 | 4.593 | 0.068 | 0.015 | YES | FAILED |
| 2024 | +$1,807.75 | 2.959 | 0.078 | 0.026 | YES | FAILED |

**`--limit-at-level --limit-timeout-candles 4` results** (new, this
round):

| Year | Net Profit | Profitable periods | PF (delay=0) | Walk-forward | Trades |
|---|---|---|---|---|---|
| 2026 | -$744.13 | 1/6 | 0.704 | FAILED (max losing streak 5, degrading) | 96 |
| 2025 | -$727.22 | 0/6 | 0.473 | FAILED (max losing streak 6, degrading) | 51 |
| 2024 | -$895.05 | 2/6 | 0.450 | FAILED (max losing streak 3, degrading) | 64 |

**Internal delay-gate retention for `--limit-at-level` itself**
(delay=0 vs delay=1, WITHIN this mechanism — this is the pre-registered
Check 2 evidence):

| Year | Baseline PF | Delayed PF | PF retention | Sign flip | Delay gate |
|---|---|---|---|---|---|
| 2026 | 0.704 | 0.706 | 1.003 | NO | PASSED |
| 2025 | 0.473 | 0.418 | 0.883 | NO | PASSED |
| 2024 | 0.450 | 0.420 | 0.935 | NO | PASSED |

## 3. Keep-rule verdict — applied literally, both parts

Quoting `docs/HYPOTHESES_ROUND_1.md` section 4's keep-rule verbatim:

> **Keep-rule (declared now, two parts)**: 1. **Cost-of-passivity
> check**: `--limit-at-level`'s own zero-added-delay Net Profit must
> retain ≥50% of Legacy market-order baseline Net Profit in at least 2
> of 3 years — a resting-order model that misses too many fills waiting
> for a retest is not a viable substitute regardless of its delay
> behavior. 2. **Delay-robustness check**: `--limit-at-level`'s
> delay-gate PF retention must clear ≥0.5 with no sign flip in at least
> 2 of 3 years — where market-order Legacy failed 3-for-3. **Both** must
> hold for KEEP. Either failing alone is REJECT — passing (1) while
> failing (2) means it's just a worse Legacy with the same fragility;
> passing (2) while failing (1) means it "fixed" delay by mostly not
> trading, the same shape of failure the ATR floor already showed.

**Check 2 (delay-robustness): PASSES cleanly, 3/3 years.** PF retention
1.003 / 0.883 / 0.935 across 2026 / 2025 / 2024, no sign flip anywhere —
the passive-limit mechanism genuinely, robustly solves the
execution-delay fragility problem that both Legacy's default exit
(retention 0.015-0.026, `docs/LEGACY_DELAY_ROBUSTNESS.md`) and
`structure_tp` (retention 0.051-0.080, Milestone 27,
`docs/H3_REGIME_DELAY_RESULTS.md`) failed catastrophically. This is
mechanistically sound: a resting order's fill price does not depend on
how quickly the decision to place it was dispatched, only on
whether/when price revisits the level — a fundamentally different
exposure to delay than an immediate market fill that chases a moving
price.

**Check 1 (cost-of-passivity): FAILS catastrophically, 0/3 years.** Not
a near-miss of the ≥50%-retention bar — it inverts sign in every single
year, turning a profitable baseline into a net loss: 2026 +$3,400.62 ->
-$744.13; 2025 +$1,714.56 -> -$727.22; 2024 +$1,807.75 -> -$895.05.

**Both must hold for KEEP; Check 1 alone disqualifies.** Per the rule's
own named failure-mode #2 ("passing (2) while failing (1)" — see the
precision note below for why this is not, in fact, the exact same shape
of failure the rule's own analogy names). **VERDICT: REJECT.**

## 4. Precision note — this is NOT the same failure shape as the ATR floor (read before citing this REJECT elsewhere)

The keep-rule's own text analogizes a Check-1 failure to "the same shape
of failure the ATR floor already showed" — i.e., delay robustness
achieved by mostly not trading. This round's actual mechanism is more
precise and, disclosed here as a genuinely novel finding, materially
different from that description:

Trade count only drops modestly (~13-21% fewer than Legacy: 2026 96 vs.
111; 2025 51 vs. 65; 2024 64 vs. 73-77) while profitable-periods
collapses almost entirely (1/6, 0/6, 2/6 vs. Legacy's 6/6 in ALL three
years) and walk-forward fails everywhere with degrading trends and
elevated losing streaks (5, 6, 3 vs. Legacy's compliant streaks). This
is **not primarily** "fixed delay by mostly not trading" (the ATR
floor's mechanism, `docs/ATR_FLOOR_EVALUATION.md` §4, which cut trade
count 46% at 1.5x and more at higher multiples) — the trade-count
reduction here is far too small to explain a swing from strongly
profitable to net-loss on its own.

The more precise, disclosed-as-genuinely-new finding: **the
retest-based passive-fill mechanism itself systematically selects for
structurally worse trade outcomes**, independent of the delay question
entirely. Waiting for a retest of the OB/FVG/sweep zone edge appears to
filter FOR setups that subsequently underperform (or filters OUT the
specific immediate-continuation setups that drove Legacy's edge), not
merely filter volume. This is a genuinely novel, third distinct failure
mode among this platform's three tested delay-robustness fixes to date:

- **ATR floor** — thinned population, wider stops alone confer no
  robustness (`docs/ATR_FLOOR_EVALUATION.md`).
- **Entry-drift gate** — inconsistent/partial benefit across years
  (`docs/CONTINUOUS_RESEARCH_LOG.md` Experiment 4).
- **H2 limit-at-level (this round)** — achieves delay-robustness
  completely and cleanly (Check 2, 3/3), but the entry model itself
  becomes unprofitable independent of delay (Check 1, 0/3, sign flip
  every year).

This is worth stating explicitly as a clean, well-differentiated
addition to the evidence base, not a repeat of a known pattern.

## 5. Promotion path

**NONE — this was a REJECT**, matching H2's own pre-registered
promotion-path text (`docs/HYPOTHESES_ROUND_1.md` §4, "Promotion path if
KEEP"), which notes that even a KEEP here would have had a uniquely
different promotion story than the other hypotheses in this round — a
candle-only approximation of a resting limit order is not verified live
limit-order behavior, so even a full KEEP would not have substituted for
Phase-1 gate #4's measured-latency requirement. Moot here since the
result is REJECT.

**Legacy's live/paper trading behavior is completely unchanged.**
`RiskManager.evaluate()` and `scripts/run_paper.py` are untouched; the
new flag pair defaults off and is byte-identical when unset, confirmed
by 2 dedicated regression tests in `backend/tests/test_backtest_engine.py`.
No orders were placed; no writes to `backend/paper_validation.db`
occurred.

## 6. Caveats

- **One asset (BTCUSDT), one timeframe (15m), three Jan-Jul windows
  (2024, 2025, 2026)** — matching H2's own pre-registered 3-year anchor
  set. Not cross-asset checked.
- **Candle-only approximation, not verified live limit-order
  behavior.** No tick/L2 feed, no queue-position or partial-fill
  modeling — deliberately the "synthetic candle-only approximation"
  `docs/RESEARCH_ROUND_1.md` §4b named as the honest middle ground
  short of full limit-order-book simulation, which was already
  correctly rejected as disproportionate for this platform (same
  document, §2b/§5).
- **`limit_timeout_candles=4` was the only timeout value tested** — a
  disclosed-not-tuned default declared before any run, per this
  project's discipline. A different timeout window is a theoretical
  possibility not ruled out by this REJECT, though the magnitude of
  Check 1's failure (sign flip in all three years, not a near-miss)
  makes it unlikely a different timeout alone would flip the verdict
  without also re-testing whether the underlying retest-selection
  mechanism (section 4) still applies.
- **No code was touched beyond the new opt-in flag pair; no live/paper
  system was modified.** This is a read-only evidence document per the
  department's scope — the mechanism and precision notes in sections 4
  are findings, not changes.
