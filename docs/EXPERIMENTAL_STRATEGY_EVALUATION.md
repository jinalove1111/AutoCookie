# Experimental Strategy Evaluation — Round 1

Operator/CTO directive: Milestone 10, evidence round 1 (2026-07-16). First
backtest evaluation of the four quarantined experimental strategy modules
(`trend_following`, `range_trading`, `breakout`, `volatility_expansion`,
shipped Milestone 8 / `ENGINEERING_DECISIONS.md` #52) against the Legacy
baseline, per `docs/ADAPTIVE_ARCHITECTURE.md` section 7's evidence-gated
promotion discipline. This is **evidence collection only** — run, measure,
record honestly. No parameters were tuned, no strategy code was touched,
no promotion decisions are made here.

## 1. Purpose and methodology

**Question**: do any of the four experimental `Strategy`-Protocol modules
show enough edge on one asset, one recent window, to justify spending more
compute on cross-asset/cross-year validation? Nothing more is claimed.

**Anchor (identical across all five runs)**: `--symbol BTCUSDT --timeframe
15m --candles 3000 --periods 6 --end-date 2026-07-10 --walk-forward`. Every
configuration fetched the SAME 18,000 LTF (15m) candles and the SAME 1,125
HTF (4h) candles from OKX, split into the same 6 non-overlapping
chronological periods (`split_into_periods`, oldest → newest, 2026-01-03
through 2026-07-09). No configuration ever saw a different candle than any
other — apples-to-apples by construction (`scripts/run_backtest.py`'s
signal-source-only injection design, `ENGINEERING_DECISIONS.md` #52(b)).

**Engine**: `BacktestEngine.run()`, the same engine used for every prior
backtest finding in this project (`docs/PROFITABILITY_EXPERIMENT_REPORT.md`
et al.). Fee/slippage are `run_backtest.py`'s standard defaults, matching
`app.execution.paper_broker`'s live constants: 0.05% fee, 0.02% slippage,
applied identically to every run — no run got a cost-assumption advantage
over another. `$10,000` starting balance per period (each period runs with
a fresh account, no shared state across periods).

**Baseline** = running `run_backtest.py` WITHOUT `--strategy` (the default
`SignalEngine` path, i.e. Legacy — the actual production configuration,
all experimental flags off). **Legacy and paper trading were not touched by
this evaluation** — `run_backtest.py` is read-only, never writes to the
`trades` DB table, never places an order.

**Walk-forward criteria** (`walk_forward_report()`, unchanged from prior
sessions, not a rolling parameter-refit — see decision #8): PASS requires
≥66% of the 6 periods profitable, a max losing streak ≤2 consecutive
periods, and no first-half-vs-second-half PnL degradation (>50% falloff
from a positive first half, or any further decline from a non-positive
first half).

**Trust threshold**: per this project's own established floor
(`experiment_runner.MIN_TRADES_FOR_CONFIDENCE = 20`), a result needs ≥20
trades before it's treated as meaningful signal rather than noise. All
five configurations in this round cleared that floor by a wide margin (all
totals ≥100 trades over 6 periods) — sample size is not a caveat for any
of the five results below, which is itself worth noting given how often
"too few trades" sinks a first-round strategy read.

**Operational note (not a strategy defect)**: the OKX candle fetch for
`trend_following` failed 5 times consecutively (read timeouts, SSL
handshake timeouts, one connection reset) before succeeding on the 6th
attempt — all failures occurred during the network fetch, before any
strategy code executed, and did not affect the other four runs. Recorded
here for transparency; not an ESCALATION since it never reached strategy
logic.

## 2. Results table

| Strategy | Trades | Win rate (exact) | Total PnL (6 periods) | Profitable periods | Worst-period max DD | Walk-forward |
|---|---|---|---|---|---|---|
| **baseline (Legacy)** | 111 | 75.68% (84/111) | **+$3,400.62** | 6/6 | 1.64% | **PASSED** |
| `trend_following` | 146 | 26.03% (38/146) | -$1,009.78 | 1/6 | 3.92% | FAILED |
| `range_trading` | 258 | 17.83% (46/258) | -$2,321.08 | 2/6 | 9.85% | FAILED |
| `breakout` | 347 | 26.51% (92/347) | -$5,329.19 | 0/6 | 12.10% | FAILED |
| `volatility_expansion` | 246 | 34.55% (85/246) | -$892.45 | 3/6 | 7.46% | FAILED |

### Per-period detail

| Strategy | P1 (01/03-02/03) | P2 (02/03-03/06) | P3 (03/07-04/07) | P4 (04/07-05/08) | P5 (05/08-06/08) | P6 (06/08-07/09) |
|---|---|---|---|---|---|---|
| baseline | 17 tr, 94.12% WR, +$831.29, 0.35% DD | 20 tr, 60.00% WR, +$342.87, 1.16% DD | 8 tr, 62.50% WR, +$155.82, 0.74% DD | 21 tr, 95.24% WR, +$995.61, 0.33% DD | 17 tr, 64.71% WR, +$325.91, 0.76% DD | 28 tr, 71.43% WR, +$749.13, 1.64% DD |
| trend_following | 25 tr, 24.00% WR, -$215.38, 3.03% DD | 29 tr, 34.48% WR, +$63.53, 2.39% DD | 26 tr, 23.08% WR, -$235.55, 2.89% DD | 23 tr, 26.09% WR, -$130.94, 2.65% DD | 25 tr, 20.00% WR, -$340.96, 3.92% DD | 18 tr, 27.78% WR, -$150.48, 2.43% DD |
| range_trading | 40 tr, 17.50% WR, -$548.53, 6.89% DD | 45 tr, 11.11% WR, -$720.16, 9.00% DD | 41 tr, 9.76% WR, -$810.66, 9.85% DD | 44 tr, 22.73% WR, +$19.12, 3.79% DD | 41 tr, 26.83% WR, +$154.40, 3.65% DD | 47 tr, 19.15% WR, -$415.24, 8.57% DD |
| breakout | 61 tr, 31.15% WR, -$1,019.89, 10.89% DD | 62 tr, 29.03% WR, -$530.17, 6.10% DD | 53 tr, 24.53% WR, -$775.46, 7.76% DD | 61 tr, 21.31% WR, -$1,210.41, 12.10% DD | 61 tr, 29.51% WR, -$904.32, 9.04% DD | 49 tr, 22.45% WR, -$888.94, 9.44% DD |
| volatility_expansion | 36 tr, 36.11% WR, -$206.14, 3.11% DD | 45 tr, 46.67% WR, +$472.84, 2.85% DD | 41 tr, 21.95% WR, -$568.33, 6.15% DD | 42 tr, 19.05% WR, -$746.30, 7.46% DD | 40 tr, 45.00% WR, +$114.31, 2.90% DD | 42 tr, 38.10% WR, +$41.16, 2.21% DD |

Walk-forward detail (profitable-period ratio / max losing streak / degrading?):

| Strategy | Profitable ratio | Max losing streak | Degrading trend |
|---|---|---|---|
| baseline | 100.0% (criterion ≥66%) | 0 (criterion ≤2) | no |
| trend_following | 16.7% | 4 | YES |
| range_trading | 33.3% | 3 | no |
| breakout | 0.0% | 6 | YES |
| volatility_expansion | 50.0% | 2 (at the criterion) | YES |

## 3. Per-strategy honest verdict

**Baseline (Legacy) — reference point, not a subject of this evaluation.**
Profitable in 6/6 periods, walk-forward PASSED, 111 trades (ample sample).
Reproduces this project's established production behavior; included only
so the four candidates have something real to be measured against on the
identical candle data.

**`trend_following` — clearly negative, adequate sample (146 trades).**
Only 1 of 6 periods profitable, walk-forward FAILED on all three criteria
(16.7% profitable ratio vs. 66% required, 4-period losing streak vs. 2
allowed, and a genuine degrading trend). 26% win rate with a fixed-R
approach is well below what this module would need to be net positive.
This is not "insufficient sample" — 146 trades is far past the 20-trade
floor — it is a real, adequately-evidenced negative result on this
asset/window.

**`range_trading` — clearly negative, adequate sample (258 trades), and
carries real risk.** 2 of 6 periods profitable, walk-forward FAILED. Worst
single-period drawdown of 9.85% (period 3) is more than 5x baseline's
worst period (1.64%) and the second-worst of the four candidates. Win rate
of 17.83% aggregate is the lowest of any configuration tested. Not
"insufficient sample" — the largest-drawdown, most-frequently-trading
losing result in this round.

**`breakout` — clearly negative, adequate sample (347 trades), worst
result of the four.** 0 of 6 periods profitable — every single period lost
money, the only 0/6 result in this round. Walk-forward FAILED on all three
criteria, including a 6-period losing streak (i.e., every period). Worst
drawdown of any configuration (12.10%, period 4). -$5,329.19 aggregate PnL
against a $10,000 per-period starting balance is a severe, consistent
result, not noise — this is the clearest "dead configuration" in the round.

**`volatility_expansion` — clearly negative but the least bad of the four,
adequate sample (246 trades).** 3 of 6 periods profitable (the best
profitable-period ratio among the experimental strategies, though still
below the 66% walk-forward bar) and the smallest aggregate loss
(-$892.45). Walk-forward FAILED (50% profitable ratio, degrading trend
flagged) but by a narrower margin than the other three — max losing streak
of exactly 2 sits right at the allowed criterion rather than blowing past
it. Still a negative result, not a promising one, but distinguishable from
the other three in degree.

**None of the four experimental strategies is "insufficient sample."**
Every one of them cleared the 20-trade confidence floor by 5-17x. This
round produced real, adequately-evidenced negative results across the
board, not an inconclusive one.

## 4. Conclusions (round 1 only — no promotion recommendations)

**Insufficient sample**: none. All four candidates traded enough (146-347
trades over 6 periods) to be evaluated honestly on this data.

**Clearly dead — do not spend further compute without a code-level
review first**: `breakout` (0/6 profitable, worst drawdown, worst
aggregate loss, walk-forward failed on every criterion). This is the one
result in this round strong enough to say "don't extend to other
assets/years as-is" rather than "extend cautiously."

**Negative, but not yet at the "stop extending" bar**: `trend_following`,
`range_trading`, `volatility_expansion`. All three failed walk-forward and
lost money in-sample on this single asset/window. Per this project's
"don't burn compute on clearly dead configs" discipline, none of the three
currently justifies a full cross-asset/cross-year extension on the
strength of this evidence — but unlike `breakout`, none showed the
uniform, every-period failure that would make a further round pointless.
If cross-asset/cross-year evidence is pursued at all for this batch,
`volatility_expansion` is the least-bad candidate to prioritize first
(narrowest walk-forward miss, smallest aggregate loss, 3/6 profitable
periods).

**No promotion recommendations are made** — promotion into
`AVAILABLE_STRATEGIES` requires cross-asset AND cross-year AND
out-of-sample evidence per `ADAPTIVE_ARCHITECTURE.md` section 4.3 /
`ENGINEERING_DECISIONS.md` #52(a); this round is one asset, one 6-month
window, in-sample only. Nothing here clears that bar, and nothing here is
intended to.

**ESCALATION**: none. All four strategies executed without exceptions,
produced coherent trade counts/win rates/drawdowns across all 6 periods,
and returned `None` (no trade) rather than crashing on any period tested.
Losing money is a legitimate, honestly-recorded evidence outcome under
this evidence round's own rules — it is not evidence of a code defect, and
nothing observed in these five runs looks like broken logic (e.g. no
strategy produced an empty/degenerate result, an impossible win rate, or
an unhandled exception). The only anomaly of the round — `trend_following`'s
5 consecutive OKX fetch failures before a 6th-attempt success — was a
network-layer issue (read timeouts, SSL handshake timeouts, one connection
reset) that occurred before any strategy code ran, and is documented in
section 1 as an operational note, not a code bug.

## 5. Caveats

- **One asset, one window**: BTCUSDT only, 2026-01-03 through 2026-07-09
  (a 15m timeframe, ~6-month span). No claim is made about any other
  asset, timeframe, or macro regime. This is explicitly round 1 of a
  multi-round evidence program.
- **Disclosed-not-tuned rules**: all four modules ship with textbook
  thresholds (ADX floors, ATR multipliers, fixed-R targets, percentile
  ceilings) that have never been backtested or adjusted
  (`ENGINEERING_DECISIONS.md` #52(c)). A negative result here says "this
  specific untuned ruleset lost money on this asset/window," not "this
  strategy family has no edge under any parameterization."
  `trend_following` and `range_trading`'s losses in particular could
  partly reflect untuned parameters rather than a fundamentally unsound
  approach — this round cannot distinguish the two.
- **Walk-forward granularity sensitivity**: the 6-period split is a fixed
  choice (per `ENGINEERING_DECISIONS.md` #18's precedent that this kind of
  threshold is a starting point, not a proven-optimal setting). A
  different period count/boundary could shift a result that landed close
  to a criterion (e.g. `volatility_expansion`'s losing streak of exactly 2
  is one bad trade away from failing that criterion outright, or one good
  trade away from not tripping it at all) — not disclosed as a reason to
  discount the FAILED verdicts, but as a reason not to over-read the exact
  margin between "FAILED narrowly" and "FAILED badly."
- **In-sample only**: unlike `docs/PROFITABILITY_EXPERIMENT_REPORT.md`'s
  methodology (which held out a genuine out-of-sample period), this round
  used all 6 periods as walk-forward evidence with none held out — a
  deliberate choice for a first-look evidence pass across four candidates
  at once, but it means even `volatility_expansion`'s least-bad result has
  not been checked against data no period-selection could have touched.
- **No promotion evidence exists yet for any of the four** — this is
  explicitly stated by design in section 4, repeated here because it is
  the single most important caveat of this document.
