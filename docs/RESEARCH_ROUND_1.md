# Research Round 1 — Established Quant Techniques vs. This Platform's Four Open Problems

Research Department deliverable (2026-07-16), CTO directive. Scope: survey
established quantitative-trading literature/industry practice against the
platform's four ACTUAL open problems (not a wishlist) and produce
adopt/defer/reject verdicts grounded in this platform's real constraints:
SQLite + pure-Python codebase (no numpy/scipy dependency today), a
one-person operation, paper-trading-only, and — the dominant constraint
threading through all four problems — an evidence-starved dataset (per
`docs/REGIME_PERFORMANCE_ANALYSIS.md`, 8 of 9 regime buckets sit below the
project's own 20-trade confidence floor; only one bucket has ever reached
it). No code was touched. No claim in this document is presented without a
named, checkable source; where a source could not be independently verified
beyond a search-engine summary, that is stated explicitly rather than
smoothed over.

---

## 1. Statistical rigor for strategy comparison at small samples

### 1a. What the literature says

- **Deflated Sharpe Ratio (DSR)** — Bailey, D.H. & López de Prado, M.
  (2014), *"The Deflated Sharpe Ratio: Correcting for Selection Bias,
  Backtest Overfitting and Non-Normality,"* *Journal of Portfolio
  Management* (SSRN 2460551; full text also at davidhbailey.com/dhbpapers/deflated-sharpe.pdf).
  Corrects a Sharpe ratio estimate for two effects: (i) selection bias from
  testing many strategy variants and reporting only the best (a multiple-
  comparisons correction based on the number of independent trials), and
  (ii) non-normality of returns (skewness/kurtosis) inflating the naive
  Sharpe estimate's apparent significance.
- **Probability of Backtest Overfitting (PBO)** — Bailey, D.H., Borwein,
  J., López de Prado, M., Zhu, Q.J. (2015/2016), *"The Probability of
  Backtest Overfitting,"* *Journal of Computational Finance* (SSRN 2326253).
  Introduces Combinatorially Symmetric Cross-Validation (CSCV): repeatedly
  splits a backtest's trial history into in-sample/out-of-sample halves,
  checks whether the strategy chosen as "best" in-sample also ranks well
  out-of-sample, and reports what fraction of splits it does not — directly
  targeting "we tried N variants and picked the winner," which is a form of
  data snooping distinct from a single-strategy significance test.
- **White's Reality Check (RC)** — White, H. (2000), *"A Reality Check for
  Data Snooping,"* *Econometrica* 68(5). Bootstrap-based joint test of
  whether the BEST of many candidate trading rules beats a benchmark by more
  than chance, once the search over all candidates is accounted for.
- **Hansen's SPA test** — Hansen, P.R. (2005), *"A Test for Superior
  Predictive Ability,"* *Journal of Business & Economic Statistics* 23(4),
  365–380. A refinement of White's RC using a studentized statistic and a
  sample-dependent null distribution; documented in the literature (Hsu,
  P-H. & Kuan, C-M. (2005), *"Re-Examining the Profitability of Technical
  Analysis with White's Reality Check and Hansen's SPA Test,"* *Journal of
  Financial Econometrics* 3(4), 606–628) as more powerful than RC because RC
  is conservative under its "least favorable configuration" null and loses
  power when many weak/irrelevant candidate rules are included alongside a
  few good ones.
- **Bayesian A/B approaches**: general treatments (Dynamic Yield's Bayesian
  A/B testing guide; Stefan/industry Bayesian A/B literature surveyed via
  search) converge on the same practical point relevant here — Bayesian
  methods report a posterior probability that A beats B and an expected
  loss from choosing wrongly, rather than a binary reject/fail-to-reject
  call, and degrade gracefully (wide, honest posteriors) at small n instead
  of just reporting "insignificant." No trading-specific Bayesian A/B paper
  with a citable, peer-reviewed methodology specific to expectancy
  comparison was found in this search round; the recommendation below is
  built from the general Bayesian-inference framework, not a single named
  trading paper.

### 1b. Candidates vs. our constraints

**Constraint that dominates this problem**: per `docs/REGIME_PERFORMANCE_ANALYSIS.md`
section 4, 8 of 9 regime buckets have never reached the existing n≥20
floor, and the one bucket that has (`weak_trend/normal_volatility`, n=28
Legacy / n=56 best challenger) already shows Legacy winning by ~6x on
expectancy — not a close call needing finer statistics to resolve. Any
technique's real test is: **at n=20–60, does it change any decision the
current strict-inequality-plus-floor rule (`app/strategy/selector.py`,
decision #56) wouldn't already reach?**

| Technique | Verdict | Reasoning |
|---|---|---|
| Deflated Sharpe Ratio | **DEFER** | DSR's own correction terms need reliable skewness/kurtosis estimates — 3rd/4th central moments are unstable well above n=20 (the standard error of a Sharpe-ratio estimate itself is roughly `sqrt((1 + 0.5·SR²)/n)`, i.e. still large at n=20–60). At our current sample sizes DSR would almost certainly report "cannot distinguish from noise" — the same conclusion the existing n≥20 floor already reaches by simpler means, at the cost of implementing moment-based corrections this stdlib-only codebase has no existing machinery for (no numpy/scipy today). Revisit once several buckets carry 50+ trades each. |
| Probability of Backtest Overfitting (CSCV) | **DEFER, but flag the underlying warning as immediately relevant** | CSCV needs multiple genuinely independent in/out-of-sample splits per strategy — we have single-window backtests (`docs/EXPERIMENTAL_STRATEGY_EVALUATION.md`, `docs/REGIME_PERFORMANCE_ANALYSIS.md`), not the repeated-split history CSCV is built to consume. However, PBO's core INSIGHT — correct for the number of trials being compared — is directly applicable *conceptually* to `RollingPerformanceSelector`: it performs an implicit argmax search over up to 5 challenger strategies × 10 buckets × 2 sources (shadow/live) without any multiple-comparisons correction. This is exactly the data-snooping shape White/Hansen and Bailey et al. warn about. Full CSCV is deferred; the multiple-comparisons *discipline* (see 1c) is not. |
| White's Reality Check / Hansen's SPA test | **DEFER** | Both are bootstrap tests over the joint distribution of (best-candidate-minus-benchmark) statistics — computable in pure Python via block-bootstrap resampling of trade sequences (no numpy required, `random.choices` suffices), so this is NOT ruled out by our dependency constraint. It IS ruled out by sample size: the original papers apply these tests to thousands of trading rules over decades of daily return data; at n=20–60 trades per cell, a bootstrap over so few points has very low power and a stationary-bootstrap block-length choice becomes another disclosed-not-tuned parameter layered on top of already-thin data. This is the conceptually correct long-run test for "does RollingPerformanceSelector's argmax-over-challengers beat picking Legacy by chance," and should be revisited once multiple cells clear ~50 trades. |
| Bootstrap confidence on the expectancy GAP (nonparametric, stdlib-only) | **ADOPT** | Not a named paper — a standard nonparametric technique (resample-with-replacement from the actual trade set, recompute mean(challenger R) − mean(legacy R) each resample, report the fraction of resamples where the challenger wins). Implementable in pure Python (`random.choices` + `statistics.mean`, no new dependency), works at any n (correctly reports WIDE, uninformative intervals at n=20 rather than fabricating false confidence — the same "don't fabricate an answer" discipline already governing every existing detector in this codebase), and directly extends (does not replace) the existing strict-inequality gate with an actual confidence number instead of a bare `>`. |

### 1c. Concrete integration point (ADOPT item)

- **Module**: `app/portfolio/rolling_regime_performance.py` gains a new pure
  function, e.g. `bootstrap_expectancy_gap(challenger_r_values,
  legacy_r_values, n_resamples=2000, seed=...) -> (prob_challenger_better,
  ci_low, ci_high)`, consumed by `select_for_bucket()` in
  `app/strategy/selector.py` as an ADDITIONAL gate layered on top of (not
  replacing) the existing `min_samples` floor and strict-inequality rule —
  e.g. require `prob_challenger_better >= 0.95` in addition to today's
  point-estimate check.
- **Size estimate**: small — roughly 80–150 lines including tests, no new
  dependency (stdlib `random` + `statistics` only, consistent with the
  "pure-Python" constraint).
- **Evidence that would validate it**: run it against the real accumulated
  dataset once more buckets clear n≥20, and check whether it EVER produces
  a different decision than the current strict-inequality rule on the same
  data — i.e. a case where the point-estimate says "challenger wins" but
  the bootstrap says "not confident enough." That divergence is the actual
  proof this earns its added complexity; today's single sufficient-evidence
  bucket (Legacy winning by ~6x) would not show a divergence, so this
  cannot be validated meaningfully until more evidence exists — consistent
  with it being an ADOPT-for-later rather than an urgent gap.
- **Multiple-comparisons discipline (process-level, not code)**: as more
  buckets accumulate n≥20 simultaneously, the number of implicit
  comparisons `RollingPerformanceSelector` makes per report grows. Per
  White/Hansen/Bailey's shared warning, this is the point to either widen
  the required bootstrap confidence threshold or apply a simple Bonferroni-
  style correction (`required_confidence = 1 - alpha/num_active_buckets`)
  — flagged here as a future trigger condition, not built now, since with
  only one currently-active bucket there is nothing yet to correct for.

---

## 2. Realistic shadow-fill modeling

### 2a. What the literature/industry says

- Practitioner consensus (Alpaca Community Forum thread, "Slippage - Paper
  Trading vs. Real Trading," forum.alpaca.markets/t/slippage-paper-trading-vs-real-trading/2801)
  is that paper/shadow fills systematically understate real-world cost
  because they assume idealized execution; the fix cited there is
  explicitly "shadow fill simulation that respects slippage and fees."
- QuantStart (Michael Halls-Moore), *"Successful Backtesting of Algorithmic
  Trading Strategies – Part II"* — a widely-cited practitioner reference —
  states that backtests/simulations must explicitly model transaction
  costs and fill mechanics or they will "significantly outperform live
  trading."
- Standard retail/quant backtesting convention (reflected across multiple
  backtesting-framework docs found in this search, and consistent with
  this platform's OWN prior work): fill orders at the NEXT bar's open
  rather than the signal bar's close/price, both to avoid look-ahead bias
  and to approximate real dispatch latency.
- This platform's own `docs/ROBUSTNESS_REPORT.md` (Test 2) already built
  and validated exactly this mechanism — `entry_delay_candles` in
  `BacktestEngine` — and found it is not a cosmetic adjustment: a 1-candle
  (~5 min) delay flipped the only validated candidate from PF 5.24 to PF
  0.16. That is first-party, already-collected evidence, not literature.

### 2b. Candidates vs. our constraints

| Technique | Verdict | Reasoning |
|---|---|---|
| Fee + slippage injection into shadow fills | **ADOPT** | Trivial in-scope change: `paper_broker.py` already carries the constants (0.05% fee, 0.02% slippage per leg) that both `BacktestEngine` and real paper trades already use. `app/portfolio/shadow_resolver.py`'s `resolve_open_shadow_signals()` currently computes `resolved_r` fee-free (decision #55(c), explicitly disclosed as "an OPTIMISTIC UPPER BOUND"). Applying the SAME already-existing constants closes the gap with zero new tuning and zero new invented thresholds — pure reuse. |
| Next-candle-open (delay ≥1) fill for shadow signals | **ADOPT** | This is not a new technique for this codebase — it is the SAME `entry_delay_candles` mechanism `docs/ROBUSTNESS_REPORT.md` Test 2 already built, tested, and validated as materially consequential. Currently shadow evidence resolves from the SAME candle the signal fired on — i.e. shadow evidence is blind to precisely the one failure mode this platform has already observed killing a real candidate. This is the single highest-leverage, lowest-novelty fix available: reuse already-proven code against a data source (shadow) that currently lacks it. |
| Spread modeling | **REJECT for now (data does not exist)** | `docs/ADAPTIVE_ARCHITECTURE.md` section 2.2 already discloses that OKX's public candle endpoint carries no bid/ask spread (same limitation already named for volume delta) — spread modeling would require a genuinely new market-data source (tick or L2 order-book data), a materially larger scope change than fee/slippage/delay, for a cost component `docs/ROBUSTNESS_REPORT.md`'s own Tests 3–4 suggest is smaller in magnitude than fees/slippage on liquid BTC/major-pair venues. Named explicitly as a disclosed gap, not silently dropped. |

### 2c. Concrete integration point (ADOPT items)

- **Module**: `app/portfolio/shadow_resolver.py`. Two additive changes to
  `resolve_open_shadow_signals()`: (1) apply the existing
  `paper_broker.py` fee/slippage constants to the entry and exit legs
  before computing `resolved_r` (mirrors how `BacktestEngine` already
  applies them); (2) start the outcome-resolution candle walk from
  `captured_at + 1 candle` using that candle's open as the effective fill
  price, keeping stop/target at their original structural levels —
  matching Test 2's exact methodology in `docs/ROBUSTNESS_REPORT.md`, so
  the two results stay directly comparable.
- **Size estimate**: small (fee/slippage) + small–medium (entry delay,
  since it touches the resolver's candle-walk start point and must respect
  the already-known SQLite naive-datetime lesson from decision #55(d)) —
  roughly 80–150 lines including tests combined.
- **Evidence that would validate it**: (a) shadow-side `resolved_r`
  distributions should shift down by an amount consistent with round-trip
  fee+slippage as a fraction of typical stop distance — a predictable,
  checkable shift, not a hoped-for one; (b) re-run `scripts/shadow_status.py`
  / the milestone-15 evidence layer before/after and confirm the
  shadow-vs-live expectancy gap (where both exist) shrinks, since the
  known optimism source is now partially removed; (c) most importantly —
  does adding entry-delay measurably compress or reverse any shadow
  strategy's apparent edge, the way it did for the one real validated
  candidate? A "no" would itself be informative (this platform's untested
  experimental strategies may have wider stops than the killed
  `structure_tp` candidate's 0.17–0.23%-of-price stops — worth knowing
  either way).

---

## 3. Regime detection robustness

### 3a. What the literature says

- **Hamilton, J.D. (1989), "A New Approach to the Economic Analysis of
  Nonstationary Time Series and the Business Cycle,"** *Econometrica*
  57(2), 357–384 — the foundational Markov-switching model: regime is a
  latent state following a Markov chain, with regime-dependent parameters
  (mean, variance, sometimes AR dynamics) for the observed series. This is
  the origin of "HMM for regime detection" as applied in finance.
  Multiple 2024–2026-era research pieces surfaced in this search apply
  Hamilton-style or Gaussian HMMs specifically to Bitcoin/crypto regime
  classification (e.g. an academia.edu-hosted paper titled *"Markov and
  Hidden Markov Models for Regime Detection in Cryptocurrency Markets:
  Evidence from Bitcoin (2024–2026)"* — flagged explicitly as NOT
  independently verified as peer-reviewed; academia.edu hosts both
  published and unpublished/preprint material, and this paper's specific
  quantitative claims were not independently checked beyond the search
  summary, so it is cited here as directional evidence of research
  activity in this space, not as a verified quantitative result).
- The differentiator HMMs offer over threshold-rule classifiers, and the
  one directly relevant to "what property matters for routing," is
  explicit modeling of **persistence** (probability of staying in a state)
  and **transition** probabilities as fitted parameters — i.e. an HMM is
  built specifically to answer "how sticky is this regime," which a
  fixed-threshold rule (ADX ≥ 25 this candle vs. last candle) does not
  model at all.
- Static/rule-based classifiers (what this platform uses) are commonly
  described in the surveyed sources as cheap and good at labeling the
  CURRENT observation but "weak on persistence" by construction, since
  they have no memory of prior state.
- GARCH-family models (Bollerslev 1986, building on Engle's ARCH) are
  standard for modeling volatility clustering, including in crypto — search
  results confirm GARCH/EGARCH variants are actively applied to Bitcoin
  volatility forecasting, with realized-volatility-based HAR models cited
  as often outperforming plain GARCH on high-frequency data.

### 3b. Candidates vs. our constraints

**Constraint that dominates this problem**: `docs/REGIME_PERFORMANCE_ANALYSIS.md`
section 4 already diagnosed the platform's actual bottleneck, and it is
NOT regime-boundary noise — it is **trade-rate scarcity**: "Legacy's
per-regime evidence accumulates very slowly. 111 trades over ~6 months
spread across 9 buckets left Legacy with a sufficient sample in exactly
ONE bucket." No prior analysis in this codebase has evidenced that regime
buckets are unstable, flapping, or mis-transitioning — the diagnosed
problem is that too few TRADES land in most buckets at all, independent of
how cleanly those buckets are defined.

| Technique | Verdict | Reasoning |
|---|---|---|
| HMM / Markov-switching regime classifier | **DEFER** | Real literature support (Hamilton 1989; multiple crypto-specific 2024–2026 applications) for the specific property this problem statement asks about (persistence/transition stability). But: (a) it requires either a new numpy/scipy dependency (`hmmlearn`, the standard Python implementation) or a hand-rolled Baum-Welch EM fitter — either is a first for this codebase, where every existing detector (`ADX`, swing structure, liquidity sweeps, FVG) is closed-form/rule-based with zero iterative optimization anywhere; (b) it does not address the bottleneck `docs/REGIME_PERFORMANCE_ANALYSIS.md` actually identified — fewer, more-persistent regime states would not increase Legacy's trade RATE, which is the thing starving 8 of 9 buckets. Revisit only if a FUTURE analysis specifically implicates regime-boundary flapping (rapid reclassification) as a real contributor to sample fragmentation — that evidence does not exist yet. |
| Hysteresis / minimum-dwell-time smoothing on the EXISTING ADX/volatility classifier | **ADOPT** | Directly targets "fewer transitions, better persistence" — the literal property named in the problem statement — without any new statistical framework: only reclassify `trend`/`volatility` once the new label has held for N consecutive detector calls. Reuses 100% of existing `detect_market_regime()` logic; needs only a small amount of explicit state passed in by the caller (consistent with this project's existing pattern of caller-computed state, e.g. `RiskManager.evaluate(strategy_disabled: bool)`, `ADAPTIVE_ARCHITECTURE.md` 5.2), not hidden inside the detector. Cheap, low-risk, testable in isolation. |
| Realized-volatility terciles / GARCH-lite as a volatility-measure upgrade | **REJECT for now** | Not hype — a real, standard technique — but redundant with what's already built: `detect_market_regime`'s volatility bucketing is ALREADY percentile-based over a rolling window (75th/25th percentile ⇒ high/low), which is functionally a tercile-style classification. `docs/REGIME_PERFORMANCE_ANALYSIS.md` never flagged volatility-bucket instability as a contributor to evidence starvation — the diagnosed problem is trend-bucket trade scarcity, and GARCH would only refine the volatility axis. Building it now would be solving a problem with no cited supporting evidence, which is exactly the standard this project holds every other threshold to (`ENGINEERING_DECISIONS.md` #18, #52(c)). |

### 3c. Concrete integration point (ADOPT item)

- **Module**: `app/regime/regime_detector.py::detect_market_regime()` — add
  an optional `prior_classifications: list[MarketRegime] | None` parameter
  (caller-supplied, matching the existing "state passed in explicitly"
  pattern) and a small `min_dwell_candles` (disclosed-not-tuned default,
  e.g. 2–3) rule: only flip the `trend`/`volatility` label if the new
  classification would also have held for the last `min_dwell_candles`
  calls; otherwise report the PRIOR sticky label (event flags — breakout/
  mean_reversion/liquidity_sweep_environment — stay un-smoothed, since
  they are already designed as instantaneous event markers, not standing
  states).
- **Size estimate**: small — roughly 40–80 lines including tests.
- **Evidence that would validate it**: re-run
  `scripts/analyze_regime_performance.py` on the SAME BTCUSDT anchor used
  by `docs/REGIME_PERFORMANCE_ANALYSIS.md` with smoothing on vs. off, and
  check (a) whether bucket-transition counts drop, and (b) whether any
  bucket's trade count materially shifts as a result (evidence that fewer,
  stickier buckets help floor-filling) versus staying flat (evidence this
  wasn't the actual bottleneck, matching the REJECT verdict on GARCH
  above). This is a cheap, falsifiable check — if it shows no effect, that
  itself is useful, confirming trade-rate scarcity is the real lever, not
  classifier smoothness.

---

## 4. Execution-delay robustness

### 4a. What the literature/industry says

This is the one problem area where this platform already HAS first-party,
already-collected experimental evidence (`docs/ROBUSTNESS_REPORT.md` Test
2) rather than only literature — the research task here is to check that
evidence against established practice, not to import a new idea cold.

- Wilder, J.W. (1978), *New Concepts in Technical Trading Systems* —
  origin of the Average True Range (ATR) indicator. Standard, widely
  documented practitioner convention (corroborated across multiple
  independent sources found in this search — TradeSignal, IG, FTMO
  Academy, OANDA, TrendSpider): stops sized as a MULTIPLE of ATR (commonly
  1.5×–3× ATR), not as a fixed percent of price, specifically so stop
  distance scales with the asset's own normal noise level rather than
  being an arbitrary constant that can be tighter than ordinary price
  movement.
- Multiple sources on latency/execution (mt4copier, tradesignal.tech,
  holaprime, QuantStart Part II) converge on the same structural point:
  backtests that assume instantaneous zero-latency fills systematically
  overstate live performance, and the standard mitigation named across
  these sources is modeling delay/slippage explicitly in the backtest
  itself, not merely disclosing it as a caveat afterward.
- `nkaz001/hftbacktest` (GitHub) — an open-source backtesting engine that
  models limit orders, queue position, and network/exchange latency using
  full L2 tick data, with real crypto (Binance/Bybit) examples — cited here
  as the honest reference point for what FULL latency-aware backtesting
  looks like in practice, and, by direct comparison, why it is
  disproportionate for this platform (see 4b).
- **This platform's own evidence** (`docs/ROBUSTNESS_REPORT.md` Test 2,
  Test 7): the only validated production candidate had an average stop
  distance of 0.23% of entry price (minimum 0.17%) — a single 5-minute
  delay flipped it from PF 5.24 to PF 0.16, and the report's own root-cause
  analysis states this plainly: *"Normal price movement over even one
  5-minute candle can be comparable to or exceed that distance."* This is
  a mechanistically identified, not merely observed, failure.

### 4b. Candidates vs. our constraints

| Technique | Verdict | Reasoning |
|---|---|---|
| Minimum stop-distance-as-ATR-multiple gate | **ADOPT** | Directly treats the ROOT CAUSE `docs/ROBUSTNESS_REPORT.md` itself identified mechanistically — a stop tighter than normal single-candle price movement. ATR is already computed in this codebase (`app.strategy.utils.average_true_range`, `ADAPTIVE_ARCHITECTURE.md` 2.2); `RiskManager.evaluate()` already gates on an RR floor (`settings.MIN_RR`) in an analogous way, so this is a natural sibling check, not a new architectural concept. |
| Standardize execution-delay testing (`entry_delay_candles`) as a REQUIRED promotion-gate check, not an ad hoc one-off | **ADOPT** | Zero new code — `entry_delay_candles` already exists, tested, and validated in `backend/app/backtesting/backtest_engine.py` (built for `docs/ROBUSTNESS_REPORT.md`). It is currently invoked only from one standalone script (`scripts/robustness_report.py`), run once, at the END of a long validation chain (Monte Carlo, slippage, fees, sessions, leverage) — meaning a future candidate could burn significant validation effort before this single, already-known-to-be-decisive check ever runs. Promoting it into `scripts/run_backtest.py`'s existing `walk_forward_report()` (decision #8's PASS/FAIL gate machinery) as a required criterion is a pure process change with no new statistical or engineering risk. |
| Limit-entry-with-timeout (resting limit order, cancel-if-unfilled-after-N) | **DEFER** | A real, standard technique (avoids chasing a moved market with a marketable order). But this platform is paper-only against OKX CANDLE data — no live order book, no L2/tick feed, no real order-matching engine. Implementing this meaningfully needs either a genuinely new data source (same class of gap already disclosed for volume delta and spread, `ADAPTIVE_ARCHITECTURE.md` 2.2) or a synthetic candle-only approximation whose benefit is largely REDUNDANT with the ATR-stop-floor recommendation above — both target the same root cause (stop too tight relative to normal price movement) at very different implementation costs. Revisit once live-trading infrastructure work begins (`ADAPTIVE_ARCHITECTURE.md` Phase 1 gate #4, still gated). |

### 4c. Concrete integration point (ADOPT items)

- **Minimum stop-distance-as-ATR-multiple gate** — module:
  `app.risk.risk_manager.RiskManager.evaluate()`. Add an optional,
  disclosed-not-tuned parameter (e.g. `min_stop_distance_atr_multiple:
  float | None = None`, defaulting to off, per decision #10's
  opt-in-before-default-change pattern), computed from the same ATR
  helper already used by the regime detector, rejecting a signal whose
  stop distance is below the multiple (starting point: 0.5×–1× ATR,
  matching Wilder's own convention scaled down since Wilder's 1.5×–3× was
  designed as the full stop distance, not merely a rejection floor).
  Size estimate: small (~30–50 lines including tests).
- **Standardized delay-robustness gate** — module: `scripts/run_backtest.py`'s
  `walk_forward_report()` (decision #8). Add a required check: PF at
  `entry_delay_candles=1` must retain at least some disclosed fraction
  (e.g. 0.5×) of the zero-delay PF, alongside the existing
  profitable-period-ratio / consecutive-losing-period / first-half-vs-
  second-half checks. Size estimate: small (~20–40 lines — the delay
  mechanism itself needs no new code, only a new PASS/FAIL criterion using
  what already exists).
- **Evidence that would validate both**: re-run
  `scripts/robustness_report.py` Test 2 against the `structure_tp`
  candidate WITH the new ATR-floor gate applied retroactively — the
  concrete falsifiable claim is that the gate would have REJECTED that
  candidate's configuration (0.17–0.23%-of-price stops) before it ever
  reached the robustness round, using data this platform already
  collected. If the gate does NOT reject it, that is a real negative
  result worth recording, not something to quietly adjust the threshold
  to force a pass.

---

## 5. Hype rejected

Each item below was surveyed and explicitly rejected, with reasoning tied
to this platform's real constraints — not rejected by default skepticism.

- **Deep reinforcement learning for strategy discovery/selection.**
  Multiple 2025–2026 sources found in this search (e.g. arXiv 2209.05559,
  *"Deep Reinforcement Learning for Cryptocurrency Trading: Practical
  Approach to Address Backtest Overfitting"* — note the paper's OWN title
  concedes the overfitting problem it's trying to patch; Ezgi Korkmaz's
  *"A Survey on Generalization in Deep Reinforcement Learning"*, NeurIPS
  2023) consistently report RL agents overfitting to training-period
  dynamics and failing to generalize under regime drift — the exact
  failure mode `docs/ADAPTIVE_ARCHITECTURE.md` section 4.3 already
  anticipated when it explicitly deferred ML-based strategy selection
  "until real data exists to learn from." This platform doesn't have that
  data yet (8/9 buckets evidence-starved) and RL specifically needs MORE
  data than a simpler selector, not less. Consistent rejection, not a new
  one.
- **Full HMM/GARCH regime-detection machinery, right now.** Real technique
  (see section 3), rejected for THIS round specifically because it adds a
  first-ever iterative-optimization dependency to a codebase built entirely
  on closed-form detectors, to solve a problem (regime instability) that
  has never actually been evidenced as this platform's bottleneck — trade
  scarcity has.
- **Bid/ask spread modeling for shadow fills.** No data source exists (OKX
  public candle endpoint carries no spread data, same disclosed limitation
  already named for volume delta) — would require a new market-data
  integration, not a modeling change.
- **Full LOB/queue-position latency simulation (hftbacktest-style).**
  Real, rigorous, and the honest gold standard for HFT/market-making —
  wildly disproportionate for a candle-resolution, one-person, paper-only
  platform with no tick/L2 feed. The ATR-stop-floor + standardized
  delay-gate combination (section 4) captures the practically relevant
  share of this benefit at a small fraction of the engineering cost.
- **Deflated Sharpe Ratio / PBO / SPA test, built as production machinery
  TODAY.** Not rejected as WRONG (see section 1) — rejected as premature:
  at n=20–60 per cell, more sophisticated statistics mostly agree with the
  existing simple floor, so building them now would add real complexity
  for a bar the platform hasn't approached yet.
- **Walk-forward PARAMETER REFITTING as a generic new capability.**
  Already directly addressed and rejected in this codebase's own history
  (`ENGINEERING_DECISIONS.md` #8) — the strategy has no tunable/fitted
  parameters today, so a refitting loop would have nothing to refit.
  Re-surveyed for this round and found no new reason to reverse that
  decision; noted for consistency rather than re-litigated.
- **Limit-order-with-timeout entry simulation, right now.** See section
  4b — deferred, not rejected outright, but grouped here because it is the
  kind of "sounds obviously better" idea this project's own history
  (`ENGINEERING_DECISIONS.md` #17, the confluence-strength finding) has
  repeatedly shown does NOT automatically hold without real evidence; it
  needs live-trading infrastructure this platform doesn't have yet to be
  tested honestly rather than assumed.

---

## 6. Top-3 prioritized recommendations for the CTO

1. **Standardize execution-delay testing (`entry_delay_candles`) as a
   required promotion-gate criterion in `scripts/run_backtest.py`'s
   `walk_forward_report()`**, not an ad hoc one-off script run at the end
   of validation. Zero new code (the mechanism is already built and
   already proved decisive), pure process change, and directly prevents
   recurrence of the exact failure mode that already killed this
   platform's only validated candidate — before future validation effort
   is spent on a candidate that would die on delay alone.

2. **Add a minimum stop-distance-as-ATR-multiple gate to
   `RiskManager.evaluate()`**, reusing the already-built ATR helper. This
   treats the ROOT CAUSE `docs/ROBUSTNESS_REPORT.md` mechanistically
   identified (a stop tighter than one candle's normal price movement),
   not just the symptom, and is directly falsifiable against data this
   platform already collected (would it have rejected the `structure_tp`
   candidate's 0.17–0.23%-of-price stops before the robustness round ever
   ran?).

3. **Inject fee/slippage (reusing existing `paper_broker.py` constants)
   and entry-delay (reusing the already-validated `entry_delay_candles`
   mechanism) into `app/portfolio/shadow_resolver.py`**. Shadow-mode
   recording is explicitly the platform's own identified "right lever" for
   filling evidence-starved buckets faster than live trading alone
   (`ENGINEERING_DECISIONS.md` #54); if `RollingPerformanceSelector` is
   ever wired to consume that evidence for a real promotion decision, it
   must not be consuming numbers built on the exact two assumptions
   (fee-free, zero-delay) already proven — by this platform's own
   robustness testing — to matter.

Honorable mentions not in the top 3, both real and correctly scoped as
lower-urgency: the bootstrap confidence gate on `RollingPerformanceSelector`
(section 1c — correct, but with only one evidence-sufficient bucket today
and Legacy winning it by ~6x, it wouldn't change any current decision) and
regime-classifier hysteresis smoothing (section 3c — cheap and directly
answers the problem statement's own framing, but `docs/REGIME_PERFORMANCE_ANALYSIS.md`
never actually evidenced regime-boundary instability as the bottleneck, so
it's a reasonable bet rather than an evidenced fix).

---

## 7. Caveats

- This document surveys techniques against a specific, disclosed set of
  four problems and this platform's actual current evidence base
  (`docs/REGIME_PERFORMANCE_ANALYSIS.md`, `docs/ROBUSTNESS_REPORT.md`,
  `ENGINEERING_DECISIONS.md` #52–#57) as of 2026-07-16. No new backtests,
  code changes, or data collection were performed as part of this
  research round — every "Evidence that would validate it" note above
  describes a FUTURE falsification test, not a result already obtained.
- Several web sources (search-engine-summarized rather than directly
  fetched and read in full) are cited with the caveat noted inline where
  their claims could not be independently verified beyond the summary —
  most notably the academia.edu crypto-HMM paper in section 3a. Named
  academic papers with SSRN/journal identifiers (Bailey & López de Prado,
  Bailey/Borwein/López de Prado/Zhu, White, Hansen, Hamilton) are
  well-established, widely-cited works; their existence and core claims
  are not in question, though this round did not re-derive their proofs.
  Prior generalization-critique claims about deep RL (arXiv 2209.05559
  and the Korkmaz NeurIPS survey) are treated the same way — cited by
  title/venue as found, not re-verified line-by-line.
- No recommendation in this document authorizes any code change on its
  own — per department scope, this is a research/proposal deliverable
  only. Every ADOPT item explicitly follows this project's own
  established "opt-in flag before any default change" discipline
  (`ENGINEERING_DECISIONS.md` #10) and would need its own
  implementation, tests, and evidence round before promotion, exactly
  like every other feature in this codebase's history.
