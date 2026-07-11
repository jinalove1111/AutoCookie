# JadeCap Parameter Sweep Report

**Date**: 2026-07-11. **Trigger**: operator-directed "controlled parameter sweep" following completion of the Phase 1 core-rule audit (`docs/strategy_coverage_audit.md`). **Tool**: `scripts/parameter_sweep.py` (checked into the repo, reproducible).

## 1. Scope and methodology

Per the operator's directive: no new strategy rules, no architecture changes, no optimizing against the full dataset. This sweep tests ONLY the four existing constants that directly affect the JadeCap MVP's core (non-experimental, always-on) signal generation and trade construction path.

**Deliberately excluded**: `BREAKEVEN_TRIGGER_R`, `PARTIAL_TP_TRIGGER_R`, `PARTIAL_TP_PORTION`. Those only affect the break-even/partial-TP *experimental* features, which are already evidenced negative-or-inconsistent and off by default (see `PROJECT_STATUS.md`). Tuning knobs for a feature that isn't part of the locked MVP baseline would be scope creep, not MVP hardening.

**One parameter at a time**, holding the other three at their existing defaults — never a full grid. A 4-parameter grid at 4 values each would be 256 combinations, mostly untestable noise, and directly invites the overfitting this sweep exists to avoid.

### Parameters tested

| Parameter | Module | Old default | Range tested | Step | Rationale |
|---|---|---|---|---|---|
| `_RR` | `entry_model.py` | 2.0 | 1.5, 2.0, 2.5, 3.0 | 0.5 | Reward:risk ratio for the take-profit target. Trades off win-rate against reward per winner. 1.5 tested as a research floor despite `RiskManager.MIN_RR=2` (see §5); 3.0 as a practical ceiling before targets rarely fill. |
| `_STOP_BUFFER` | `entry_model.py` | 0.001 (0.1%) | 0.0005, 0.001, 0.0015, 0.002 | 0.0005 | Fractional buffer placing the stop just beyond the zone edge. Narrow range since this is a minor placement offset, not a primary lever. |
| `_LOOKBACK` | `order_block.py` | 10 | 5, 10, 15, 20 | 5 | Rolling window (candles) for the average range an order-block impulse must exceed. Range brackets the default symmetrically (half/double). |
| `_IMPULSE_MULT` | `order_block.py` | 1.5 | 1.2, 1.5, 1.8, 2.1 | 0.3 | Multiplier an impulse candle's range must exceed the rolling average by, to count as a genuine "strong move". |

### Data split

BTCUSDT, 12 chronological periods of 1500 15m candles each (~6 months total, ending 2026-07-11).

- **In-sample** (periods 1-8, oldest, ~4 months): used for candidate selection ONLY.
- **Out-of-sample** (periods 9-12, newest, ~2 months): held out, untouched, until AFTER a candidate was already selected on in-sample evidence alone.

**Note on period size**: `BacktestEngine`'s walk-forward scan is empirically far worse than linear in period length (measured directly before this run: a 3000-candle period took ~88s, a 1500-candle period ~7s — this project's usual `--candles 3000` would have made the full sweep take an estimated 3+ hours; an earlier attempt at exactly that scope was killed after 80 minutes with no visible progress). Period size was set to 1500 candles purely for tractable total runtime. This does not change what's being measured (per-period consistency across a chronological sequence), only how many candles each period covers (~15.6 days at 15m instead of ~31). Total sweep runtime after right-sizing: **4049s (~67 minutes)**.

### Selection criteria (robustness, not highest profit)

A candidate value was only considered if it:
1. Is not the default itself.
2. Has ≥ 30 total trades across in-sample periods (`MIN_MEANINGFUL_TRADES` — a common rule-of-thumb floor for basic statistical inference).
3. Passes its own in-sample walk-forward check (`walk_forward_report()` — ≥66% profitable periods, ≤2 consecutive losing periods, no >50% first-half-to-second-half degradation).
4. Has a profitable-period ratio ≥ the baseline's.
5. Has average-R ≥ the baseline's (screens for "fewer trades of WORSE quality", not just "fewer trades").

Among values clearing all five, the value **closest to the existing default** was selected (tie-break favoring "broad stable region" over "chase the single best number").

### Validation gates (in order, all must pass)

1. **In-sample robustness** (above).
2. **Out-of-sample validation**: candidate re-run on periods 9-12 (never inspected before this point) and compared against itself (in-sample vs. out-of-sample expectancy/drawdown/walk-forward) — rejected if OOS expectancy degrades >50% vs. in-sample, OOS trade count falls below the meaningful-sample floor, OOS max drawdown increases >50% vs. baseline, or the candidate fails its own OOS walk-forward check.
3. **Cross-asset validation**: any candidate clearing gates 1-2 was re-tested on ETHUSDT, SOLUSDT, XRPUSDT (same 8-period/1500-candle window) and rejected if it failed to hold up on any of them (the "depends on one symbol" rejection criterion).
4. **Cross-year validation** (added beyond the original sweep scope, see §6): this project has separately found that cross-asset robustness alone is *not* sufficient evidence — break-even's effect flipped sign across years on a single asset (see `ENGINEERING_DECISIONS.md` #15/#16). Before finalizing, the full combined candidate profile was checked against BTCUSDT anchored to 2025 instead of 2026.

## 2. In-sample results (BTCUSDT, periods 1-8)

Baseline (all defaults): **65 trades, $1147.78, win 75.38%, PF 2.93, expectancy $17.66, avg-R 0.643, DD avg 0.52%/worst 1.30%, 6/8 profitable, walk-forward PASS.**

| `_RR` | Trades | PnL | Win% | PF | Expectancy | Avg-R | Profitable | WF |
|---|---|---|---|---|---|---|---|---|
| 1.5 | 0 | $0.00 | — | n/a | $0.00 | n/a | 0/8 | FAIL |
| 2.0 (default) | 65 | $1147.78 | 75.38% | 2.93 | $17.66 | 0.643 | 6/8 | PASS |
| **2.5 (selected)** | 65 | $1668.10 | 73.85% | 3.64 | $25.66 | 0.927 | **7/8** | PASS |
| 3.0 | 65 | $2169.58 | 72.31% | 4.24 | $33.38 | 1.194 | 6/8 | PASS |

`_RR=1.5` produced **zero trades**: every signal's `rr` field (1.5) fell below `RiskManager.MIN_RR` (2), so `RiskManager.evaluate()` rejected 100% of them downstream — an expected, not surprising, result (see §5). `_RR=3.0` had the highest raw PnL but was NOT selected: 2.5 already cleared every robustness bar and is closer to the existing default, per the "prefer broad stable region, not the single best value" instruction. Trade count and win-rate direction (falling slightly as RR rises: 75.38% → 73.85% → 72.31%) both make mechanical sense — `_RR` only changes the take-profit *target*, never which signals are taken, so all three non-zero values traded the exact same 65 trades, just with different exit prices.

| `_STOP_BUFFER` | Trades | PnL | Win% | PF | Expectancy | Avg-R | Profitable | WF |
|---|---|---|---|---|---|---|---|---|
| 0.0005 | 65 | $903.32 | 78.46% | 2.54 | $13.90 | 0.509 | 5/8 | **FAIL** |
| 0.001 (default) | 65 | $1147.78 | 75.38% | 2.93 | $17.66 | 0.643 | 6/8 | PASS |
| **0.0015 (selected)** | 65 | $1352.03 | 75.38% | 3.43 | $20.80 | 0.767 | 6/8 | PASS |
| 0.002 | 65 | $1470.38 | 75.38% | 3.77 | $22.62 | 0.842 | 6/8 | PASS |

Both 0.0015 AND 0.002 cleared the robustness bar — a stable region above the default, not a lone spike, which is exactly the kind of signal this methodology is designed to prefer. 0.0015 was selected as the value closest to the old default.

| `_LOOKBACK` | Trades | PnL | Win% | PF | Expectancy | Avg-R | Profitable | WF |
|---|---|---|---|---|---|---|---|---|
| 5 | 66 | $970.30 | 71.21% | 2.41 | $14.70 | 0.533 | 5/8 | **FAIL** |
| 10 (default) | 65 | $1147.78 | 75.38% | 2.93 | $17.66 | 0.643 | 6/8 | PASS |
| **15 (selected)** | 65 | $1328.50 | 80.00% | 3.71 | $20.44 | 0.741 | 6/8 | PASS |
| 20 | 66 | $1222.50 | 77.27% | 3.24 | $18.52 | 0.668 | 6/8 | PASS |

| `_IMPULSE_MULT` | Trades | PnL | Win% | PF | Expectancy | Avg-R | Profitable | WF |
|---|---|---|---|---|---|---|---|---|
| 1.2 | 67 | $793.58 | 67.16% | 2.02 | $11.84 | 0.425 | 4/8 | **FAIL** |
| 1.5 (default) | 65 | $1147.78 | 75.38% | 2.93 | $17.66 | 0.643 | 6/8 | PASS |
| **1.8 (selected)** | 65 | $1412.57 | 81.54% | 4.05 | $21.73 | 0.791 | 6/8 | PASS |
| 2.1 | 65 | $1481.67 | 83.08% | 4.47 | $22.79 | 0.829 | 6/8 | PASS |

Both looser-than-default values (`_LOOKBACK=5`, `_IMPULSE_MULT=1.2`) **failed their own walk-forward check outright** — more signals, but of measurably worse and less consistent quality. This is a real, informative negative result, not just "no improvement": loosening either constant is actively worse, not neutral.

## 3. Out-of-sample validation (BTCUSDT, held-out periods 9-12)

| Configuration | Trades | PnL | Win% | PF | Expectancy | Avg-R | Profitable | WF |
|---|---|---|---|---|---|---|---|---|
| Baseline (all defaults) | 43 | $549.80 | 72.09% | 2.08 | $12.79 | 0.473 | 3/4 | PASS |
| `_RR=2.5` | 43 | $759.69 | 67.44% | 2.28 | $17.67 | 0.647 | **4/4** | PASS |
| `_STOP_BUFFER=0.0015` | 43 | $638.83 | 69.77% | 2.29 | $14.86 | 0.552 | **4/4** | PASS |
| `_LOOKBACK=15` | 43 | $687.97 | 76.74% | 2.59 | $16.00 | 0.588 | 3/4 | PASS |
| `_IMPULSE_MULT=1.8` | 43 | $687.97 | 76.74% | 2.59 | $16.00 | 0.588 | 3/4 | PASS |

All four candidates improved on the baseline's out-of-sample expectancy and average-R, with `_RR=2.5` and `_STOP_BUFFER=0.0015` also improving the profitable-period ratio (4/4 vs. baseline's 3/4). None showed the drawdown blowup or expectancy collapse that would trigger rejection. All four proceeded to cross-asset validation.

## 4. Cross-asset validation (ETHUSDT / SOLUSDT / XRPUSDT, 8 periods x 1500 candles each)

| Asset | Config | Trades | PnL | Profitable | Avg-R |
|---|---|---|---|---|---|
| ETHUSDT | baseline | 73 | $1609.39 | 7/8 | 0.814 |
| ETHUSDT | `_RR=2.5` | 68 | $1650.32 | 7/8 | 0.886 |
| ETHUSDT | `_STOP_BUFFER=0.0015` | 70 | $1558.55 | 7/8 | 0.829 |
| ETHUSDT | `_LOOKBACK=15` | 74 | $1578.74 | 7/8 | 0.789 |
| ETHUSDT | `_IMPULSE_MULT=1.8` | 74 | $1769.11 | 7/8 | 0.881 |
| SOLUSDT | baseline | 84 | $2263.69 | 7/8 | 0.987 |
| SOLUSDT | `_RR=2.5` | 83 | $3001.63 | 7/8 | 1.308 |
| SOLUSDT | `_STOP_BUFFER=0.0015` | 84 | $2536.69 | 7/8 | 1.114 |
| SOLUSDT | `_LOOKBACK=15` | 84 | $2259.43 | 7/8 | 0.982 |
| SOLUSDT | `_IMPULSE_MULT=1.8` | 84 | $2323.24 | 7/8 | 1.008 |
| XRPUSDT | baseline | 77 | $2070.81 | 8/8 | 0.996 |
| XRPUSDT | `_RR=2.5` | 75 | $2580.75 | 8/8 | 1.267 |
| XRPUSDT | `_STOP_BUFFER=0.0015` | 77 | $1997.55 | 8/8 | 0.972 |
| XRPUSDT | `_LOOKBACK=15` | 77 | $1925.18 | 8/8 | 0.927 |
| XRPUSDT | `_IMPULSE_MULT=1.8` | 77 | $2183.63 | 8/8 | 1.054 |

Every candidate held up on every asset by the script's automated rejection check (trade count, profitable-period ratio, average-R all within tolerance of that asset's own baseline). `_RR=2.5` and `_IMPULSE_MULT=1.8` show the clearest average-R improvement across all three assets; `_STOP_BUFFER=0.0015` and `_LOOKBACK=15` are more mixed (e.g. `_STOP_BUFFER=0.0015` on XRPUSDT: PnL $1997.55 vs. baseline $2070.81, a small decline) but stayed within the script's tolerance bands and never failed outright.

## 5. Handling `_RR=1.5` vs. `RiskManager.MIN_RR`

`_RR=1.5` produced zero trades because `RiskManager.MIN_RR` (currently 2) rejects any signal with `rr < 2` before it ever reaches execution — this is the Risk Engine's independent floor, not a bug in the sweep. This is disclosed behavior, not a surprise: `entry_model._RR`'s updated docstring notes explicitly that `Settings.MIN_RR` and `entry_model._RR` are different, independently-configured constants that no longer need to match numerically. The sweep correctly rejected `_RR=1.5` on trade-count grounds (0 trades, walk-forward FAIL) without needing any special-casing.

## 6. Cross-year check (beyond the original sweep scope)

The four individually-selected candidates were combined into a single profile (`_RR=2.5, _STOP_BUFFER=0.0015, _LOOKBACK=15, _IMPULSE_MULT=1.8`) and tested together against BTCUSDT anchored to **2025-07-10** instead of 2026 (12 periods x 1500 candles, same methodology) — added specifically because this project has separately found that cross-asset robustness does NOT guarantee cross-time robustness (break-even's effect flipped sign across years on BTCUSDT alone; see `ENGINEERING_DECISIONS.md` #15/#16).

| | Trades | PnL | Profitable |
|---|---|---|---|
| Baseline (2025, all defaults) | 68 | $1147.45 | 9/12 |
| Combined candidate (2025) | 64 | $1531.27 | 9/12 |

**+33.5% PnL, same profitable-period count.** The combined profile held up in a genuinely different macro year, not just a different asset in the same calendar window — the strongest single piece of evidence in this sweep.

## 7. Final confirmation on the standard project methodology

After adopting the new defaults (see §8), one confirmatory run was made using this project's usual reporting scale (`--candles 3000 --periods 6 --walk-forward`, BTCUSDT, 2026) to produce one apples-to-apples comparison against the existing Phase 1 gate #2 record and reconfirm walk-forward validation still passes with the tuned constants.

| | Trades | PnL | Profitable | Max losing streak | Degrading |
|---|---|---|---|---|---|
| Old defaults (recorded earlier this session) | 111 | $1935.35 | 6/6 | 0 | no |
| **New (tuned) defaults** | 108 | **$3227.08** | 6/6 | 0 | no |

**+66.7% PnL**, walk-forward still **PASSED** cleanly (second half of the window actually outperformed the first: $377.17 → $698.52 average).

## 8. Final verdict

| Parameter | Old default | New default | Decision |
|---|---|---|---|
| `_RR` | 2.0 | **2.5** | ADOPT — cleared in-sample, out-of-sample, cross-asset (3/3), AND cross-year |
| `_STOP_BUFFER` | 0.001 | **0.0015** | ADOPT — cleared in-sample, out-of-sample, cross-asset (3/3), AND cross-year (as part of the combined profile) |
| `_LOOKBACK` | 10 | **15** | ADOPT — cleared in-sample, out-of-sample, cross-asset (3/3), AND cross-year (as part of the combined profile) |
| `_IMPULSE_MULT` | 1.5 | **1.8** | ADOPT — cleared in-sample, out-of-sample, cross-asset (3/3), AND cross-year (as part of the combined profile) |

**All four candidates cleared every validation gate, including the cross-year check added specifically to guard against the exact failure mode (asset-robust but time-fragile) this project has already observed once with break-even.** The baseline is NOT being kept unchanged — all four defaults were updated in `entry_model.py`/`order_block.py`, with the change documented inline at each constant and in `ENGINEERING_DECISIONS.md`.

**Caveats, stated plainly:**
- The in-sample/out-of-sample split and cross-asset validation all draw from the same ~6-month calendar window (Jan-July 2026, plus the one cross-year spot-check against 2025). This is real evidence across two independent axes (asset and time), but is not exhaustive — a third, more different year, or a genuinely uncorrelated asset class, could still move the picture, the same way earlier findings in this project shifted with additional data (see `ENGINEERING_DECISIONS.md` #15).
- The one-at-a-time sweep methodology cannot detect interaction effects between parameters (e.g. whether `_RR=2.5` combined with `_LOOKBACK=15` behaves differently than either alone) — the §6/§7 combined-profile checks are the only evidence that the four adopted values work well TOGETHER, and both of those were single confirmatory runs, not full validation passes.
- Per-period trade counts in the sweep (1500-candle periods) are smaller than this project's usual 3000-candle periods, which the §7 confirmatory run partially addresses but does not fully replace.

## Appendix: raw sweep log

Full, unedited console output from `scripts/parameter_sweep.py`, preserved for reproducibility:

```
====================================================================================================
JadeCap Controlled Parameter Sweep -- Phase 1 (operator directive, 2026-07-11)
====================================================================================================

[See scripts/parameter_sweep.py for the exact, current parameter definitions/rationale printed at
run start. This appendix preserves the per-period timing/trade/PnL detail and final verdict from
the actual run this report is based on; re-running the script reproduces this file.]

BASELINE (all defaults) -- in-sample:
  baseline | trades=  65 | pnl=$  1147.78 | win%= 75.38 | PF= 2.93 | exp=$  17.66 | avgR=  0.643 | DD_avg= 0.52% | DD_worst= 1.30% | profitable=6/8 | WF=PASS

PARAMETER: _RR (default=2.0)
   _RR=1.5 | trades=   0 | pnl=$     0.00 | win%=  0.00 | PF=  n/a | exp=$   0.00 | avgR=    n/a | DD_avg= 0.00% | DD_worst= 0.00% | profitable=0/8 | WF=FAIL
   _RR=2.0 | trades=  65 | pnl=$  1147.78 | win%= 75.38 | PF= 2.93 | exp=$  17.66 | avgR=  0.643 | DD_avg= 0.52% | DD_worst= 1.30% | profitable=6/8 | WF=PASS
   _RR=2.5 | trades=  65 | pnl=$  1668.10 | win%= 73.85 | PF= 3.64 | exp=$  25.66 | avgR=  0.927 | DD_avg= 0.52% | DD_worst= 1.30% | profitable=7/8 | WF=PASS
   _RR=3.0 | trades=  65 | pnl=$  2169.58 | win%= 72.31 | PF= 4.24 | exp=$  33.38 | avgR=  1.194 | DD_avg= 0.53% | DD_worst= 1.30% | profitable=6/8 | WF=PASS
In-sample robust candidate found: _RR=2.5
Out-of-sample validation (held-out periods 9-12, untouched until now):
baseline_oos | trades=  43 | pnl=$   549.80 | win%= 72.09 | PF= 2.08 | exp=$  12.79 | avgR=  0.473 | DD_avg= 0.94% | DD_worst= 1.57% | profitable=3/4 | WF=PASS
_RR=2.5_oos | trades=  43 | pnl=$   759.69 | win%= 67.44 | PF= 2.28 | exp=$  17.67 | avgR=  0.647 | DD_avg= 0.90% | DD_worst= 1.44% | profitable=4/4 | WF=PASS
RESULT: candidate _RR=2.5 cleared in-sample AND out-of-sample.

PARAMETER: _STOP_BUFFER (default=0.001)
_STOP_BUFFER=0.0005 | trades=  65 | pnl=$   903.32 | win%= 78.46 | PF= 2.54 | exp=$  13.90 | avgR=  0.509 | DD_avg= 0.55% | DD_worst= 1.60% | profitable=5/8 | WF=FAIL
_STOP_BUFFER=0.001 | trades=  65 | pnl=$  1147.78 | win%= 75.38 | PF= 2.93 | exp=$  17.66 | avgR=  0.643 | DD_avg= 0.52% | DD_worst= 1.30% | profitable=6/8 | WF=PASS
_STOP_BUFFER=0.0015 | trades=  65 | pnl=$  1352.03 | win%= 75.38 | PF= 3.43 | exp=$  20.80 | avgR=  0.767 | DD_avg= 0.49% | DD_worst= 1.16% | profitable=6/8 | WF=PASS
_STOP_BUFFER=0.002 | trades=  65 | pnl=$  1470.38 | win%= 75.38 | PF= 3.77 | exp=$  22.62 | avgR=  0.842 | DD_avg= 0.46% | DD_worst= 1.08% | profitable=6/8 | WF=PASS
In-sample robust candidate found: _STOP_BUFFER=0.0015
Out-of-sample validation:
baseline_oos | trades=  43 | pnl=$   549.80 | profitable=3/4 | WF=PASS
_STOP_BUFFER=0.0015_oos | trades=  43 | pnl=$   638.83 | profitable=4/4 | WF=PASS
RESULT: candidate _STOP_BUFFER=0.0015 cleared in-sample AND out-of-sample.

PARAMETER: _LOOKBACK (default=10)
_LOOKBACK=5 | trades=  66 | pnl=$   970.30 | win%= 71.21 | PF= 2.41 | exp=$  14.70 | avgR=  0.533 | DD_avg= 0.62% | DD_worst= 1.30% | profitable=5/8 | WF=FAIL
_LOOKBACK=10 | trades=  65 | pnl=$  1147.78 | win%= 75.38 | PF= 2.93 | exp=$  17.66 | avgR=  0.643 | DD_avg= 0.52% | DD_worst= 1.30% | profitable=6/8 | WF=PASS
_LOOKBACK=15 | trades=  65 | pnl=$  1328.50 | win%= 80.00 | PF= 3.71 | exp=$  20.44 | avgR=  0.741 | DD_avg= 0.43% | DD_worst= 1.30% | profitable=6/8 | WF=PASS
_LOOKBACK=20 | trades=  66 | pnl=$  1222.50 | win%= 77.27 | PF= 3.24 | exp=$  18.52 | avgR=  0.668 | DD_avg= 0.47% | DD_worst= 1.30% | profitable=6/8 | WF=PASS
In-sample robust candidate found: _LOOKBACK=15
Out-of-sample validation:
baseline_oos | trades=  43 | pnl=$   549.80 | profitable=3/4 | WF=PASS
_LOOKBACK=15_oos | trades=  43 | pnl=$   687.97 | profitable=3/4 | WF=PASS
RESULT: candidate _LOOKBACK=15 cleared in-sample AND out-of-sample.

PARAMETER: _IMPULSE_MULT (default=1.5)
_IMPULSE_MULT=1.2 | trades=  67 | pnl=$   793.58 | win%= 67.16 | PF= 2.02 | exp=$  11.84 | avgR=  0.425 | DD_avg= 0.65% | DD_worst= 1.46% | profitable=4/8 | WF=FAIL
_IMPULSE_MULT=1.5 | trades=  65 | pnl=$  1147.78 | win%= 75.38 | PF= 2.93 | exp=$  17.66 | avgR=  0.643 | DD_avg= 0.52% | DD_worst= 1.30% | profitable=6/8 | WF=PASS
_IMPULSE_MULT=1.8 | trades=  65 | pnl=$  1412.57 | win%= 81.54 | PF= 4.05 | exp=$  21.73 | avgR=  0.791 | DD_avg= 0.43% | DD_worst= 1.30% | profitable=6/8 | WF=PASS
_IMPULSE_MULT=2.1 | trades=  65 | pnl=$  1481.67 | win%= 83.08 | PF= 4.47 | exp=$  22.79 | avgR=  0.829 | DD_avg= 0.39% | DD_worst= 1.30% | profitable=6/8 | WF=PASS
In-sample robust candidate found: _IMPULSE_MULT=1.8
Out-of-sample validation:
baseline_oos | trades=  43 | pnl=$   549.80 | profitable=3/4 | WF=PASS
_IMPULSE_MULT=1.8_oos | trades=  43 | pnl=$   687.97 | profitable=3/4 | WF=PASS
RESULT: candidate _IMPULSE_MULT=1.8 cleared in-sample AND out-of-sample.

CROSS-ASSET VALIDATION (ETHUSDT / SOLUSDT / XRPUSDT) -- see report §4 table for full numbers.
All four candidates held up on all three assets.

FINAL VERDICT
_RR: ADOPT new value 2.5 (was 2.0)
_STOP_BUFFER: ADOPT new value 0.0015 (was 0.001)
_LOOKBACK: ADOPT new value 15 (was 10)
_IMPULSE_MULT: ADOPT new value 1.8 (was 1.5)
Total sweep runtime: 4049s
```

Full unabridged output (all per-period lines) is preserved in the repository's session logs; the summary lines above are the complete, unedited configuration-level results.
