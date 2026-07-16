# Regime-Conditioned Performance Analysis — Round 2

Operator/CTO directive: Milestone 12, evidence round 2 (2026-07-16). First
regime-CONDITIONED performance comparison of the four quarantined
experimental strategies (`trend_following`, `range_trading`, `breakout`,
`volatility_expansion`) against the Legacy baseline, per
`docs/ADAPTIVE_ARCHITECTURE.md` section 4.3. Round 1
(`docs/EXPERIMENTAL_STRATEGY_EVALUATION.md`) established that no
experimental strategy beats Legacy OVERALL on BTC. The adaptive platform's
core thesis is regime-conditional edge — this round produces the first
per-regime evidence for or against that thesis. This is **evidence
collection only** — run, measure, record honestly. No parameters were
tuned, no strategy code was touched, no promotion decisions are made here.

## 1. Purpose and methodology

**Question**: even though every experimental strategy loses to Legacy in
aggregate on BTC 15m, is there ANY market-regime bucket in which one of
them credibly outperforms Legacy? That is the precondition for a future
`RollingPerformanceSelector` ever routing away from Legacy. Nothing more
is claimed or tested here.

**Anchor (identical to round 1, results directly comparable)**:
`scripts/analyze_regime_performance.py --symbol BTCUSDT --timeframe 15m
--candles 3000 --periods 6 --end-date 2026-07-10`. The tool fetched the
SAME 18,000 LTF (15m) candles and the SAME 1,125 HTF (4h) candles from
OKX exactly ONCE, then ran all five configurations over the identical
data, split into the same 6 non-overlapping chronological periods
(`split_into_periods`). Reproducibility check: every strategy's pooled
totals match round 1 exactly (legacy 111 trades / +$3,400.62; breakout
347 / -$5,329.19; range_trading 258 / -$2,321.08; trend_following 146 /
-$1,009.78; volatility_expansion 246 / -$892.45) — same data, same
engine, same trades.

**Regime tagging**: `BacktestEngine.run(..., tag_regimes=True)`
(Milestone 12a) calls `detect_market_regime` at each trade's ENTRY and
attaches the classification to the trade. Buckets are
`{trend}/{volatility}` pairs only (trend ∈ strong_trend / weak_trend /
range; volatility ∈ low / normal / high) — the three boolean event flags
are deliberately not part of the bucket key, matching the
`RollingPerformanceSelector`'s eventual lookup unit
(`app.backtesting.regime_analysis.regime_bucket`). Trades where regime
detection had insufficient history land in an explicit `untagged` bucket
rather than being dropped.

**Aggregation**: each strategy's trades are pooled across all 6 periods
before one `aggregate_by_regime()` call per strategy. Per-bucket metrics
are plain arithmetic over the trades in that bucket (win rate, total
PnL, expectancy = mean PnL/trade in currency, profit factor). The
20-trade confidence floor (`MIN_TRADES_FOR_CONFIDENCE = 20`, decision
#41) is applied per (strategy, bucket): rows below it are shown with an
explicit `(⚠ n<20)` marker, never hidden.

**Baseline** = the default `SignalEngine` path (`BacktestEngine.run()`
called without `strategy=`), i.e. actual production Legacy. Read-only
throughout: no orders placed, no writes to the trades DB, paper trading
untouched.

**Operational note / ESCALATION (code bug, not fixed per evidence-round
rules)**: the first run completed all five strategy backtests and then
crashed with `UnicodeEncodeError: 'charmap' codec can't encode character
'⚠'` at `print(table)` (`scripts/analyze_regime_performance.py`
line 274) — the `⚠` sample-floor marker from
`regime_analysis.comparison_table()` is not encodable on a Windows
cp1252 console, and because the console `print` happens BEFORE the file
write (line 278), the entire run's results were lost. Worked around by
re-running with `PYTHONUTF8=1` (environment change only; no code was
edited). All numbers below come from the successful second run
(`scripts/reports/regime_performance_run2.log`,
`scripts/reports/regime_performance_btc_2026.md`). Escalated for a
later engineering fix (write the file before printing, and/or make
console output encoding-safe). Neither run hit any OKX network failure.

## 2. Results table

Full output of the tool (source of every number in this document):

| Bucket | Strategy | Trades | Win Rate | Total PnL | Expectancy | Profit Factor |
|---|---|---|---|---|---|---|
| all | breakout | 347 | 26.51% | -5329.19 | -15.36 | 0.45 |
| all | legacy | 111 | 75.68% | 3400.62 | 30.64 | 4.38 |
| all | range_trading | 258 | 17.83% | -2321.08 | -9.00 | 0.71 |
| all | trend_following | 146 | 26.03% | -1009.78 | -6.92 | 0.68 |
| all | volatility_expansion | 246 | 34.55% | -892.45 | -3.63 | 0.84 |
| range/high_volatility | breakout | 8 (⚠ n<20) | 37.50% | 4.64 | 0.58 | 1.03 |
| range/high_volatility | legacy | 2 (⚠ n<20) | 50.00% | 27.45 | 13.72 | 1.83 |
| range/high_volatility | range_trading | 28 | 7.14% | -693.97 | -24.78 | 0.21 |
| range/high_volatility | volatility_expansion | 1 (⚠ n<20) | 0.00% | -25.40 | -25.40 | 0.00 |
| range/low_volatility | breakout | 52 | 23.08% | -1216.08 | -23.39 | 0.31 |
| range/low_volatility | legacy | 13 (⚠ n<20) | 84.62% | 516.60 | 39.74 | 7.72 |
| range/low_volatility | range_trading | 44 | 25.00% | 40.15 | 0.91 | 1.03 |
| range/low_volatility | volatility_expansion | 48 | 31.25% | -445.01 | -9.27 | 0.64 |
| range/normal_volatility | breakout | 46 | 23.91% | -694.58 | -15.10 | 0.45 |
| range/normal_volatility | legacy | 12 (⚠ n<20) | 75.00% | 363.82 | 30.32 | 4.18 |
| range/normal_volatility | range_trading | 53 | 16.98% | -397.51 | -7.50 | 0.76 |
| range/normal_volatility | volatility_expansion | 38 | 34.21% | -111.89 | -2.94 | 0.86 |
| strong_trend/high_volatility | breakout | 20 | 10.00% | -487.78 | -24.39 | 0.14 |
| strong_trend/high_volatility | legacy | 12 (⚠ n<20) | 75.00% | 362.77 | 30.23 | 4.52 |
| strong_trend/high_volatility | trend_following | 17 (⚠ n<20) | 35.29% | 7.41 | 0.44 | 1.02 |
| strong_trend/high_volatility | volatility_expansion | 6 (⚠ n<20) | 33.33% | -0.37 | -0.06 | 1.00 |
| strong_trend/low_volatility | breakout | 12 (⚠ n<20) | 16.67% | -288.36 | -24.03 | 0.23 |
| strong_trend/low_volatility | legacy | 6 (⚠ n<20) | 66.67% | 128.83 | 21.47 | 2.88 |
| strong_trend/low_volatility | trend_following | 11 (⚠ n<20) | 9.09% | -246.64 | -22.42 | 0.16 |
| strong_trend/low_volatility | volatility_expansion | 13 (⚠ n<20) | 30.77% | -89.79 | -6.91 | 0.70 |
| strong_trend/normal_volatility | breakout | 27 | 14.81% | -581.56 | -21.54 | 0.26 |
| strong_trend/normal_volatility | legacy | 8 (⚠ n<20) | 87.50% | 316.09 | 39.51 | 8.84 |
| strong_trend/normal_volatility | trend_following | 27 | 18.52% | -379.35 | -14.05 | 0.42 |
| strong_trend/normal_volatility | volatility_expansion | 21 | 28.57% | -136.85 | -6.52 | 0.72 |
| untagged | breakout | 16 (⚠ n<20) | 25.00% | -302.45 | -18.90 | 0.36 |
| untagged | range_trading | 5 (⚠ n<20) | 40.00% | 147.90 | 29.58 | 2.16 |
| untagged | trend_following | 6 (⚠ n<20) | 50.00% | 74.47 | 12.41 | 1.75 |
| untagged | volatility_expansion | 8 (⚠ n<20) | 50.00% | 50.57 | 6.32 | 1.35 |
| weak_trend/high_volatility | breakout | 44 | 40.91% | 47.49 | 1.08 | 1.06 |
| weak_trend/high_volatility | legacy | 16 (⚠ n<20) | 81.25% | 568.71 | 35.54 | 5.97 |
| weak_trend/high_volatility | range_trading | 28 | 7.14% | -775.79 | -27.71 | 0.16 |
| weak_trend/high_volatility | trend_following | 29 | 17.24% | -370.57 | -12.78 | 0.44 |
| weak_trend/high_volatility | volatility_expansion | 6 (⚠ n<20) | 50.00% | 96.31 | 16.05 | 2.14 |
| weak_trend/low_volatility | breakout | 42 | 28.57% | -889.37 | -21.18 | 0.34 |
| weak_trend/low_volatility | legacy | 14 (⚠ n<20) | 71.43% | 380.49 | 27.18 | 3.80 |
| weak_trend/low_volatility | range_trading | 36 | 19.44% | -148.04 | -4.11 | 0.87 |
| weak_trend/low_volatility | trend_following | 15 (⚠ n<20) | 33.33% | -37.71 | -2.51 | 0.88 |
| weak_trend/low_volatility | volatility_expansion | 49 | 30.61% | -470.27 | -9.60 | 0.61 |
| weak_trend/normal_volatility | breakout | 80 | 30.00% | -921.14 | -11.51 | 0.56 |
| weak_trend/normal_volatility | legacy | 28 | 71.43% | 735.86 | 26.28 | 3.30 |
| weak_trend/normal_volatility | range_trading | 64 | 20.31% | -493.81 | -7.72 | 0.74 |
| weak_trend/normal_volatility | trend_following | 41 | 31.71% | -57.39 | -1.40 | 0.93 |
| weak_trend/normal_volatility | volatility_expansion | 56 | 41.07% | 240.25 | 4.29 | 1.23 |

Missing (strategy, bucket) rows mean ZERO trades: `trend_following`
never traded in any `range/*` bucket, and `range_trading` never traded
in any `strong_trend/*` bucket — each module's own regime gate
(ADX-based trend/range filters) kept it out of its off-regime, which is
exactly what those gates are for. Legacy has no `untagged` row: all 111
Legacy trades received a real regime classification.

## 3. Honest analysis

### 3a. Is there ANY bucket where an experimental strategy credibly beats Legacy?

**No.** Applying the meaningful-signal bar — "beats Legacy in a bucket
with n≥20 on BOTH sides" — there is exactly **one** bucket where both
Legacy and at least one experimental strategy clear the floor:
`weak_trend/normal_volatility` (Legacy 28 trades — its only
sufficient-sample bucket, see 3b). In it, Legacy posts expectancy
**+26.28 / PF 3.30**, versus the best experimental,
`volatility_expansion`, at **+4.29 / PF 1.23** (56 trades). Legacy wins
the only head-to-head comparison this data can support, by roughly 6x
on expectancy.

At the weaker bar — experimental has n≥20 but Legacy's row in that
bucket is below the floor — only three experimental (strategy, bucket)
rows are positive at all:

| Bucket | Strategy | n | Expectancy | PF | Legacy in same bucket (small-sample) |
|---|---|---|---|---|---|
| range/low_volatility | range_trading | 44 | +0.91 | 1.03 | +39.74 / PF 7.72 (n=13 ⚠) |
| weak_trend/high_volatility | breakout | 44 | +1.08 | 1.06 | +35.54 / PF 5.97 (n=16 ⚠) |
| weak_trend/normal_volatility | volatility_expansion | 56 | +4.29 | 1.23 | +26.28 / PF 3.30 (n=28, sufficient) |

Two of these are effectively breakeven (PF 1.03 and 1.06 — well inside
noise/cost sensitivity), and in every one Legacy's numbers — even where
small-sample — are dramatically higher. There is no bucket, at any
evidence standard, where the data suggests routing away from Legacy
would have helped on this asset/window.

**A directional observation worth recording honestly**: the
regime-conditional pattern does exist in shape, just not in magnitude.
Each experimental strategy is least-bad (or marginally positive) in a
regime consistent with its design — `range_trading`'s only positive
bucket is `range/low_volatility` (its home regime), `trend_following`'s
only non-negative bucket is `strong_trend/high_volatility` (+0.44,
PF 1.02, but n=17, below the floor), and `volatility_expansion`'s only
sufficient-sample positive bucket carries a PF of 1.23. So conditioning
on regime moves these strategies from "clearly losing" toward
"breakeven" in their intended habitat — but nowhere does it move any of
them past breakeven-with-costs, let alone past Legacy. The
regime-conditional-edge thesis is **not supported** by this round for
this strategy set on this asset/window; at most it survives as "regime
gating reduces losses," which is not the thesis.

Contrast: `range_trading` in its OFF-regime volatility conditions is
catastrophic — `range/high_volatility` expectancy -24.78 / PF 0.21 and
`weak_trend/high_volatility` -27.71 / PF 0.16 (both n=28). If anything
in this table is actionable evidence, it is negative routing evidence
("never let range_trading trade high-volatility conditions"), not
positive routing evidence.

### 3b. Legacy's own regime profile — where is Legacy weakest?

Legacy is positive in **all nine** tagged buckets — no losing regime was
observed. But 8 of Legacy's 9 bucket rows are below the 20-trade floor
(n = 2, 6, 8, 12, 12, 13, 14, 16); only `weak_trend/normal_volatility`
(n=28) is a sufficient sample. So Legacy's weakest regime **cannot be
reliably identified from this data**. Taking the small-sample numbers
at face value (flagged as such): the lowest-expectancy Legacy rows are
`range/high_volatility` (+13.72, but n=2 — meaningless) and
`strong_trend/low_volatility` (+21.47 / PF 2.88, n=6). The one
confident statement available: in its single sufficient-sample bucket
(`weak_trend/normal_volatility`, also BTC 15m's most common regime by
trade counts), Legacy's expectancy (+26.28) and PF (3.30) run somewhat
BELOW its overall aggregate (+30.64 / 4.38) — i.e. Legacy is mildly
below its own average in the market's most frequent condition and makes
up for it in the rarer ones. Even Legacy-at-its-weakest outperforms
every experimental row in every bucket, so "where an alternative would
matter most" currently has no candidate to fill it.

### 3c. Buckets that are insufficient-sample everywhere

- **`strong_trend/low_volatility`**: no strategy reached 20 trades
  (max: volatility_expansion at 13). Nothing can be concluded about this
  regime — absence of evidence, not evidence.
- **`untagged`**: no strategy reached 20 trades (max: breakout at 16).
  These are trades where `detect_market_regime` had insufficient
  history at entry (early-period warmup); their scattered positive
  numbers for three strategies are small-sample noise, not signal.
- **`range/high_volatility`**: only `range_trading` cleared the floor
  (n=28, and it lost badly there); Legacy saw it exactly twice in six
  months. Rare regime on BTC 15m in this window.

Everything positive that an experimental strategy shows in an
insufficient-sample row (e.g. `volatility_expansion` +16.05 on n=6 in
`weak_trend/high_volatility`, `trend_following` +0.44 on n=17 in
`strong_trend/high_volatility`) is explicitly small-sample noise under
this project's own floor and is not treated as signal anywhere in this
document.

## 4. Implication for the platform (RollingPerformanceSelector)

The most consequential finding of this round is not about any
strategy — it is about **evidence accumulation rates**:

- **Legacy's per-regime evidence accumulates very slowly.** 111 trades
  over ~6 months spread across 9 buckets left Legacy with a sufficient
  sample in exactly ONE bucket (`weak_trend/normal_volatility`). At this
  trade rate, a `RollingPerformanceSelector` using a rolling window
  meaningfully shorter than 6 months would have **zero** buckets in
  which Legacy's own per-regime performance is measurable — and per
  ADAPTIVE_ARCHITECTURE.md 4.3, comparing an alternative against Legacy
  within a regime needs both sides of that comparison.
- **Only the dominant bucket is plausibly routable on BTC 15m.**
  `weak_trend/normal_volatility` is the only bucket where the
  20-trade floor is realistically reachable on both sides within a
  6-month window. `weak_trend/low`, `weak_trend/high`, `range/low`,
  `range/normal`, and `strong_trend/normal` fill for the
  higher-frequency experimental strategies but not for Legacy;
  `strong_trend/low`, `strong_trend/high`, and `range/high` barely
  occur. A 9-bucket routing table is, in practice on this asset/
  timeframe, a 1-bucket routing table plus fallback-to-legacy
  everywhere else.
- **The fallback design is doing exactly the right thing.** Given (a)
  most buckets are unroutable for lack of evidence and (b) in the one
  routable bucket Legacy wins by ~6x expectancy, a correctly implemented
  RollingPerformanceSelector run against this data would select Legacy
  in 9 of 9 buckets — 8 by insufficient-data fallback, 1 by argmax. The
  selector architecture is not invalidated by this round, but its
  premise (that there will eventually be a bucket where an alternative
  has both sufficient evidence AND better performance) has no supporting
  instance yet.
- **Shadow-mode recording (Milestone 11) is the right lever**: it
  accumulates per-regime evidence for every registered strategy on every
  paper pass without waiting for each strategy to be live, which is the
  only realistic way the sparse buckets ever reach the floor.

## 5. Caveats

- **One asset, one window**: BTCUSDT only, 15m, 2026-01-03 through
  2026-07-09. No claim about any other asset, timeframe, or macro
  environment. Same scope limits as round 1.
- **In-sample only**: all 6 periods are evidence; nothing held out. Same
  deliberate first-look tradeoff as round 1.
- **Disclosed-not-tuned rules**: the four experimental modules still run
  textbook, never-adjusted thresholds (`ENGINEERING_DECISIONS.md`
  #52(c)). "range_trading is ~breakeven in its home regime with untuned
  parameters" is a different statement from "range trading has no edge
  in ranges" — this round cannot distinguish them.
- **Regime measured at entry only**: a trade tagged
  `range/low_volatility` at entry may have resolved during a breakout;
  no exit-time or holding-period regime re-check exists. Per-bucket PnL
  attribution inherits that simplification.
- **Bucket boundary sensitivity**: trend/volatility bucket edges come
  from `detect_market_regime`'s fixed thresholds. Trades near a boundary
  could flip buckets under slightly different thresholds; with several
  buckets holding 20-60 trades, a boundary shift could move individual
  rows across the confidence floor. The headline findings (no
  experimental beats Legacy anywhere; Legacy insufficient-sample in 8/9
  buckets) are robust to this; exact per-bucket expectancies are not.
- **Expectancy is in currency (mean $/trade), not R-multiples**, and
  profit factor inherits `calculate_profit_factor`'s conventions.
  Cross-strategy comparison within a bucket is fair (identical account
  size, fees, slippage); cross-bucket magnitude comparison is looser.
- **Legacy's per-bucket numbers are mostly small-sample** (8 of 9 rows
  below the floor) — Legacy's PER-REGIME profile in section 3b is
  low-confidence by this project's own standard, even though Legacy's
  aggregate result (111 trades) is not.
- **No promotion recommendations are made, regardless of results** —
  same bar as round 1: promotion requires cross-asset AND cross-year AND
  out-of-sample evidence (`ADAPTIVE_ARCHITECTURE.md` 4.3 /
  `ENGINEERING_DECISIONS.md` #52(a)). Nothing here clears it, and this
  round found nothing that even suggests a candidate.
