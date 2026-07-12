# PROJECT_STATUS — JadeCap Automated Trading Bot

This file is the always-current, English snapshot: what the system does
*right now*, as of the latest commit on `master`. It intentionally has
no history — for the round-by-round session log (in Korean, matching
this project's established working language for that file), see
`HANDOFF.md`. For chronological release notes, see `CHANGELOG.md`. For
the "why" behind specific non-obvious engineering choices, see
`ENGINEERING_DECISIONS.md`. For forward-looking prioritization, see
`ROADMAP.md`.

Last updated: 2026-07-12 (all 5 JadeCap MVP core trading rules from the
2026-07-11 operator directive are now COMPLETE: Premium/Discount,
previous swing high/low, OB+FVG confluence, structure-based TP, Equal
High/Equal Low. Progress tracked in the "Core rule completion (MVP)"
section below. Previous swing high/low
(`app.strategy.market_structure.find_previous_swing_high`/
`find_previous_swing_low`) shipped in an earlier round; this round
closed out the remaining three: **OB + FVG confluence entry model**
(opt-in `require_ob_fvg_confluence` on `build_entry_model`, default off,
not yet A/B backtested), **structure-based take-profit** (opt-in
`use_structure_tp` on `build_entry_model`, wires Premium/Discount in as
a TP extension target, default off, not yet A/B backtested), and
**Equal High/Equal Low liquidity detection**
(`app.strategy.liquidity.detect_equal_highs`/`detect_equal_lows`,
detection-only). 27 new tests across the 4 non-Premium/Discount items
(4 previous-swing + 7 OB+FVG confluence + 8 structure-TP + 8 equal
highs/lows) — 247 total, up from 220, 0 known failures — see
`docs/strategy_spec.md` sections 2/3/6/8 and `ENGINEERING_DECISIONS.md`.
Next: Phase 1 gate #3 paper-trading validation, per operator instruction
(2026-07-12). Prior round, unchanged below: completed a
full 2025 cross-year check on all 4 assets under the new tuned defaults
at the standard reporting scale -- **8 of 9 combinations PASSED
cleanly** (2026: BTC/ETH/SOL/XRP all PASSED; 2025: ETH/SOL/XRP all
PASSED). **1 real, disclosed exception**: BTCUSDT 2025 FAILED its
walk-forward degradation check (still net profitable in all 6 periods,
$1714.56 total, but the second half's average PnL retained only 35.4%
of the first half's) -- notably, this did NOT show up in the parameter
sweep's own smaller-scale BTC-2025 spot-check, a real example of
walk-forward conclusions depending on period granularity. Not reverting
the new defaults over this (BTC 2025 stayed profitable throughout), but
recorded honestly as a caveat rather than omitted. Earlier this session:
re-confirmed walk-forward on all 4 assets at 2026 under the new tuned
defaults (BTC +66.7%, ETH +4.6%, SOL +32.6%, XRP +39.0%, combined
+33.3%); completed the parameter sweep itself (`_RR` 2.0->2.5,
`_STOP_BUFFER` 0.001->0.0015, `_LOOKBACK` 10->15, `_IMPULSE_MULT`
1.5->1.8, full methodology in `docs/parameter_sweep_report.md`);
resolved the confluence-strength spec ambiguity; hardened risk controls
(circuit breaker auto-reset). Scope locked by operator directive: Phase
1 = JadeCap only, tracked against 4 explicit gates below. See
`CHANGELOG.md` for the full chronological history of this session's
findings).

## Profitability sprint (2026-07-12, operator-directed autonomous session)

Paper trading started (Legacy engine, all experimental flags off,
19:29:11) and is running continuously against live OKX data -- 0 trades
so far as of this write-up (expected at this trade frequency, not an
error). In parallel, built a rigorous controlled-experiment harness
(`scripts/experiment_runner.py` -- fixed-anchor fetch shared across every
config, in-sample/held-out-out-of-sample split, JSON results ledger) and
tested every previously-unvalidated Legacy-pipeline flag against it.
**`use_structure_tp` clears the project's three-metric keep rule** (Net
Profit, Profit Factor, AND worst-period Drawdown all improve), confirmed
out-of-sample on held-out data -- the strongest single-experiment result
this project has produced, though still only 1 asset/1 time window
(cross-asset/cross-year validation is the recommended next step, not yet
run). `ob_fvg_confluence`/`premium_discount_filter`/the
`structure_tp`+`premium_discount_filter` combination were all tested and
rejected. A new opt-in `structure_tp_max_r` conservative-exit variant was
built and also clears the bar. **Production default is unchanged** --
Legacy stays the only production-approved configuration. Also closed 4
real paper-trading observability gaps (`Signal.rejection_reason`,
`Trade.exit_reason`/`r_multiple`/`strategy_config` -- were computed
in-process but never persisted) additively, without touching the running
process. Full detail: `docs/PROFITABILITY_EXPERIMENT_REPORT.md`,
`ENGINEERING_DECISIONS.md` #37-#40, `ROADMAP.md`.

## Core rule completion (MVP) — ✅ COMPLETE (2026-07-12)

Operator directive (2026-07-11): before resuming any parameter
optimization/sweeps/multi-year backtests, finish these 5 core Jade
strategy rules, in this order. All 5 are now done; each item's docs
(this file, ROADMAP, ENGINEERING_DECISIONS) and a commit landed when it
shipped — this list remains the single source of truth for what's done.

| # | Rule | Status |
|---|---|---|
| 1 | Premium/Discount calculation from current swing range | ✅ Shipped — `app.strategy.premium_discount.calculate_premium_discount`, unit-tested, spec'd (`docs/strategy_spec.md` §8). Detection only when shipped; now also wired as an opt-in TP extension target (see #4) |
| 2 | Previous swing high/previous swing low detection | ✅ Shipped — `app.strategy.market_structure.find_previous_swing_high`/`find_previous_swing_low`, unit-tested, spec'd (§3) |
| 3 | OB + FVG confluence entry model | ✅ Shipped — opt-in `require_ob_fvg_confluence` on `build_entry_model` (default off), threaded through `SignalEngine`/`BacktestEngine`/`run_backtest.py --ob-fvg-confluence`, unit/integration-tested, spec'd (§6). Not yet A/B backtested |
| 4 | TP logic: previous high/low first, HTF-permitting extension to 0.5 equilibrium | ✅ Shipped — opt-in `use_structure_tp` on `build_entry_model` (default off, depended on #1 and #2), threaded through `SignalEngine`/`BacktestEngine`/`run_backtest.py --structure-tp`, unit/integration-tested, spec'd (§6, §8). Not yet A/B backtested |
| 5 | Equal High/Equal Low liquidity detection | ✅ Shipped — `app.strategy.liquidity.detect_equal_highs`/`detect_equal_lows`, unit-tested, spec'd (§2). Detection only; not yet wired into `SignalEngine` |

## Phase 1 gate status (operator scope lock)

Objective: build, validate, and prove ONE profitable JadeCap automated
trading system. Nothing else. See `ROADMAP.md`'s "Phase 2 (deferred)"
section for ideas explicitly out of scope until these 4 gates clear.

| Gate | Status |
|---|---|
| 1. Backtest | ✅ Complete — 4 assets x 2026, BTCUSDT also x 2025. Controlled parameter sweep complete, 4 tuned defaults adopted (+66.7% PnL vs. old defaults on BTC 2026) |
| 2. Walk-forward validation | ✅ CLOSED under BOTH the old and new (tuned) defaults — 24/24 periods profitable across all 4 assets each time, PnL improved on every asset under the new defaults (BTC +66.7%, ETH +4.6%, SOL +32.6%, XRP +39.0%) |
| 3. Paper trading | ✅ Pipeline complete and running (`scripts/run_paper.py`), no real capital. Risk controls hardened (circuit breaker now auto-resets) |
| 4. Small live validation | ❌ Not started — requires operator-issued API keys + staged approval + real balance integration (`PLACEHOLDER_ACCOUNT_BALANCE` explicitly deferred here, operator decision) |

## One-paragraph summary

JadeCap is a Smart-Money-Concepts (SMC/ICT-style) crypto trading bot
built as a **research platform first, execution platform second**. It
has a real Strategy Engine (HTF bias, liquidity sweep, CHOCH/MSS, FVG,
order block, zone-mitigation, confluence entry model), a real Risk
Engine (RR floor, daily/weekly loss limits, position sizing, circuit
breaker, all DB-persisted), a real Backtest Engine (deep OKX history via
paginated fetch, no-lookahead HTF cursor, real fee/slippage/PnL model,
out-of-sample period splitting), a real Paper Trading loop
(`scripts/run_paper.py`, open/close positions against a real OKX
candle feed, no real money), and a real Dashboard (all 5 endpoints
backed by live data). Live Trading is **entirely unimplemented**
(`NotImplementedError` stubs) and gated behind explicit operator
approval — this is by design, not an oversight.

## Layer-by-layer status

| Layer | Status | Notes |
|---|---|---|
| Data (candle fetch) | ✅ Complete | Real OKX public API, deep pagination via `/market/history-candles` (fixed a long-standing 300-candle cap bug), no API key needed. `fetch_ohlcv_history()` can now anchor a fetch to end at a specific past date (`end_time_ms`), enabling genuine cross-YEAR backtesting via `run_backtest.py --end-date` |
| Strategy Engine | ✅ Core rule MVP complete | Bias/sweep/CHOCH/FVG/OB/zone-mitigation/entry-model all real, all tested. Breaker Block detection wired in (opt-in, `use_breaker_block`, A/B tested — see findings below). Confluence-strength spec ambiguity RESOLVED — the existing looser rule (sweep OR CHOCH) is confirmed correct with A/B evidence; `require_full_confluence`/`--strict-confluence` available as an opt-in but not recommended. Core-rule constants TUNED via controlled parameter sweep (`entry_model._RR`=2.5, `_STOP_BUFFER`=0.0015, `order_block._LOOKBACK`=15, `_IMPULSE_MULT`=1.8 — all previously untuned defaults) — see `docs/parameter_sweep_report.md`. **All 5 MVP core rules now shipped** (Premium/Discount, previous swing high/low, OB+FVG confluence, structure-based TP, Equal High/Equal Low) — see "Core rule completion (MVP)" above. The two newest, `require_ob_fvg_confluence`/`use_structure_tp`, ship opt-in and default OFF pending A/B backtest evaluation, same discipline as `use_breaker_block` |
| Risk Engine | ✅ Complete | RR floor, daily/weekly loss limits, trades/day cap, position sizing, DB-persisted circuit breaker — all enforced in both paper AND backtest. Circuit breaker now auto-resets once a fresh daily/weekly check clears (previously a documented gap — see `ENGINEERING_DECISIONS.md` #16). Sizing/loss-limit math still keys off `PLACEHOLDER_ACCOUNT_BALANCE`, intentionally, until Phase 1 gate #4 |
| Backtest Engine | ✅ Complete, actively used for research | Real fee/slippage/PnL, no-lookahead HTF cursor, multi-period out-of-sample splitting (`--periods`, HTF fetch now correctly sized to the LTF request's real time span), time-anchored fetching (`--end-date`), walk-forward validation (`--walk-forward`, explicit PASS/FAIL criteria — PASSED for BTCUSDT baseline), opt-in break-even (`--breakeven`, A/B **no reliable direction across 4 assets OR across 2 years on the same asset — even flips sign on BTCUSDT alone**), opt-in Breaker Block entries (`--breaker-block`, A/B **mostly negative across assets, zero effect in the 2025 BTCUSDT window**), opt-in partial take-profit (`--partial-tp`, A/B **negative on all 4 tested assets AND both tested years on BTCUSDT — the most robust finding in the project**) |
| Paper Trading | ✅ Complete | Real open/close/PnL against live OKX data, no real capital. Break-even stop management is wired here too (`settings.ENABLE_BREAKEVEN`, off by default, PERMANENTLY -- see research findings below) — no reliable direction exists across assets OR across time (it flips sign on BTCUSDT alone between 2025 and 2026), so there is no direction to ever default toward. Breaker Block and partial-TP remain backtest-only (no positive evidence justifying paper trading) |
| Portfolio/Journal | ✅ Complete | Real trade/signal persistence, daily/weekly/all-time reports |
| Dashboard | ✅ Complete | All 5 endpoints (`status`, `positions`, `logs`, `risk-status`, `bias`, `signals`) real, DB/live-computed |
| Live Trading | ❌ Not implemented, intentionally gated | `LiveBroker`, `exchange/okx_client.py`, `exchange/orangex_client.py` are all `NotImplementedError` stubs. Requires operator-approved API keys + staged approval before ANY code is written here |

## Test suite

366 backend tests, 0 known failures (363 + 3 new `structure_tp_max_r`
tests, 2026-07-12 profitability sprint -- see ENGINEERING_DECISIONS.md
#39/#40). Run: `cd backend &&
./.venv/Scripts/python.exe -m pytest -q`
(or the platform-appropriate venv path). No frontend test failures
(`npx tsc --noEmit` clean as of the last frontend-touching change).
`scripts/run_paper.py` itself has no direct pytest coverage (needs a live
network candle feed); its DB-backed logic (`TradeTracker.update_stop_loss`,
`_maybe_move_to_breakeven`) is instead verified via a real-temp-SQLite-DB
script exercising long/short/idempotency/disabled-gate paths end to end.

## Current research findings (the actual point of this project)

- **First Jade engine A/B result: bad, stays opt-in/off by default**
  (2026-07-12). The full Jade methodology (5 entry models, exit
  targets, HTF confluence, trendline, CRT, session bias -- see
  `ENGINEERING_DECISIONS.md` #23-#33) was wired end-to-end into
  `SignalEngine`/`BacktestEngine`/`scripts/run_paper.py` behind
  `use_jade_engine`/`settings.USE_JADE_ENGINE` (both default `False`)
  and A/B tested against the existing pipeline at this project's
  standard scale (BTCUSDT, `--candles 3000 --periods 6 --walk-forward`).
  **Result: 6 total trades vs. the legacy pipeline's 47 on the same
  data, 0/6 profitable periods vs. 6/6, -$77.28 total PnL vs. +$1,334.17,
  walk-forward FAILED vs. PASSED.** Not a marginal or mixed result.
  A real performance bug (unbounded displacement-candidate complexity)
  was also found and fixed along the way -- see
  `ENGINEERING_DECISIONS.md` #35/#36 for the full numbers, the
  (unconfirmed) hypothesis for the trade-count gap, and why this is
  disclosed as a real finding despite being only 1 asset/1 window so
  far. **Not recommended for use; `use_jade_engine` stays off.**
- **Deep-history backtesting works** (was capped at ~300 candles/~1 day
  until a real OKX pagination bug was fixed). This is the single most
  important infrastructure fix in the project's history — nothing about
  strategy validity could be assessed before it.
- **A real strategy bug was found and fixed**: `SignalEngine` could
  generate near-duplicate signals re-entering a zone price had already
  tested and failed at. Fixing it flipped a 28-trade BTCUSDT/15m sample
  from -$577.82/25% win rate to +$462.18/75% win rate.
- **Out-of-sample validation exists** (`--periods N`, splits fetched
  history into independent, non-overlapping chronological chunks) and
  has now been run on FOUR independent assets at 6-month/6-period scale
  (BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT — all January-July 2026, genuinely
  varied conditions: win rates 40%-100%, trade counts 5-40 across
  periods and assets). The strategy's baseline (no experimental
  features) was **6 of 6 periods profitable on all four assets**.
- **Full rule-by-rule coverage audit exists**: `docs/strategy_coverage_audit.md`.
  Found three items implemented, unit-tested, but never wired into the
  live decision loop. **All three are now wired, A/B tested, and
  re-tested on four independent 6-month asset samples**:

  | Feature | BTCUSDT | ETHUSDT | SOLUSDT | XRPUSDT | Verdict |
  |---|---|---|---|---|---|
  | Break-even (`--breakeven`) | +9.2% | -1.9% | -4.8% | +5.4% | **No reliable direction — 2 of 4 positive, 2 of 4 negative** |
  | Breaker Block (`--breaker-block`) | -3.8% | -12.0% | -1.9% | +1.5% | **Mostly negative — 3 of 4 negative, 1 of 4 positive** |
  | Partial TP (`--partial-tp`) | -32.6% | -35.4% | -29.1% | -28.7% | **Negative on 4 of 4, 24 of 24 periods — the one solid finding** |

  - **Break-even**: positive on BTCUSDT (+13.5% small sample, +9.2%
    6-month) and XRPUSDT (+5.4%); negative on ETHUSDT (-1.9%) and
    SOLUSDT (-4.8%). A 3-asset run had suggested a negative lean (2 of 3
    negative); the 4th asset broke that lean rather than confirming it.
    **This reversal is itself the important finding**: an apparent trend
    from a small number of ASSETS (not periods) reverted to a coin flip
    with one more data point, the same failure mode
    `ENGINEERING_DECISIONS.md` entries #14/#15 already warned about for
    small period counts — it turns out to apply to small asset counts
    too. **Conclusion: no asset-agnostic direction exists** for this
    feature with the evidence gathered so far. This is why
    `ENABLE_BREAKEVEN` ships off by default PERMANENTLY, not
    provisionally pending more data — more assets in the same time
    window are unlikely to resolve a genuine coin flip; the useful next
    test is a different YEAR (see caveats below), not a 5th asset.
  - **Partial take-profit**: negative on all 4 assets, 24 of 24 tested
    periods worse, zero exceptions anywhere. -31.4%/-32.6% (BTC small/
    6-month), -35.4% (ETH), -29.1% (SOL), -28.7% (XRP). Mechanistic
    cause identified and holds on every asset: this strategy has a fixed
    2:1 RR and tends toward a high win rate — locking in half the
    position at 1R trades away half of every full winner's upside, while
    rarely protecting losers (which mostly never reach +1R before
    reversing to the stop). **The single most robust finding in the
    project — solid enough to actively recommend against, not just
    decline to recommend.**
  - **Breaker Block**: negative on 3 of 4 assets (-3.8% BTC, -12.0% ETH,
    -1.9% SOL), positive on 1 (+1.5% XRP). Mostly negative, no longer
    unanimous — "not recommended" still holds given the majority
    direction, but "negative on every tested asset" is no longer an
    accurate description of the evidence.

  All three kept opt-in and non-default in the Backtest Engine. Of the
  three, only break-even was ever wired into paper trading
  (`settings.ENABLE_BREAKEVEN`, off by default) — it shipped while its
  evidence still looked BTCUSDT-consistent; three subsequent validation
  rounds (ETHUSDT, SOLUSDT, XRPUSDT) revealed the true picture is a
  cross-asset coin flip. The off-by-default choice is now a settled
  design conclusion, not a placeholder waiting on more evidence: an
  operator who had defaulted it ON based on the BTCUSDT evidence alone
  would today be running a feature with literally no reliable expected
  sign on a randomly chosen asset.
- **Cross-YEAR validation now exists too, not just cross-asset**: a new
  `end_time_ms`/`--end-date` capability lets a backtest be anchored to
  end at a specific past date instead of always "now". First real use:
  BTCUSDT, same 6-month/6-period methodology, anchored to 2025-07-10
  instead of 2026-07-10. Baseline was still 6 of 6 periods profitable,
  but in a visibly different regime (67 total trades vs. many more in
  2026, one period had only 2 trades). **Break-even flips sign on
  BTCUSDT itself between the two years** (+9.2% in 2026, **-1.9%** in
  2025) — the single clearest piece of evidence in the project that this
  feature has no reliable direction along ANY tested dimension, asset or
  time. Breaker Block had exactly 0.0% effect in the 2025 window
  (identical to baseline in every period). Partial TP reproduced almost
  exactly across years (-32.6% in 2026 vs. -32.1% in 2025) — now
  confirmed negative across 4 assets in one time window AND 2 time
  windows on one asset, the strongest evidentiary base for any finding
  in this project.
- **Walk-forward validation (Phase 1 gate #2) now exists as a formal,
  reusable artifact**: `run_backtest.py::walk_forward_report()` +
  `--walk-forward` evaluate a chronological period sequence against
  explicit criteria (>= 66% profitable periods, <= 2 consecutive losing
  periods, no >50% first-half-to-second-half PnL falloff) rather than
  just an aggregate sum — catching degradation trends and losing streaks
  an aggregate could hide. This is deliberately NOT a rolling
  parameter-refitting walk-forward (the strategy has no tunable
  parameters to refit yet — see `ENGINEERING_DECISIONS.md` #8); it's a
  genuine check that performance holds up moving forward through
  chronological time. **Real result: PASSED unanimously on all 4 tested
  assets** — BTC ($237->$408), ETH ($367->$541), SOL ($586->$814), XRP
  ($474->$476) all show 6/6 profitable periods, 0 losing streaks, and a
  second half that performed flat-or-better than the first. Zero
  degradation detected on any asset. Phase 1 gate #2 is now closed for
  the current asset set.
- **Controlled parameter sweep completed and adopted**: JadeCap's four
  core-rule constants (`entry_model._RR`/`_STOP_BUFFER`,
  `order_block._LOOKBACK`/`_IMPULSE_MULT`) were previously disclosed as
  "reasonable defaults, not tuned against real performance data". A
  one-at-a-time sweep (never a full grid — avoids the overfitting risk
  of testing 256 combinations at once), selecting candidates by
  robustness (walk-forward pass, meaningful trade count,
  profitable-period ratio and average-R both >= baseline) rather than
  highest profit, found a robust improvement for all four: `_RR`
  2.0->2.5, `_STOP_BUFFER` 0.001->0.0015, `_LOOKBACK` 10->15,
  `_IMPULSE_MULT` 1.5->1.8. Each cleared in-sample selection (BTCUSDT),
  held-out out-of-sample validation (never inspected during selection),
  AND cross-asset validation (ETHUSDT/SOLUSDT/XRPUSDT). Before adopting,
  the combined 4-parameter profile was ALSO checked against BTCUSDT
  anchored to 2025 (a cross-YEAR check, added beyond the operator's
  original sweep scope specifically because this project already found
  cross-asset robustness alone insufficient for break-even) — held up:
  +33.5% PnL, same profitable-period count. A final confirmatory run on
  this project's standard reporting scale (BTC 2026, `--periods 6
  --walk-forward`) showed **+66.7% PnL with walk-forward still PASSING
  cleanly** (0 losing streak, no degradation). Full methodology, every
  number, and explicitly stated caveats (the validation window is still
  only ~6 months plus one 2025 spot-check; interaction effects between
  the four parameters were only spot-checked, not fully swept) in
  `docs/parameter_sweep_report.md`. A real, if unplanned, finding along
  the way: `BacktestEngine`'s walk-forward scan is far worse than linear
  in period length (3000 candles ~88s vs. 1500 candles ~7s) — the
  initial sweep attempt at the usual 3000-candle scale ran 80+ minutes
  with zero visible output before being killed and redesigned.
- **Phase 1 gate #2 (walk-forward validation) fully re-closed under the
  new tuned defaults, all 4 assets**: the parameter sweep above only
  re-confirmed BTCUSDT at this project's standard reporting scale.
  Re-ran ETHUSDT/SOLUSDT/XRPUSDT the same way (`--candles 3000
  --periods 6 --walk-forward`) and all three **PASSED unanimously**:
  6/6 periods profitable each, 0 losing streaks, no degradation. PnL
  improved on every single asset vs. the old (untuned) defaults: BTC
  +66.7%, ETH +4.6%, SOL +32.6%, XRP +39.0%, combined +33.3%
  ($11708.78 -> $15607.93 across all 4 assets). At the time, this was
  the most thoroughly validated state JadeCap's core strategy had been
  in this project's history for the 2026 window specifically.
- **First full cross-year check (2025) on all 4 assets under the new
  tuned defaults — 8 of 9 combinations PASS, 1 real exception found**:
  extended the above to 2025 (`--end-date 2025-07-10`, same standard
  scale). ETHUSDT ($3090.03), SOLUSDT ($4289.78), and XRPUSDT ($4300.39)
  all **PASSED cleanly** — first time any of these three had been tested
  outside the 2026 window. BTCUSDT 2025 at this standard scale
  **FAILED its own walk-forward degradation check**: every one of the 6
  periods was individually profitable ($1714.56 total), so the
  aggregate/profitable-period criteria passed, but the second half's
  average PnL ($149.40) retained only 35.4% of the first half's
  ($422.13) — below the 50% retention threshold. This is a real,
  measured decline (Apr-Jun 2025 meaningfully weaker than Jan-Mar 2025
  under the new defaults specifically), not an artifact. Notably, this
  did NOT show up in the parameter sweep's own BTC-2025 spot-check
  (`docs/parameter_sweep_report.md` §6), which used smaller 1500-candle
  periods and a different period-boundary split — a real, informative
  example of walk-forward conclusions depending on the exact period
  granularity chosen, not just the underlying price data. Not treated
  as a reason to revert the new defaults (BTC 2025 remained net
  profitable throughout, and 8 of 9 standard-scale combinations passed
  cleanly) — but recorded as a genuine, disclosed caveat: the new
  defaults' robustness on BTCUSDT specifically is weaker across time
  than across assets. See `ROADMAP.md` for the natural follow-up
  (investigate whether this is new-defaults-specific or a genuine
  BTC-specific regime shift that the old defaults would show too).
- **Confluence-strength spec ambiguity resolved with real A/B evidence**:
  `docs/strategy_spec.md` section 6's prose previously read as requiring
  ALL of bias + sweep + CHOCH + FVG/OB in confluence; the actual code
  had always required only bias + (sweep OR CHOCH) + (FVG OR OB), a
  strictly looser bar (`docs/strategy_coverage_audit.md` row #9). Added
  opt-in `require_full_confluence` (`--strict-confluence`), A/B tested
  across all 4 assets, 6-month/6-period each: requiring BOTH sweep AND
  CHOCH cuts trade count 75.9% (457 -> 110 across the 4-asset sample)
  for a per-trade PnL only 3.8% different from the looser default --
  not meaningfully higher quality, just far fewer trades of the same
  quality, costing ~75% of total realized profit. **Resolved in favor
  of the existing looser implementation** -- the spec text itself was
  rewritten to state the confluence rule explicitly (sweep OR CHOCH),
  closing the ambiguity for good rather than leaving it open. This is
  the fourth time in this project that "does adding a stricter/more
  cautious rule actually help" was tested rather than assumed, and the
  fourth time the answer required real data to determine (break-even:
  yes on one asset, no on others; Breaker Block: mostly no; partial-TP:
  no; strict confluence: no).
- **Data-layer bug found and fixed along the way**: `scripts/run_backtest.py`
  requested the same candle COUNT for both LTF and HTF fetches, which
  for a large `--periods` request meant asking for years more HTF
  history than needed (18000 candles at `4h` = ~8.2 years vs. the ~187
  days actually needed). Fixed with `timeframe_to_timedelta()` +
  `htf_candle_count_for_span()`, which size the HTF request off the
  real time span the LTF request covers.

## Honest caveats (read before citing these results anywhere)

- 4 assets checked (BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT), all large-cap
  tokens with broadly similar market beta — not a genuinely diverse
  asset set, and two of the three findings (break-even, Breaker Block)
  already show no unanimous direction even within this correlated set.
- Only 2 time windows checked at all (2025-07 and 2026-07, both anchored
  to BTCUSDT only) — every other asset (ETH/SOL/XRP) is still tested in
  the 2026 window alone. A 2024 window, or the 2025 window on the other
  three assets, remain untested.
- Per-period trade counts (2-40 across all samples so far, with the 2025
  BTCUSDT window's period 1 at just 2 trades) are still modest in
  places; win-rate confidence intervals remain wide, especially for the
  smaller-trade-count periods.
- `_RR`/`_STOP_BUFFER`/`_LOOKBACK`/`_IMPULSE_MULT` are now TUNED (2026-07-11
  controlled parameter sweep, `docs/parameter_sweep_report.md`) using the
  `--periods` tool's held-out-period discipline — validated across 2026
  AND 2025 on all 4 assets at this point (8 of 9 standard-scale
  combinations clean, 1 real BTCUSDT-2025 degradation exception, see
  above), still only 2 calendar years and 4 correlated large-cap assets
  though, and the one-at-a-time sweep methodology never tested
  interaction effects between the four parameters together (only a
  small number of confirmatory runs of the combined profile).
  `BREAKEVEN_TRIGGER_R`/
  `PARTIAL_TP_TRIGGER_R`/`PARTIAL_TP_PORTION` remain untuned, disclosed
  defaults — deliberately excluded from this round since they only affect
  the off-by-default experimental features (see `ROADMAP.md`). Any future
  parameter work must keep using the same held-out-period discipline or
  the entire point of the tooling is defeated.

**Conclusion: one finding is now solid across every dimension tested, two
are genuinely unresolved across every dimension tested — and
"unresolved" is itself a real, useful result, not a gap in the
process.** Partial-TP's negative verdict has now reproduced on 4
independent assets (24/24 periods) AND across 2 independent years on the
one asset checked both ways — as strong an evidentiary base as this
project has produced for anything, strong enough to actively recommend
against using it. Break-even and Breaker Block both show results with no
reliable direction along EITHER axis: break-even flips sign both across
assets (2 of 4 positive) and across time on the SAME asset (+9.2% to
-1.9% on BTCUSDT alone). This is the clearest demonstration in this
project so far of why small counts of ANYTHING (periods, assets, or now
time windows) can manufacture the appearance of a trend that isn't real.
See `ROADMAP.md` for what's next.
