# Robustness Report — Production Candidate Validation

Operator directive (2026-07-14): take the strongest validated candidate
from `docs/PROFITABILITY_EXPERIMENT_REPORT.md` as the designated
PRODUCTION CANDIDATE and run 7 robustness tests against it. Only reject
if robustness materially fails; otherwise promote.

## Candidate under test

**BTCUSDT**, `use_structure_tp=True, structure_tp_max_r=3.0,
require_premium_discount_filter=True` — confirmed profitable in 2 of 3
independent years (2025, 2026), out-of-sample confirmed both times (see
`docs/PROFITABILITY_EXPERIMENT_REPORT.md` sections 12-14). This is the
highest-confidence candidate produced this session. **Still not a
production default** — the paper trader has run Legacy-only, untouched,
throughout this entire validation.

Methodology: `scripts/robustness_report.py`, reusing the same fixed-anchor
fetch/backtest infrastructure as the rest of this session's work (2025 and
2026 anchors, `--candles 3000 --periods 6`). Full raw output:
`scripts/reports/robustness_report.json`.

## Test 1: Monte Carlo analysis

Bootstrap resampling (2000 iterations, fixed seed 42) of the 68 real
trades collected across both confirmed years combined. Disclosed
assumption: treats trade outcomes as independent draws, ignoring any real
serial correlation between consecutive trades (a genuine simplification).

| Metric | Value |
|---|---|
| Final return, 5th percentile | +$1,696.82 |
| Final return, median | +$2,286.57 |
| Final return, 95th percentile | +$2,843.89 |
| Probability of a negative return | **0.0%** |
| Max drawdown, 95th percentile | 1.67% |
| Max drawdown, 99th percentile | 2.08% |
| Probability drawdown exceeds 5% | **0.0%** |
| Probability drawdown exceeds 10% | **0.0%** |

**PASS.** Every one of 2000 resampled trade-order permutations was
profitable, and drawdown stayed under 2.1% even at the 99th percentile.
Strong result, though bounded by the i.i.d. assumption disclosed above.

## Test 2: Randomized execution delay — MATERIAL FAILURE

Simulates real dispatch/network/exchange latency: the order fills at a
LATER candle's price than the signal's planned structural entry, while
stop-loss/take-profit stay at their original structural levels (new
`entry_delay_candles` parameter, `backtest_engine.py`, 2 new unit tests).

| Delay | Net Profit | Profit Factor | Win Rate |
|---|---|---|---|
| 0 candles (no delay) | +$1,547.64 | 5.24 | 78.6% |
| 1 candle (~5 min) | **-$1,239.23** | **0.16** | 31.4% |
| 2 candles (~10 min) | -$1,407.85 | 0.12 | 30.6% |
| 3 candles (~15 min) | -$1,322.54 | 0.13 | 30.6% |

**MATERIAL FAILURE.** This is not a graceful degradation — a single
5-minute delay flips the candidate from a 5.24 profit factor to 0.16 (a
losing system), and it stays there at 2 and 3 candles of delay. Root
cause, mechanistically identified (not just observed): this candidate's
average stop distance is **0.23% of entry price** (Test 7 below) —
extremely tight. Normal price movement over even one 5-minute candle can
be comparable to or exceed that distance, so a delayed fill can land
already invalidated relative to the ORIGINAL stop/target math the
position was sized against. This is a genuine property of the strategy's
tight-stop design interacting with real-world latency, not an artifact of
how the test was built.

## Test 3: Slippage stress test

| Slippage | Net Profit | Profit Factor |
|---|---|---|
| 0.02% (baseline) | +$1,547.64 | 5.24 |
| 0.10% (5x) | +$1,116.75 | 3.45 |
| 0.30% (15x) | +$54.48 | 1.08 |

**PASS, with disclosed sensitivity.** Degrades gracefully (unlike Test 2)
-- stays profitable even at 15x the baseline slippage assumption, though
only marginally so at that extreme. Realistic BTC slippage on a liquid
venue is far closer to the 0.02-0.10% range tested here than the 0.30%
breaking point.

## Test 4: Fee stress test

| Fee (per leg) | Net Profit | Profit Factor |
|---|---|---|
| 0.05% (baseline, matches `paper_broker.py`) | +$1,547.64 | 5.24 |
| 0.15% (3x) | +$476.60 | 1.81 |
| 0.30% (6x) | **-$998.72** | 0.18 |

**PASS at realistic fee tiers, fails at extreme ones.** 0.05-0.15% per
leg covers typical futures-taker fee tiers on major venues; 0.30% would
be an unusually unfavorable tier. Real sensitivity disclosed, not a
material failure at assumptions matching this project's actual paper
trading configuration.

## Test 5: Different volatility regimes

Realized volatility (stdev of consecutive-candle percent returns,
disclosed as a simple, non-annualized measure):

| Window | Realized volatility |
|---|---|
| 2026-07-12 anchor | 0.001355 |
| 2025-07-12 anchor | 0.001070 |

2026 was ~27% more volatile than 2025; the candidate was profitable and
out-of-sample-confirmed in both (`docs/PROFITABILITY_EXPERIMENT_REPORT.md`
section 14). **PASS**, though this only covers a modest volatility range
-- a genuinely low-volatility regime and a genuinely extreme one (e.g.
2024's harder regime, section 14.2) were not both re-tested here
specifically for volatility characterization.

## Test 6: Different market sessions

Real trades bucketed by entry hour (UTC): Asian 00-08, London 08-16,
NY/other 16-24.

| Session | Trades | Net Profit | Win Rate | Profit Factor |
|---|---|---|---|---|
| Asian | 41 | +$1,417.27 | 75.6% | 4.65 |
| London | 19 | +$384.73 | 63.2% | 2.41 |
| NY/other | 8 | +$483.12 | 100.0% | infinite |

**PASS.** Profitable in every session tested -- no session shows a
negative result. Asian session dominates both trade volume and quality
(consistent with this being a BTCUSDT/5m ICT-style strategy, where Asian
range/liquidity setups are a standard, expected source of signals).
NY/other's 100% win rate is disclosed as likely small-sample noise (only
8 trades), not a genuinely stronger edge in that session.

## Test 7: Different leverage settings — analytical, not re-run

This codebase's position sizing (`calculate_position_size`) targets a
FIXED RISK PERCENT of account balance per trade, derived from the stop
distance -- not a fixed notional scaled by a leverage multiplier. Under
this model, leverage does not independently change trade P&L or drawdown
(re-running backtests at different "leverage settings" would return
identical numbers to what's already reported) -- it only matters for
margin sufficiency and liquidation headroom.

| Metric | Value |
|---|---|
| Max implied leverage across every real trade tested | 1.68x |
| Average implied leverage | 1.29x |
| Average stop distance (source of Test 2's fragility) | 0.23% of entry price |
| Minimum stop distance seen | 0.17% of entry price |

**PASS.** Maximum leverage needed (1.68x) is modest and well within what
any reasonable exchange account offers -- margin availability is not a
practical constraint for this candidate. (The same tight-stop numbers
that make leverage a non-issue are exactly what makes Test 2's execution
delay finding material -- both trace to the same root cause.)

## Overall verdict: NOT PROMOTED — one material failure found

Per the operator's own decision rule ("only reject if robustness
materially fails"): **Test 2 (execution delay) is a material failure.**
5 of 7 tests pass cleanly (Monte Carlo, slippage, fees, volatility,
sessions) and 1 is a pure non-issue by construction (leverage). But a
strategy that flips from a 5.24 to a 0.16 profit factor -- fully reversing
sign -- from a single 5-minute execution delay is not safely deployable
as-is: real paper/live trading cannot guarantee zero latency, and this
candidate's edge depends on it.

**This is not a rejection of the underlying `structure_tp` family or the
cross-asset/cross-year validation work** (sections 12-14 stand on their
own merits) -- it is specifically that the tight stop distances this
candidate's config produces (0.17-0.23% of price) make it latency-fragile
in a way the backtest-only validation could not surface, because
`run_backtest()` has always assumed instantaneous, zero-latency fills.

**Recommendation, not automatically acted on**: this is a genuine fork in
the road, not a "search for a new candidate" question (per this round's
explicit "do not search for more strategy ideas" instruction) -- the
options are (a) accept this candidate only with verified sub-candle
execution infrastructure in front of it, (b) re-derive a candidate from
the SAME already-validated `structure_tp`/`premium_discount_filter`
family with a wider stop (a parameter change, not a new strategy idea),
or (c) hold at "validated but not deployable without infra guarantees."
Left for operator decision rather than assumed.

## Production status (unchanged)

Nothing here changes any production default. Paper trading (Legacy
engine, all experimental flags off) has run continuously and untouched
throughout this entire robustness validation.
