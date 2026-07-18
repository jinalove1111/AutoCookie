# Hypothesis Round 1 — Candidate Generation for the Empty Strategy Pipeline

Research + Hypothesis department deliverable (2026-07-17), CTO directive.
**Context**: the platform's candidate pipeline is empty. All four
quarantined textbook strategies lose outright on aggregate
(`docs/EXPERIMENTAL_STRATEGY_EVALUATION.md`) and lose in every regime
bucket with a meaningful sample
(`docs/REGIME_PERFORMANCE_ANALYSIS.md` — Legacy wins the one
sufficient-evidence bucket, `weak_trend/normal_volatility`, by ~6x
expectancy). Legacy itself is the platform's only working edge, and it
is now known to be structurally delay-fragile — fails the 1-candle
(15-minute) execution-delay gate in 3 of 3 tested years
(`docs/LEGACY_DELAY_ROBUSTNESS.md`, retention 0.026/0.015/0.023). The
one attempted fix (a minimum ATR-multiple stop floor) was A/B-tested and
REJECTED — it does not confer delay robustness, it just thins the
trade population (`docs/ATR_FLOOR_EVALUATION.md`).

This document does not propose a new strategy family. Per the
department's mandate, every hypothesis below is a **falsifiable
mechanism**, grounded in this platform's own accumulated evidence, with
a **pre-registered experiment** (exact `run_backtest.py` invocations,
exact keep/reject rule, declared before any run) and an honest
implementation-cost estimate. Nothing here is evidence; these are
experiments to run, in priority order.

**Ground rule inherited from every prior evidence round in this
project** (`docs/ATR_FLOOR_EVALUATION.md`, `docs/RESEARCH_ROUND_1.md`):
a hypothesis earns a KEEP only if the pre-declared criterion is met on
the pre-declared anchors, evaluated after the run, not adjusted to fit
the result. A negative result is a first-class outcome of this round,
not a failure of it.

---

## 1. Ranking

Ranked by (evidence-grounding × testability) / implementation cost,
each factor scored 1 (weak) – 5 (strong) informally, cost scored 1
(near-zero) – 5 (substantial new mechanism):

| Rank | Hypothesis | Grounding | Testability | Cost | Why |
|---|---|---|---|---|---|
| **1** | H4 — Close the backtest/live position-sizing gap | 5 | 5 | 1 | Not a search for new edge — a verified, present-tense blind spot: every backtest number in this project's entire evidence base was computed WITHOUT the volatility-scaled sizing that live paper trading has actually been running since Milestone 7. Nearly free to test; the result conditions how every other finding (including H1–H3 below) should be read. |
| **2** | H1 — Quality-ranked selection inside the existing `MAX_TRADES_PER_DAY` cap | 5 | 4 | 3 | Directly targets the single largest disclosed, quantified opportunity in the evidence base: 89–92% of Legacy's own signals are discarded by a FIFO daily cap, in all three tested years. Backtest-only, zero live-risk change by construction. |
| **3** | H3 — Regime-conditional delay survival of the `structure_tp` family | 4 | 3 | 2 | Combines three already-built, already-independently-validated mechanisms (`--structure-tp`, `--tag-regimes`, `--delay-check`) in a combination nobody has run together yet. Pure analysis on top of existing machinery. |
| **4** | H2 — Passive (limit-at-level) entry as a delay-robust alternative to immediate market entry | 3 | 3 | 4 | Mechanistically distinct from the already-rejected ATR-floor fix and the already-rejected drift-gate fix, and grounded in a `RESEARCH_ROUND_1.md` item that was deferred for infra reasons that may no longer apply. Highest new-code cost of the five. |
| **5** | H5 — Session-conditional position sizing (not entry filtering) | 2 | 3 | 2 | Cheap, and mechanistically distinct from the already-rejected Asian-only entry filter — but rides on the same small-sample session split (Test 6: 41/19/8 trades) whose failure mode (small-sample noise) already sank the filter version. Weakest grounding of the five; listed for completeness, not urgency. **Full pre-registration: section 6** (added 2026-07-19, after H1-H4 resolved — Grounding column above reflects the ORIGINAL 2026-07-17 assessment; section 6 discusses new supporting evidence from H1/Milestone 26 found since). |

**Recommended first experiment: H4.** See section 7.

---

## 2. H1 — Quality-ranked selection inside the existing `MAX_TRADES_PER_DAY` cap

### Mechanism

Legacy's `RiskManager.evaluate()` accepts or rejects each signal as it
arrives, in chronological (FIFO) order, and stops approving once
`trades_today >= MAX_TRADES_PER_DAY` (2). `docs/LEGACY_DELAY_ROBUSTNESS.md`
§2 (Milestone 23 instrumentation, first used in an evidence round)
measured this directly: **804 of 869 raw signals (92.5%) rejected in
2025, and 595 of 668 (89.1%) in 2024** — every single rejection reason
that fired anywhere in either log was `MAX_TRADES_PER_DAY 2 reached`.
`ENGINEERING_DECISIONS.md` #62 records this as a real finding and
explicitly does NOT act on it, precisely because raising the cap is a
risk-limit change outside this department's authority. The mechanism
this hypothesis tests is narrower and safer: **holding the cap fixed at
2, does selecting the two highest-QUALITY signals of the day (instead
of the first two chronologically) improve expectancy?** If Legacy's own
signal-generation pipeline produces variable-quality signals — some
combination of realized reward:risk (`TradeSignal.rr`), confluence
count (sweep+CHOCH both present vs. one, OB+FVG both agree vs. one,
per `docs/strategy_spec.md` §6), or structural-target distance —
re-ordering which two of an oversupply of signals get taken should be a
pure selection effect: same number of trades, same nominal risk
exposure, no change to entry/stop/target logic.

### Grounding

- **Internal**: `docs/LEGACY_DELAY_ROBUSTNESS.md` §2 (869/804 and
  668/595 rejection counts, 2025/2024); `ENGINEERING_DECISIONS.md` #62
  ("a large untapped signal stream exists... this round observes and
  discloses the effect; it does not propose touching the cap" —
  exactly the boundary this hypothesis respects: touch selection, not
  the cap). `docs/strategy_spec.md` §6 already documents an A/B-tested,
  cheaper analog of this exact question for entry gating —
  `require_full_confluence=True` cuts trade count ~76% for a per-trade
  PnL within 4% of the looser rule, i.e. **stricter confluence does NOT
  automatically produce meaningfully higher-quality trades on this
  platform** (a real prior negative result this hypothesis must survive
  contact with, not ignore).
- **External**: general signal-quality/trade-selection literature
  (trade "quality grading" — e.g. traderssecondbrain.com's A/B/C
  framework; Macrosynergy's signal-quality research,
  macrosynergy.com/research/how-to-measure-the-quality-of-a-trading-signal/)
  converges on the same practical claim relevant here: ranking and
  selectively executing higher-quality signals under a fixed trade
  budget can improve expectancy — but the same sources note this only
  holds if the ranking criterion is genuinely predictive of forward
  outcome, which is exactly what this experiment measures rather than
  assumes.

### Pre-registered experiment

**New instrumentation required** (research-only, does not touch
`RiskManager`'s live sequential-approval logic): a new analysis mode —
e.g. `scripts/research_signal_selection.py` or a `--rank-signals-by
{chronological,rr,confluence}` research flag on a copy of the
backtest loop — that, for each simulated trading day, collects EVERY
candidate signal `SignalEngine` would have generated at each step
(already surfaced in principle by the Milestone 23 rejection
instrumentation), scores each by a **disclosed-not-tuned** formula
(`score = rr` as the primary variant; `score = rr + confluence_count`
as a secondary variant, both declared now, not chosen post-hoc), and
replays execution using only the top-`MAX_TRADES_PER_DAY` signals per
day by score instead of by arrival order. All downstream mechanics
(fees, slippage, fills, PnL) reuse `BacktestEngine` unchanged.

**Runs** (chronological-FIFO baseline vs. `rr`-ranked vs.
`rr+confluence`-ranked, each on both anchors):

```
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2026-07-10 --walk-forward --delay-check
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2025-07-10 --walk-forward --delay-check
```
(the two baseline runs already exist verbatim in
`docs/ATR_FLOOR_EVALUATION.md` / `docs/LEGACY_DELAY_ROBUSTNESS.md` —
re-run only if the research script's day-batching changes what counts
as "the baseline", otherwise reuse the recorded numbers directly),
against the new tool's two ranked variants over the identical
already-fetched candle set for both anchors.

**Keep-rule (declared now)**: KEEP (promote to further validation, NOT
to production/paper) only if a ranked variant **beats the chronological
baseline on Net Profit AND Profit Factor in BOTH the 2026 and 2025
anchors**, AND does not newly fail walk-forward relative to the
baseline's own result. A ranked variant that wins one year and loses
the other, or wins on PF but not Net Profit, is REJECT — same
discipline `docs/PROFITABILITY_EXPERIMENT_REPORT.md` §13.1 applied to
XRP's tied drawdown and §14 applied to SOL's mixed cross-year result.
Since this hypothesis is about signal SELECTION, not stop/target
mechanics, no material change to delay-gate retention is expected or
required for a KEEP — record it, do not gate on it.

### Cost

Small–medium: no new trading concept, no new detector — reuses
`RiskManager`'s existing rejection-reason machinery and
`TradeSignal.rr`/confluence fields already computed by the entry
pipeline. The work is a new day-batching research harness, not a
production code change.

### Promotion path if KEEP

Explicitly NOT a promotion by itself. Any live/paper change to how
signals are selected within the day is a **risk-and-behavior change**,
not a reporting change (live trading sees signals stream in real time
and would need an intraday deferred-decision window to "wait and pick
best-of-day," a genuine architecture change) — squarely
operator-gated, same category as `MAX_TRADES_PER_DAY` itself per
decision #62. Before any such operator conversation: cross-asset
(ETH/SOL/XRP) confirmation, cross-year confirmation (2024 in addition
to 2025/2026, matching the 3-year standard `docs/LEGACY_DELAY_ROBUSTNESS.md`
§7 established), and the standardized delay-gate check
(`docs/RESEARCH_ROUND_1.md` recommendation #1) — all unchanged gates.

---

## 3. H3 — Regime-conditional delay survival of the `structure_tp` family

### Mechanism

`docs/PROFITABILITY_EXPERIMENT_REPORT.md` §12–14 validated
`use_structure_tp=True` (uncapped, and later
`structure_tp_max_r=3.0` + `require_premium_discount_filter=True`) as
the platform's strongest candidate family — cross-asset (BTC, SOL) and
cross-year (2025, 2026 clean; 2024 mixed) on raw profitability and
walk-forward. Separately, `docs/ROBUSTNESS_REPORT.md` Test 2 found this
SAME family catastrophically delay-fragile in AGGREGATE (PF 5.24 → 0.16
at a 5-minute delay on a 5m anchor) — the finding that started the
entire delay-robustness thread, later confirmed structural for Legacy
itself in `docs/LEGACY_DELAY_ROBUSTNESS.md`. **No round has ever
regime-tagged a `structure_tp` delay-check run.** `structure_tp`
targets a real structural level (the previous swing high/low, or the
premium/discount equilibrium if farther — `docs/strategy_spec.md` §6)
rather than a fixed-RR target, so its stop/target distances vary with
market structure, unlike a uniform ATR floor. The hypothesis: in
regimes with more directional persistence (`strong_trend/*`, or BTC's
dominant `weak_trend/normal_volatility` bucket), a 15-minute delay
might matter proportionally less — price has less opportunity to
reverse through a farther-away stop before the delayed fill — than in
choppy/reversal-prone regimes, where the aggregate 0.16 PF collapse
could be concentrated. This is a genuinely different mechanism from the
already-REJECTED ATR floor: the floor uniformly widened stops
regardless of regime and was shown to merely thin the population
without conferring robustness (`docs/ATR_FLOOR_EVALUATION.md` §4); this
hypothesis touches no parameter at all — it asks whether an
**already-built, already-validated** candidate's EXISTING variable
stop/target geometry happens to be delay-robust in specific,
identifiable regimes.

### Grounding

- **Internal**: `docs/PROFITABILITY_EXPERIMENT_REPORT.md` §12–14
  (structure_tp family, cross-asset/cross-year validated on
  profitability, never delay-gate-tested); `docs/ROBUSTNESS_REPORT.md`
  Test 2 (the aggregate delay collapse that motivated the entire
  research thread); `docs/REGIME_PERFORMANCE_ANALYSIS.md` (BTC's
  dominant, only-evidence-sufficient regime is
  `weak_trend/normal_volatility`, n=28 for Legacy — the natural regime
  to check first for both trade volume and comparability to existing
  regime evidence); `docs/ATR_FLOOR_EVALUATION.md` §4 (the specific,
  already-falsified alternative mechanism — "wider stops alone don't
  help" — that this hypothesis must be read against, not confused
  with).
- **External**: none specific to this exact mechanism was found;
  this hypothesis is a first-party, evidence-driven combination of
  already-cited techniques (structure-based exits: Wilder-adjacent
  ICT/SMC convention already cited in `docs/RESEARCH_ROUND_1.md` §4a;
  delay/latency-aware backtesting: QuantStart, hftbacktest, both
  already cited in the same document) rather than an import of a new
  external claim.

### Pre-registered experiment

**New instrumentation required**: a per-regime delay-retention
aggregator (analysis-only — reuses `tag_regimes` and `delay-check`,
which have never been run together with a per-bucket join). For each
regime bucket, compute PF at `entry_delay_candles=0` and `=1`
separately among trades tagged to that bucket, then compute retention
per bucket rather than only in aggregate.

```
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2026-07-10 --structure-tp --tag-regimes --delay-check --walk-forward
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2025-07-10 --structure-tp --tag-regimes --delay-check --walk-forward
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2024-07-10 --structure-tp --tag-regimes --delay-check --walk-forward
```

(Uncapped `--structure-tp` is used because it is already exposed on
`run_backtest.py`'s CLI; the refined `structure_tp_max_r=3.0` +
`require_premium_discount_filter=True` combo used in
`docs/PROFITABILITY_EXPERIMENT_REPORT.md` §13.4 is currently only
reachable via `run_backtest_period()`'s Python parameter, not a CLI
flag — exposing it is a small follow-on documented in the cost section
below, only worth doing if the uncapped result is promising enough to
justify it.)

**Keep-rule (declared now)**: a regime bucket counts as a genuine
delay-robust pocket only if it clears the SAME bar the platform already
applies everywhere else: **n≥20 trades on the delayed side of that
bucket, PF retention ≥0.5, no sign flip, in AT LEAST 2 of the 3 tested
years.** If no bucket clears this bar in any year, REJECT the
regime-conditional-survival hypothesis outright — matching
`docs/REGIME_PERFORMANCE_ANALYSIS.md` §3a's own "beats Legacy in a
bucket with n≥20 on both sides" evidentiary bar, applied here to
delay-retention instead of expectancy. A bucket clearing the bar in
only 1 of 3 years is recorded as a directional lead, not a keep.

### Cost

Small: `--tag-regimes`, `--delay-check`, and `--structure-tp` all
already exist independently; this hypothesis is a new aggregation
script joining outputs that already exist, not new detection or
execution logic. Exposing `structure_tp_max_r` as its own CLI flag (if
warranted after the uncapped result) is itself small (~10–20 lines,
mirroring `--min-stop-atr`'s existing pattern).

### Promotion path if KEEP

If a bucket clears the keep-rule: this becomes a genuine
regime-conditional candidate for `RollingPerformanceSelector`
(`docs/ADAPTIVE_ARCHITECTURE.md` §4.3) — still requires cross-asset
confirmation (ETH/SOL/XRP), and — since `structure_tp` already has
prior cross-asset/cross-year evidence on raw profitability — the
REMAINING gate specific to this finding is Phase-1 gate #4's measured
live-latency requirement (`docs/ADAPTIVE_ARCHITECTURE.md`, hardened per
`docs/LEGACY_DELAY_ROBUSTNESS.md` §4): a backtest delay-gate PASS in
one regime is not the same as verified live signal-to-fill latency, and
would not by itself authorize skipping that measurement.

---

## 4. H2 — Passive (limit-at-level) entry as a delay-robust alternative

### Mechanism

Every delay-robustness fix tried so far shares one property: it keeps
the IMMEDIATE-marketable-fill entry model and tries to compensate
downstream (wider stop via ATR floor — REJECTED,
`docs/ATR_FLOOR_EVALUATION.md`; skip the trade if the delayed fill has
drifted too far — REJECTED in both tested years,
`docs/CONTINUOUS_RESEARCH_LOG.md` Experiment 4). This hypothesis
targets the entry model itself: instead of requiring an immediate fill
at (or near) the signal candle's close, place a passive limit order at
the actual structural entry zone (the OB/FVG/sweep level the signal is
already built from — `docs/strategy_spec.md` §§2–5) and let a
subsequent candle's retest fill it, with a bounded timeout (expire
unfilled after N candles if price never returns). Approximable entirely
from existing OHLC candle data — no tick/L2 feed needed — by checking
whether a later candle's high/low range crosses the zone level.
`docs/RESEARCH_ROUND_1.md` §4b already named this technique
("limit-entry-with-timeout") and DEFERRED it specifically because full
implementation would need live order-book infrastructure this platform
lacks — but that document's own text also names the fallback this
hypothesis proposes: "a synthetic candle-only approximation." The
deferral reasoning does not fully apply to a backtest-only research
question.

### Grounding

- **Internal**: `docs/ATR_FLOOR_EVALUATION.md` (falsifies the
  "wider-stop-alone" mechanism this hypothesis must NOT be confused
  with — a passive entry changes WHEN/WHERE the fill happens, not the
  stop distance once filled); `docs/CONTINUOUS_RESEARCH_LOG.md`
  Experiment 4 (falsifies the "gate the market fill by drift" mechanism
  — helped partially in one year, not at all in the other); `docs/RESEARCH_ROUND_1.md`
  §4b (names this exact technique, defers it, and names the specific
  candle-only fallback this hypothesis adopts).
- **External**: standard market-vs-limit-order tradeoff (price control
  vs. fill uncertainty — e.g. Altrady's market/limit primer,
  altrady.com/blog/crypto-trading-strategies/market-order-vs-limit-order-crypto);
  confirmation-entry/whipsaw literature converges on the same
  structural tradeoff this hypothesis is built on — trading immediacy
  for reliability filters out some genuine moves in exchange for
  avoiding chasing a price that has already moved (justintrading.com's
  confirmation-candle discussion; abovethegreenline.com on whipsaw
  mitigation); `nkaz001/hftbacktest` (github.com/nkaz001/hftbacktest),
  already cited in `docs/RESEARCH_ROUND_1.md` §4a, is the honest
  reference for what FULL limit-order/queue-position simulation looks
  like — explicitly disproportionate for this platform, which is why
  this hypothesis proposes only the candle-only approximation, not that
  level of rigor.

### Pre-registered experiment

**New CLI flags required** (new entry-timing logic in
`BacktestEngine`/`entry_model.py`, opt-in, default off, same
"disclosed-not-tuned" discipline as every existing flag):
`--limit-at-level` (place the entry as a resting limit at the
structural zone edge instead of an immediate market fill) and
`--limit-timeout-candles N` (disclosed-not-tuned default, e.g. 4 —
expire unfilled after N candles).

```
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2026-07-10 --limit-at-level --limit-timeout-candles 4 --walk-forward --delay-check
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2025-07-10 --limit-at-level --limit-timeout-candles 4 --walk-forward --delay-check
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2024-07-10 --limit-at-level --limit-timeout-candles 4 --walk-forward --delay-check
```

compared against the existing Legacy market-order baseline already
recorded for all three years in `docs/LEGACY_DELAY_ROBUSTNESS.md`.

**Keep-rule (declared now, two parts)**:

1. **Cost-of-passivity check**: `--limit-at-level`'s own zero-added-delay
   Net Profit must retain **≥50% of Legacy market-order baseline** Net
   Profit in at least 2 of 3 years — a resting-order model that misses
   too many fills waiting for a retest is not a viable substitute
   regardless of its delay behavior.
2. **Delay-robustness check**: `--limit-at-level`'s delay-gate PF
   retention must clear **≥0.5 with no sign flip in at least 2 of 3
   years** — where market-order Legacy failed 3-for-3
   (`docs/LEGACY_DELAY_ROBUSTNESS.md` §3).

**Both** must hold for KEEP. Either failing alone is REJECT — passing
(1) while failing (2) means it's just a worse Legacy with the same
fragility; passing (2) while failing (1) means it "fixed" delay by
mostly not trading, the same shape of failure the ATR floor already
showed (`docs/ATR_FLOOR_EVALUATION.md` §4's "just trades less").

### Cost

Medium–high (highest of the five): a genuinely new fill-timing
mechanism in `BacktestEngine`, not a parameter on an existing one — a
candle-walk-forward search for zone touch within a timeout window, new
unit tests, a new opt-in flag pair. Not a new TRADING concept (the zone
being rested-on is already computed by the existing OB/FVG/sweep
detectors), but real new execution-simulation code.

### Promotion path if KEEP

Same full gate set as any candidate (cross-asset, cross-year, walk-forward,
delay-gate) — but explicitly, per `docs/RESEARCH_ROUND_1.md` §4b's own
caveat, a **candle-only approximation of a resting limit order is not
verified live limit-order behavior**. Even a full KEEP here would not
substitute for Phase-1 gate #4's measured-latency requirement; it would
instead be the FIRST candidate this platform has ever had that is
plausible to actually validate against real limit-order fills once
live-trading infrastructure exists — a meaningfully different
promotion story than the other hypotheses in this round, worth
recording as such.

---

## 5. H4 — Close the backtest/live position-sizing gap (recommended first experiment)

### Mechanism — this is a verified code fact, not a speculative claim

`Milestone 7` (`ENGINEERING_DECISIONS.md` #49, 2026-07-15) added
volatility-scaled position sizing: `calculate_position_size(...,
volatility: str | None = None)` multiplies `risk_amount` by
`volatility_risk_scalar(volatility)` — **0.5 in `high_volatility`, 1.0
otherwise** (`backend/app/risk/position_sizing.py`). `scripts/run_paper.py`
computes `current_volatility` via `detect_market_regime(candles)` and
passes it into every real sizing call (`run_paper.py` line ~1325–1337)
— **this is live in paper trading today.**

Verified directly in `backend/app/backtesting/backtest_engine.py` line
589: `BacktestEngine.run()` calls `calculate_position_size(account_balance,
settings.RISK_PER_TRADE_PERCENT, signal.entry_price, signal.stop_loss)`
— **no `volatility` argument is ever passed.** `tag_regimes`'s own
`detect_market_regime()` call (line 657) happens AFTER sizing and is
gated behind a separate, default-off flag most evidence runs never set.
The consequence: **every backtest number cited anywhere in this
platform's evidence base** —
`docs/REGIME_PERFORMANCE_ANALYSIS.md`, `docs/LEGACY_DELAY_ROBUSTNESS.md`,
`docs/ATR_FLOOR_EVALUATION.md`, `docs/PROFITABILITY_EXPERIMENT_REPORT.md`
— was computed at a UNIFORM 1.0x risk scalar, while live paper trading
has been running a 0.5x scalar in high-volatility regimes since
2026-07-15. This is not a hypothesis about a new source of edge; it is
a hypothesis about whether this SILENT DIVERGENCE between the
evidence base and the live system changes any existing headline
finding — drawdown, Sharpe, and the delay-gate numbers are all currency-
or variance-sensitive metrics that a sizing change could plausibly move,
even though trade classification (win/loss, which candle fills) should
not change since entries/stops/targets are untouched.

### Grounding

- **Internal**: `ENGINEERING_DECISIONS.md` #49 (the scalar's exact
  values, disclosed-not-tuned, "0.5 is a reasonable, conservative
  starting halving factor, not backtest-derived" — literally never
  evidenced); direct code verification in
  `backend/app/backtesting/backtest_engine.py` (sizing call, line 589)
  and `scripts/run_paper.py` (live sizing call, line ~1337) showing the
  divergence.
- **External**: Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van
  Hemert (2018), *"The Impact of Volatility Targeting,"* SSRN 3175538 —
  finds volatility scaling improves Sharpe ratio and reduces tail-event
  severity specifically for "risk assets" (equities/credit-like
  behavior, plausibly applicable to BTC), with the effect concentrated
  in reduced exposure during elevated-volatility, negative-return
  periods; Hoyle & Shephard (2018), *"Volatility Scaling's Impact on
  the Sharpe Ratio,"* SSRN 3279787 (a related, more technical
  treatment). Both are cited as directional support for the MECHANISM
  (why scaling down in high vol should help risk-adjusted metrics), not
  as proof it will hold on this platform's specific setup — that is
  exactly what this experiment checks.

### Pre-registered experiment

**Small change required**: thread `detect_market_regime`'s volatility
label into `BacktestEngine`'s sizing call, mirroring `run_paper.py`'s
own best-effort/fail-open pattern exactly (regime detection failure or
insufficient history → `volatility=None` → unchanged 1.0 scalar, never
a hard failure). New opt-in flag: `--vol-scaled-sizing` (default off,
byte-identical to today's behavior when unset — same "opt-in flag
before default change" discipline, `ENGINEERING_DECISIONS.md` #10).

```
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2026-07-10 --vol-scaled-sizing --walk-forward --delay-check
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2025-07-10 --vol-scaled-sizing --walk-forward --delay-check
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2024-07-10 --vol-scaled-sizing --walk-forward --delay-check
```

compared directly against the ALREADY-RECORDED baseline numbers for all
three years (`docs/LEGACY_DELAY_ROBUSTNESS.md`,
`docs/ATR_FLOOR_EVALUATION.md`) — no need to re-run the baseline, it
already exists and is unaffected by this flag when unset.

**Keep-rule (declared now)** — note this keep-rule is deliberately
about EVIDENCE INTEGRITY, not about finding new edge:

- **If max drawdown improves and Net Profit/PF are materially
  unchanged (within ~10%) in at least 2 of 3 years**: record this as a
  confirmed, real improvement to risk-adjusted metrics consistent with
  the external literature — and, critically, **re-open every existing
  finding whose headline number could plausibly move**, starting with
  the delay-gate retention figures (0.026/0.015/0.023) and the
  walk-forward degradation checks, since those are exactly the
  currency-sensitive metrics a sizing change could shift.
- **If Net Profit or PF materially degrades**: this is itself
  important — it would mean Milestone 7's disclosed-not-tuned 0.5x
  scalar, currently live in paper trading, is costing real expectancy
  with no compensating drawdown benefit large enough to justify it, an
  operator-relevant finding independent of this round's original
  purpose.
- **If nothing moves materially in either direction**: also a valid,
  useful result — it means the evidence base's silent 1.0x-everywhere
  assumption was harmless in practice on this asset/window, closing the
  gap as a documentation fix rather than a numeric one.

There is no REJECT branch in the usual sense — this experiment's value
is in the answer, not in clearing a promotion bar, since the mechanism
(`volatility_risk_scalar`) is already live in production paper trading
regardless of this round's outcome.

### Cost

Very small: reuses `detect_market_regime` and `volatility_risk_scalar`
verbatim, mirrors `run_paper.py`'s exact fail-open pattern, no new
detector, no new trading concept — this is closing a gap between two
code paths that already both exist.

### Promotion path if KEEP

None required in the traditional sense — the sizing mechanism is
ALREADY live in paper trading (Milestone 7 shipped it as a real
producer, `ENGINEERING_DECISIONS.md` #49). This experiment's job is to
retroactively evidence a decision that was made and deployed without
backtest evidence, and to flag which existing documented findings (if
any) should carry a footnote noting they predate this correction. If
the "Net Profit or PF materially degrades" branch above triggers, THAT
becomes an operator-relevant question about whether the live 0.5x
scalar should be revisited — squarely outside this department's
authority to decide, exactly like `MAX_TRADES_PER_DAY` in H1.

---

## 6. H5 — Session-conditional position sizing (not entry filtering)

**Added 2026-07-19, after H1-H4 all resolved.** Section 1's ranking table
carried H5 as a one-line row only, by explicit department decision (see
`CLAUDE.md`'s own caution about this hypothesis) — this section is the
full pre-registration the ranking-table row deferred, written BEFORE any
run, per this document's own rule #1. Nothing below is backtest-run
retroactively; the grounding re-assessment in the next subsection draws
only on evidence that already existed in committed docs before this
section was written.

### Mechanism

`docs/ROBUSTNESS_REPORT.md` Test 6 bucketed real trades by UTC entry hour
(Asian 00-08, London 08-16, NY/other 16-24) and found a real, disclosed
profit-factor gradient: Asian PF 4.65 (n=41), London PF 2.41 (n=19),
NY/other "infinite" PF (n=8, explicitly flagged in that same document as
likely small-sample noise, not a real edge). `docs/CONTINUOUS_RESEARCH_LOG.md`
Experiment 3 already tested the obvious first mechanism this gradient
suggests — an Asian-only entry FILTER — and it was REJECTED: uniformly
worse Net Profit, Profit Factor, and Sharpe in both tested years, because
restricting entries to one window roughly halved trade count in both
years (42→30 trades in 2026, 26→13 in 2025) while only buying a modest
drawdown improvement in return. H5 proposes a mechanistically distinct
alternative that this platform has not tested: instead of DISCARDING
trades outside the strong session (filtering), scale each trade's
position SIZE by which session it enters in (sizing) — every signal that
would otherwise fire still fires and still gets filled; only the risk
allocated per trade changes. This targets the filter's own diagnosed
failure mode directly: Experiment 3 lost because it traded throughput
away for selectivity, not because the underlying session-quality signal
was wrong.

**New grounding this hypothesis has that its original 2026-07-17 ranking
did not**: `docs/H1_SIGNAL_SELECTION_RESULTS.md` / `ENGINEERING_DECISIONS.md`
#64 (Milestone 26, published 2026-07-18 — one day AFTER H5 was ranked
last in section 1) found, independently and for an unrelated mechanism,
that "Legacy's edge on this platform depends more on trade FREQUENCY
under a fixed cap than on per-trade selectivity" — ranked-selection
variants that cut throughput to raise average trade quality lost Net
Profit in both tested years despite winning on Profit Factor. This is
directly relevant to H5: it is independent evidence, discovered after
H5's original ranking, for exactly the mechanism distinction H5 already
claimed informally (sizing preserves throughput, filtering doesn't) —
this section treats it as a real grounding upgrade, not merely restates
the original ranking-table framing.

The exact sizing mechanism proposed mirrors H4's already-implemented,
already-live pattern (`backend/app/risk/position_sizing.py`'s
`volatility_risk_scalar`) as closely as possible, for the same reason H4
gave: a disclosed-not-tuned dict of scalars keyed by a regime-like label,
defaulting to 1.0 (unchanged behavior) for anything unrecognized or
undetectable, threaded into `calculate_position_size` as an additional
optional multiplier alongside (not replacing) `volatility_risk_scalar`.
Unlike `volatility_risk_scalar`'s safety-only "scale down, never up"
convention (`ENGINEERING_DECISIONS.md` #49 — a risk-safety measure, not
an edge-seeking one), H5's proposed scalars are deliberately symmetric,
because the mechanism under test here is genuinely different: whether
sizing UP into a disclosed higher-quality session and DOWN into a
disclosed lower-quality one improves risk-adjusted expectancy, not a
volatility safety brake. Disclosed-not-tuned proposed values (illustrative,
declared now, not to be adjusted after seeing results):

| Session label | Window (UTC) | Test 6 evidence | Proposed scalar |
|---|---|---|---|
| `asian` | 00:00-08:00 | PF 4.65, n=41 (pooled 2 yrs) | 1.5 |
| `london` | 08:00-16:00 | PF 2.41, n=19 (pooled 2 yrs) | 0.75 |
| `ny_other` | 16:00-24:00 | PF "infinite", n=8 -- disclosed noise | 1.0 (unchanged) |
| unavailable / unrecognized | -- | -- | 1.0 (unchanged, fail-open) |

`ny_other` is deliberately left unscaled even though Test 6's own PF
number for it is the highest of the three — the same source document
that reports it explicitly discloses it as probable small-sample noise,
and this hypothesis is not permitted to smuggle that caveat away by
citing the number without the disclosure attached. Scaling only the two
buckets whose sample sizes clear a reasonable floor (and only in the
direction their own evidence points) is the disciplined reading of Test
6, not the aggressive one.

### Grounding

- **Internal, supporting**: `docs/ROBUSTNESS_REPORT.md` Test 6 (the
  session PF gradient, with its own noise disclosure for `ny_other`);
  `backend/app/strategy/session_liquidity.py` and the `_SESSION_WINDOWS`
  dict already in `backend/app/strategy/signal_engine.py` (Asian/London
  window constants already exist and are already reused by
  `require_session`, `ENGINEERING_DECISIONS.md` #27); `backend/app/risk/position_sizing.py`'s
  `volatility_risk_scalar` (the exact pattern this hypothesis' mechanism
  is modeled on, already validated in production by H4/Milestone 25);
  `docs/H1_SIGNAL_SELECTION_RESULTS.md` / `ENGINEERING_DECISIONS.md` #64
  (the new, independently-discovered "throughput beats selectivity on
  this platform" finding that directly supports sizing-over-filtering as
  a mechanism class).
- **Internal, weakening (disclosed, not omitted)**: `docs/CONTINUOUS_RESEARCH_LOG.md`
  Experiment 3 (the closest prior art — same session windows, same
  motivating Test 6 evidence, rejected as an entry filter; H5 must
  survive contact with why that failed, not merely assert it won't
  recur). **A grounding gap this section is the first to surface**: Test
  6's 41/19/8 trades were measured on the `docs/ROBUSTNESS_REPORT.md`
  "production candidate" — BTCUSDT **5-minute** timeframe,
  `use_structure_tp=True, structure_tp_max_r=3.0,
  require_premium_discount_filter=True` (`scripts/research_session_filter.py`
  confirms `TIMEFRAME = "5m"` for the identical Test-6-motivated
  Experiment 3 run) — **not** the BTCUSDT **15-minute** Legacy
  default-exit candidate that every H1-H4 experiment in this same
  document standardized on. The session-PF gradient this hypothesis
  rests on has never been checked on the actual candidate/timeframe H5
  would size. The pre-registered experiment below treats this as a
  precondition to verify, not an assumption to inherit — see step 0.
  Also disclosed: the 41/19/8 counts are POOLED across the 2025+2026
  anchors (`docs/ROBUSTNESS_REPORT.md` Test 1's "68 real trades... across
  both confirmed years combined" is the same 41+19+8=68), so PER-YEAR
  session sample sizes are smaller than the headline counts suggest —
  compounding, not merely repeating, the ranking table's own "small-sample
  noise" caveat.
- **External**: no literature specific to crypto trading-session position
  sizing was found beyond the general volatility-targeting citations
  already used for H4 (Harvey et al. 2018, SSRN 3175538; Hoyle & Shephard
  2018, SSRN 3279787) — both support the general principle that scaling
  size by a disclosed, independent conditioning variable can improve
  risk-adjusted return without changing trade classification, the same
  principle applied here to a session label instead of a volatility
  label. Session/liquidity-cycle literature (the same ICT/SMC session
  convention already cited for `session_liquidity.py`,
  `ENGINEERING_DECISIONS.md` #27) supports the WINDOWS chosen, not the
  specific scalar values, which remain disclosed-not-tuned.

### Pre-registered experiment

**Step 0 (grounding check, run and evaluated FIRST, before any new code
is written)**: reuse the existing session-bucketing method from
`docs/ROBUSTNESS_REPORT.md` Test 6 / `scripts/research_session_filter.py`,
applied instead to Legacy's own standard candidate at this document's
standard anchors — BTCUSDT 15m, `--candles 3000 --periods 6`, no new
flags, the SAME three runs already on record for delay-gate purposes:

```
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2026-07-10 --walk-forward
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2025-07-10 --walk-forward
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2024-07-10 --walk-forward
```

Bucket each anchor's resulting trades by entry-candle UTC hour into
Asian/London/`ny_other` (same three windows as Test 6) and compute PF per
bucket per year — an analysis-only pass over already-recorded trade
output, no engine change required for this step.

**Step-0 gate (declared now)**: H5's mechanism proceeds to Step 1 only if
Legacy/15m shows the SAME qualitative gradient direction Test 6 found
(Asian PF > London PF) in at least 2 of the 3 tested years, AND at least
the Asian and London buckets individually reach n≥10 trades in the year(s)
counted toward that check (a lower floor than H1/H3's n≥20 sizing-gate
convention, deliberately, since this is a precondition check not a
promotion gate — but not so low that a 2-3 trade bucket could satisfy
it). **If this gate fails, H5 is REJECTED at step 0** without building
`session_risk_scalar` at all — sizing around a gradient that does not
actually replicate on the candidate/timeframe being sized would be
fitting Test 6's unrelated-candidate numbers, not this platform's live
strategy.

**Step 1 (mechanism test, only if step 0 passes)**: implement
`session_risk_scalar(session: str | None) -> float` in
`backend/app/risk/position_sizing.py`, mirroring `volatility_risk_scalar`
exactly (dict lookup, `None`/unrecognized → 1.0, never raises), using the
disclosed-not-tuned table above. Thread it into `calculate_position_size`
as a second optional keyword (`session: str | None = None`, multiplying
`risk_amount` alongside the existing `volatility` scalar — composition of
the two scalars is multiplicative and undisclosed-as-tested here; running
both flags together is out of scope for this hypothesis and should not be
assumed safe without its own check). New opt-in `BacktestEngine.run()`
parameter `session_scaled_sizing: bool = False` and CLI flag
`--session-scaled-sizing`, wired at the exact call site as
`vol_scaled_sizing` (`backend/app/backtesting/backtest_engine.py` ~line
715), computing the entry candle's UTC-hour session bucket immediately
before the sizing call and passing it as `session=...`; default `False`,
byte-identical to current behavior when unset — same discipline as every
existing opt-in flag in this project.

```
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2026-07-10 --session-scaled-sizing --walk-forward --delay-check
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2025-07-10 --session-scaled-sizing --walk-forward --delay-check
python scripts/run_backtest.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2024-07-10 --session-scaled-sizing --walk-forward --delay-check
```

compared directly against the already-recorded Legacy unscaled baseline
for all three years (`docs/LEGACY_DELAY_ROBUSTNESS.md`) — same trade
classification is expected (entries/stops/targets untouched, only
position size changes), so no re-run of the baseline is needed, mirroring
H4's own comparison method exactly.

**Keep-rule (declared now)**: unlike H4 (whose mechanism was already live
in production and whose keep-rule was framed around evidence integrity,
not promotion), H5 is a genuinely new, not-yet-live mechanism and gets a
real promotion-style keep-rule, matching H1/H2/H3's discipline. KEEP only
if, in AT LEAST 2 of the 3 tested years:

1. Max drawdown improves (decreases) relative to the unscaled baseline, AND
2. Net Profit does not degrade by more than ~10% relative to the unscaled
   baseline in ANY of the 3 years (not just the 2 counted toward
   condition 1) — mirroring the ~10% materiality band H4's own keep-rule
   used, and guarding against condition 1 being satisfied by a year where
   Net Profit was quietly given up to buy the drawdown improvement, AND
3. Delay-gate PF retention (already measured via `--delay-check`) does
   not newly fail relative to the already-recorded unscaled baseline in
   any year — sizing changes currency/variance-sensitive metrics, and
   `LEGACY_DELAY_ROBUSTNESS.md`'s STRUCTURAL verdict must not be
   silently invalidated by this change without being re-flagged, the
   same standing caveat H4's own evaluation raised for itself.

Any single condition failing, or the Step-0 gate failing outright, is
REJECT. A result that clears Step 0 but splits unevenly across conditions
1-3 (e.g., condition 1 holds in only 1 of 3 years) is REJECT under this
rule as written, not MIXED — MIXED is reserved for a keep-rule whose own
branches don't resolve to a single answer (H4's actual situation); this
rule's branches are not designed to leave that kind of ambiguity.

### Cost

Small-medium: reuses `volatility_risk_scalar`'s exact, already-validated
pattern (new function, same shape, same file) and `_SESSION_WINDOWS`'s
existing Asian/London constants (only `ny_other` is new, and it is a
derived "neither of the other two" bucket, not a new detector). Step 0
adds a genuine but cheap analysis-only pass (bucketing already-recorded
trade output by timestamp, no new indicator). Higher than H4 (which
needed zero new buckets and reused an already-live mechanism) because of
the new third session bucket and the mandatory Step-0 gate; lower than H2
(no new fill-timing/execution-simulation logic of any kind — this changes
WHAT SIZE gets sized, never WHEN or WHETHER a trade fills).

### Promotion path if KEEP

Explicitly NOT a promotion by itself, same boundary H1 and H4 already
drew around sizing/selection changes: altering the distribution of
per-trade risk by session is a real risk-and-behavior change to how
capital is deployed, squarely in the same operator-gated category
`ENGINEERING_DECISIONS.md` #62 already established for `MAX_TRADES_PER_DAY`
and #49 established for the volatility scalar itself. Before any
operator conversation: cross-asset (ETH/SOL/XRP) confirmation, since
this entire hypothesis is BTCUSDT-only evidence throughout (Test 6, the
Step-0 gate, and the Step-1 runs all default to BTCUSDT); and an explicit
check of `session_scaled_sizing` composed with the already-live
`vol_scaled_sizing` mechanism, deliberately left unchecked by this
pre-registration's own Step 1 (both scalars would apply multiplicatively
in production paper trading if both were ever enabled together, and that
composition has never been tested).

---

## 7. Rejected ideas

Per department mandate, ideas surveyed and explicitly rejected — either
because this platform's own evidence already falsifies the mechanism,
or because grounding was too weak relative to the hypotheses above.

- **Raising `MAX_TRADES_PER_DAY` directly.** The 89–92% signal-rejection
  finding (`docs/LEGACY_DELAY_ROBUSTNESS.md` §2, `ENGINEERING_DECISIONS.md`
  #62) is real, but `MAX_TRADES_PER_DAY` is a risk-limit constant, not a
  signal-quality parameter — changing it changes real aggregate risk
  exposure and is explicitly named in decision #62 as operator-gated
  territory, not a research-department call. H1 respects this boundary
  by re-ranking WITHIN the existing cap rather than proposing to raise
  it.
- **Asian-session-only entry filter.** Already A/B-tested and REJECTED
  in both tested years (`docs/CONTINUOUS_RESEARCH_LOG.md` Experiment
  3) — uniformly worse Net Profit, PF, and Sharpe despite a modest
  drawdown improvement, with trade count roughly halving each time.
  Motivated by the same Test 6 finding (`docs/ROBUSTNESS_REPORT.md`,
  Asian PF 4.65 vs. London 2.41) that also motivates H5 — the entry-
  filter form of this idea is closed; H5 (sizing, not filtering) is
  offered as a mechanistically distinct but still weakly-grounded
  variant, ranked last rather than excluded. **Full pre-registration
  now in section 6** (added 2026-07-19).
- **Naive ATR-multiple stop-distance floor (any multiple).** Directly
  A/B-tested and REJECTED (`docs/ATR_FLOOR_EVALUATION.md`) — at 1.5x,
  PF retention moved only 0.023 → 0.079 (still 6x below the 0.5
  criterion) while destroying walk-forward consistency (6/6 → 3/6
  profitable periods) and cutting Net Profit 67%. The 2.0x config was
  never run (early-stop, monotonicity argument) but the mechanism
  itself — uniformly widening stops — is falsified regardless of
  multiple: it thins the trade population without making the survivors
  delay-robust. Neither H2 nor H3 proposes reviving this mechanism; both
  are explicit about targeting a DIFFERENT mechanism (entry timing for
  H2, existing-candidate regime conditioning for H3).
- **Entry-confirmation drift gate (`max_entry_drift_pct`).** Already
  tested and REJECTED (`docs/CONTINUOUS_RESEARCH_LOG.md` Experiment 4)
  — helped partially in one year (2026, tightest gate) but provided
  essentially no benefit in the other (2025, every threshold still
  PF 0.11–0.22). This is the closest prior art to H2's mechanism and is
  why H2 is framed as a genuinely different model (resting passive
  limit vs. gating a still-immediate market fill), not a re-run of this
  rejected idea under a new name — and why H2 carries a materially
  higher evidentiary bar (both a cost-of-passivity check AND a
  delay-robustness check, both required) than this rejected experiment
  used.
- **Deep reinforcement learning for strategy discovery.** Already
  surveyed and REJECTED in `docs/RESEARCH_ROUND_1.md` §5 — RL needs MORE
  regime-labeled data than a simpler selector, not less, and this
  platform is evidence-starved in 8 of 9 regime buckets
  (`docs/REGIME_PERFORMANCE_ANALYSIS.md`). No new reason to revisit
  found this round.
- **HMM/Markov-switching regime detection.** Already surveyed and
  DEFERRED in `docs/RESEARCH_ROUND_1.md` §3 — the platform's diagnosed
  bottleneck is trade-RATE scarcity (too few trades per bucket), not
  regime-boundary instability; an HMM would not increase Legacy's trade
  rate. Still true this round; not revisited.
- **Full spread/L2 order-book modeling for a more rigorous H2.**
  Already correctly rejected in `docs/RESEARCH_ROUND_1.md` §2b/§5 — OKX's
  public candle endpoint carries no spread data, and full LOB
  simulation (`hftbacktest`-style) is disproportionate for a
  candle-resolution, one-person, paper-only platform. H2 deliberately
  proposes only the candle-only approximation this same document names
  as the honest middle ground, not this more rigorous (and infeasible)
  alternative.
- **Deflated Sharpe Ratio / PBO / SPA test as a gate for THIS round's
  results.** Correctly deferred in `docs/RESEARCH_ROUND_1.md` §1 — at
  n=20–60 per cell (the scale every experiment above will produce),
  these more sophisticated statistics mostly agree with the existing
  simple keep-rules; the bootstrap-confidence-gate ADOPT item from that
  round remains the right eventual upgrade once several buckets clear
  50+ trades, not before.

---

## 8. Recommended first experiment: H4

**Run H4 first**, ahead of H1–H3, for a reason distinct from its
ranking-table score: **its result conditions how every other
hypothesis's eventual numbers should be interpreted.** If closing the
backtest/live sizing gap materially changes drawdown, Sharpe, or
delay-gate retention on the standard anchors, then H1's and H3's
forthcoming backtest-only numbers (which will also be computed without
`--vol-scaled-sizing` unless this is run first and found to matter)
inherit the same blind spot this experiment exists to close. H4 is also
the cheapest experiment in this round by a wide margin (cost 1 vs. 2–4
for the others) and carries zero promotion risk — the mechanism it
tests is already live in production paper trading, so there is no
new-exposure decision waiting on this result, only a correctness
question about the evidence base itself.

**Second priority: H1.** It directly targets the single largest,
already-quantified, already-disclosed opportunity in this platform's
evidence base (89–92% of Legacy's own signal stream discarded by a
fixed daily cap, three years running) while explicitly respecting the
one boundary this project has already drawn around that finding (touch
selection, not the cap itself). It is the hypothesis in this round most
likely to produce an actual new, tradable insight rather than a
correctness fix (H4) or a conditional refinement of an existing,
already-validated candidate (H3) or a higher-cost exploratory build
(H2, H5).

---

## 9. Caveats

- **No result exists yet.** This document proposes experiments; it
  reports none. Every number cited above is drawn from prior, already-
  committed evidence documents, not from any run performed for this
  round.
- **One asset (BTCUSDT), one primary timeframe (15m) throughout** —
  matching the anchors specified for this round. None of these
  hypotheses have been checked against ETH/SOL/XRP; per this project's
  own standing discipline, no hypothesis here would be promoted past
  its own pre-registered keep-rule without that cross-asset step. **One
  disclosed exception**: H5's MOTIVATING evidence (Test 6) was measured
  on BTCUSDT 5m against the `structure_tp` candidate, not the 15m
  Legacy candidate H5 itself would size — section 6's Step 0 exists
  specifically to not let that mismatch pass silently into a keep-rule
  evaluated on the 15m standard.
- **Three of five hypotheses (H2, H3, H5) require new code before they
  can be run at all**, unlike H1 (research-script-only) and H4
  (near-trivial engine wiring). The ranking table's cost column already
  reflects this; it is restated here so the department's "many need
  zero new strategy code" framing is not read as applying uniformly to
  all five.
- **Every keep-rule above was declared in this document, before any
  run** — per the department's hard rule #1. A future evidence round
  that runs any of these experiments should quote the exact keep-rule
  from the relevant section above rather than restate it from memory,
  to keep the pre-registration honest.
