# JadeCap Strategy Coverage Audit

Date: 2026-07-10, last updated 2026-07-11. Scope: every rule documented in `docs/architecture.md`'s
six-layer design, `docs/strategy_spec.md`, and `docs/risk_rules.md`,
cross-referenced against the actual implementation in `backend/app/` and
its test coverage. Purpose: find the highest-impact GAP before writing
any more code, per operator instruction, not to re-litigate rules already
confirmed working.

Legend — **Priority**: HIGH = implemented-but-disconnected or a real,
evidenced gap; MEDIUM = works but has a known, documented limitation;
LOW = complete, tested, no known issue; N/A = out of scope (Live Trading,
gated).

## Strategy Engine

| # | Rule | Implementation status | Test coverage | Missing logic | Assumptions | Ambiguity | Priority |
|---|------|----|----|----|----|----|----|
| 1 | HTF Bias Detection (`bias.py`) | Implemented | 4 unit + integration | None | Last 3 swing highs/lows only; no volume/momentum confirmation | None — matches spec | LOW |
| 2 | Real HTF/LTF series separation | Implemented | Dedicated regression test proves HTF-not-LTF | None | None | None | LOW |
| 3 | Liquidity Sweep Detection (`liquidity.py`) | Implemented — single swing-point sweep only | Unit tested | **No "equal highs/lows" (multi-touch liquidity pool) detection** — only sweeps of a single prior swing point are recognized | Assumes one swing point = one liquidity pool | Spec section 2 doesn't define equal-highs/lows either — a spec gap, not just a code gap | MEDIUM |
| 4 | CHOCH/MSS Detection + swept-index causality (`market_structure.py`) | Implemented | Unit + causality-specific tests | None major | Fixed `n=2` swing window; no multi-bar confirmation | None | LOW |
| 5 | FVG Detection (`fvg.py`) | Implemented | Unit tested | No minimum gap-size threshold — any nonzero imbalance counts | Assumes any 3-candle gap is tradeable | Spec doesn't define a minimum size either | MEDIUM |
| 6 | Order Block Detection (`order_block.py`) | Implemented, now returns `impulse_index`. `_LOOKBACK`/`_IMPULSE_MULT` TUNED (2026-07-11, controlled parameter sweep): 10->15 / 1.5->1.8, both robust across in-sample, out-of-sample, cross-asset (BTC/ETH/SOL/XRP), AND cross-year validation -- see `docs/parameter_sweep_report.md` | Unit tested; sweep validated via real backtests across 4 assets + 2 years | Only the single most-recent OB is ever considered | None -- constants are now tuned, not just disclosed defaults | None | LOW |
| 7 | **Breaker Block Detection** (`detect_breaker_block`) | **UPDATE #2 (re-tested at scale): wired into `SignalEngine.generate_signal(use_breaker_block=False)`, opt-in, A/B tested on TWO independent samples.** Small sample (~31 days): zero measured effect. Larger sample (6 months, BTCUSDT): fired for real in 1 of 6 periods, effect NEGATIVE (win rate 90.48% -> 85.71%, aggregate -3.8%). Conclusion REVISED from "neutral" to "slightly negative" -- exactly the kind of thing more out-of-sample data is supposed to reveal. See CHANGELOG.md/HANDOFF.md/ENGINEERING_DECISIONS.md #14 for full evidence. Kept opt-in, not made default | Unit + end-to-end integration tests exist (`test_strategy_entry_model.py`, `test_strategy_signal_engine.py`) | None remaining at the wiring level; still only 1 real data point of "it fired and hurt" -- more samples would sharpen this further | Assumes a mitigated OB that reverses (a "breaker") is a valid setup -- tested twice, leaning negative so far | Resolved: now wired, matching spec section 5 | LOW (wired + tested; evidence leans negative, not neutral) |
| 8 | Zone Mitigation Filter (`utils.is_zone_mitigated`) | Implemented this session | Unit + end-to-end regression test | None major yet | Any wick overlap = mitigated (no partial-fill/percentage nuance) | None | LOW (just shipped, verified against real data) |
| 9 | Entry Model / confluence combination (`entry_model.py`) | Implemented; confluence-strength ambiguity RESOLVED (opt-in `require_full_confluence` A/B tested across 4 assets, 6-month/6-period each: requiring both sweep AND choch cuts trade count ~76% for a per-trade PnL within 4% of the looser default — no quality gain, just far fewer trades, ~75% less total profit). `_RR`/`_STOP_BUFFER` TUNED (2026-07-11, controlled parameter sweep): 2.0->2.5 / 0.001->0.0015, both robust across in-sample, out-of-sample, cross-asset, AND cross-year validation — see `docs/parameter_sweep_report.md` | Unit + integration tested (`test_strategy_entry_model.py`, `test_strategy_signal_engine.py`); sweep validated via real backtests across 4 assets + 2 years | Binary confluence only (no strength scoring); a signal with exactly 1 of 4 possible confluence factors is treated identically to one with all 4; RR is always a fixed value (now 2.5), never derived from structure | None -- `_RR`/`_STOP_BUFFER` are now tuned, not just disclosed defaults | RESOLVED: `docs/strategy_spec.md` section 6 updated to explicitly state the confluence rule requires EITHER sweep or CHOCH (not both), matching the code — see that doc for the full A/B evidence. `require_full_confluence=True` remains available as an opt-in for further research but is not recommended | LOW (resolved, evidenced) |
| 10 | Signal Engine orchestration (`signal_engine.py`) | Implemented | Integration tested | None | None | None | LOW |

## Risk Engine

| # | Rule | Implementation status | Test coverage | Missing logic | Assumptions | Ambiguity | Priority |
|---|------|----|----|----|----|----|----|
| 11 | RR minimum 1:2 (`MIN_RR`) | Implemented, enforced in Risk + Execution (defense in depth) | Tested | None | None | None | LOW |
| 12 | `MAX_DAILY_LOSS_PERCENT` | Implemented, enforced in paper AND backtest | Tested incl. real-DB integration | None | None | None | LOW |
| 13 | `MAX_WEEKLY_LOSS_PERCENT` | Same as above | Same | None | None | None | LOW |
| 14 | `RISK_PER_TRADE_PERCENT` / position sizing | Implemented | Tested | None | Sizing uses the planned (pre-slippage) entry/stop, not the real fill — documented, intentional, matches `BacktestEngine`'s own sizing order | None | LOW |
| 15 | `MAX_TRADES_PER_DAY` | Implemented, enforced | Tested | None | None | None | LOW |
| 16 | Circuit breaker (trip/reset, DB-persisted across restarts) | Implemented | Extensively tested (incl. crash/respawn scenarios) | No automatic day/week-boundary reset | Documented as a deliberate design choice ("a human should look at *why*"), not a gap | None | LOW |

## Execution Engine

| # | Rule | Implementation status | Test coverage | Missing logic | Assumptions | Ambiguity | Priority |
|---|------|----|----|----|----|----|----|
| 17 | Place entry order | Implemented (PaperBroker); LiveBroker fully stubbed | Tested (paper path) | LiveBroker is `NotImplementedError` throughout | N/A — Live is explicitly gated, out of scope | None | N/A (Live) |
| 18 | Place SL/TP, exit checking | Implemented via `check_exit`/backtest scan-forward, incl. slippage on both entry and exit | Tested | Fixed levels only for the whole trade lifetime — no dynamic/volatility-based stop adjustment | None | None | MEDIUM |
| 19 | **Handle break-even move** (`OrderManager.move_to_breakeven`) | **STALE ROW, CORRECTED: RESOLVED.** Wired into `BacktestEngine._simulate_trade(use_breakeven=False)` (opt-in `--breakeven`) AND into paper trading (`scripts/run_paper.py::_maybe_move_to_breakeven`, gated by `settings.ENABLE_BREAKEVEN`, off by default) — the ONLY one of the three originally-HIGH gaps promoted to paper trading, since it's the one with real (if ultimately mixed) positive evidence. A/B tested across 4 assets AND 2 years on BTCUSDT: positive on BTCUSDT (both time windows), negative on ETHUSDT/SOLUSDT, positive on XRPUSDT, and flips sign on BTCUSDT ALONE between years — net conclusion: **no reliable direction across either assets or time**, so `ENABLE_BREAKEVEN` stays off by default PERMANENTLY (not provisionally). See CHANGELOG.md/PROJECT_STATUS.md/ENGINEERING_DECISIONS.md #15/#16 for the full multi-round evidence history | Unit + end-to-end integration tests (`test_backtest_engine.py`) plus a real-temp-SQLite-DB script for the paper-trading path (long/short/idempotency/disabled-gate) | None remaining at the wiring level | Assumed moving to break-even after a favorable move improves risk-adjusted returns — tested extensively (4 assets x 2 time windows on one), found to be regime/asset-dependent with no reliable global direction, not a clean win | Resolved: now wired in both backtest and paper trading, matching architecture.md's Execution Engine responsibility | LOW (wired + extensively tested; evidence is genuinely mixed, not a gap) |
| 20 | **Handle partial TP** (`OrderManager.handle_partial_tp`) | **UPDATE (re-tested at scale): wired into `BacktestEngine._simulate_trade(use_partial_tp=False)`, opt-in, A/B tested on TWO independent samples.** Result: NEGATIVE, REPRODUCED -- -31.4% on the small (~31-day) sample, -32.6% on a larger 6-month sample (BTCUSDT), reducing PnL in every single period on BOTH samples (12 of 12, no exceptions). Mechanistic cause: this strategy's fixed 2:1 RR + high win rate means locking in 50% at 1R trades away upside on winners without protecting losers (which mostly never reach +1R before reversing to stop). See CHANGELOG.md/HANDOFF.md/ENGINEERING_DECISIONS.md #12/#14 for full evidence and the ordering rationale (partial-TP checked before take_profit in a candle, not after). Kept opt-in, actively not recommended for the current strategy shape | Unit + end-to-end tests exist (`test_backtest_engine.py`) proving disabled/enabled/protection/same-candle-ordering/short-mirror behavior | None remaining at the wiring level; the negative result itself may be strategy-shape-specific (different RR/win-rate profile could flip it) | Assumed locking in early profit reduces risk -- tested twice, and for THIS strategy's profile it consistently reduces returns instead | Resolved: now wired, matching architecture.md's "Handle partial TP" responsibility | LOW (wired + tested; negative result reproduced on 2 samples, not a gap) |
| 21 | Handle exchange errors / cancel unsafe orders | Implemented (`safety_checks.verify_safe_to_trade`, `CandleFetcher` raises `ConnectionError`/`RuntimeError` rather than swallowing) | Tested | Live-specific exchange error handling deferred with `LiveBroker` | N/A — Live gated | None | N/A (Live) |

## Portfolio / Journal Engine

| # | Rule | Implementation status | Test coverage | Missing logic | Assumptions | Ambiguity | Priority |
|---|------|----|----|----|----|----|----|
| 22 | Track open/closed positions | Implemented | Tested | None | None | None | LOW |
| 23 | Track PnL (daily/weekly/all-time) | Implemented | Extensively tested | None | None | None | LOW |
| 24 | Save trade reason | Implemented | Tested | None | None | None | LOW |
| 25 | Save chart snapshot | Documented no-op stub | Tested (no-op verified, not silently missing) | Never actually persists a chart/screenshot | Explicitly deferred in the code's own docstring | None (honestly labeled) | LOW — cosmetic, not strategy-critical |
| 26 | Generate trade journal | Implemented (daily/weekly/all-time reports) | Extensively tested | None | None | None | LOW |

## Dashboard / Data Layer

| # | Rule | Implementation status | Test coverage | Missing logic | Assumptions | Ambiguity | Priority |
|---|------|----|----|----|----|----|----|
| 27 | All 5 `/dashboard/*` real-data endpoints | Implemented (this session) | Tested | `run_backtest.py`-generated signals are not persisted (deliberate scope boundary, `Signal` has no `mode` column) | Documented | None | LOW |
| 28 | Deep-history candle pagination (`CandleFetcher`) | Implemented (this session) | Tested | None | None | None | LOW |

## Summary: highest-impact gaps — ALL RESOLVED (updated 2026-07-11)

**Update (2026-07-11): as of this update, every item ever marked HIGH or
MEDIUM-with-a-real-ambiguity in this audit has been resolved with real
A/B evidence.** The remaining MEDIUM rows (equal-highs/lows liquidity,
FVG minimum gap size) are confirmed SPEC gaps, not code gaps or
ambiguities in an existing rule — `docs/strategy_spec.md` doesn't define
either — so per the operator's Phase 1 scope-lock instruction ("only
implement core JadeCap trading rules"), they stay undone until/unless
the operator decides to add them to the spec first. The Order Block
`_LOOKBACK`/`_IMPULSE_MULT` untuned-constants row is tracked separately
under `ROADMAP.md`'s parameter-sweep item (a distinct, larger
undertaking requiring proper held-out-period discipline, not a
same-round fix). Confluence-strength (row #9) was the most recent
resolution: A/B tested across all 4 assets, requiring both sweep AND
CHOCH cut trade count 76% for no measurable quality gain, so the
existing looser rule was confirmed correct and the spec text itself was
rewritten to remove the ambiguity (see `docs/strategy_spec.md` section 6
and `ENGINEERING_DECISIONS.md` #17).

Four items were originally marked **HIGH** or a real, unresolved
MEDIUM ambiguity and shared the same shape — real logic that already
existed (or a real spec/code disagreement), unit-tested in isolation,
and disconnected from either the live decision loop or a firm
resolution. All four are now wired/resolved, A/B tested against an
initial 6-period sample (BTCUSDT/ETHUSDT 15m, ~31 days), AND re-tested
against much larger samples (6-month/6-period across all 4 assets, plus
2 independent years on BTCUSDT) -- most verdicts reproduced or
strengthened, one was revised, one flat-out reversed direction across
time:

1. ~~Break-even stop management (never wired into trade exit handling)~~ —
   **RESOLVED, wired into BOTH backtest AND paper trading** (opt-in
   `--breakeven` / `settings.ENABLE_BREAKEVEN`, off by default,
   PERMANENTLY). Evidence evolved significantly across rounds: +13.5%
   small sample, +9.2% BTC 6-month sample (looked like the most robust
   finding at first) -- but subsequent testing across ETHUSDT/SOLUSDT/
   XRPUSDT AND a second year on BTCUSDT revealed NO reliable direction
   across either assets or time (it even flips sign on BTCUSDT alone
   between 2025 and 2026). See `PROJECT_STATUS.md`/`ENGINEERING_
   DECISIONS.md` #15/#16 for the full multi-round history -- this is
   the clearest lesson in the project on why small counts of ANYTHING
   (periods, assets, time windows) can manufacture an apparent trend.
2. ~~Partial take-profit (never wired into trade exit handling)~~ —
   **RESOLVED, NEGATIVE, REPRODUCED**: wired (opt-in `--partial-tp`),
   -31.4% on the small sample, -32.6% on the 6-month sample -- reduced
   PnL in every single period tested across BOTH samples (12 of 12, no
   exceptions). Mechanistic cause identified (this strategy's fixed 2:1
   RR + tendency toward a high win rate means partial exits trade away
   winner upside without protecting losers). Kept opt-in, actively not
   recommended for the current strategy shape (see row #20 above and
   `ENGINEERING_DECISIONS.md` #12/#14).
3. ~~Breaker Block detection (never wired into signal generation)~~ —
   **RESOLVED, REVISED from NEUTRAL to SLIGHTLY NEGATIVE**: wired
   (opt-in `--breaker-block`). Zero measured effect on the small sample;
   on the 6-month sample it fired for real in 1 of 6 periods and the
   effect was negative (aggregate -3.8%). This is the clearest
   demonstration in this project so far of why out-of-sample testing at
   increasing scale matters -- the smaller sample's "neutral" verdict was
   real but incomplete, not wrong exactly, just under-powered to detect
   an effect that needed more data to show up (see row #7 above and
   `ENGINEERING_DECISIONS.md` #14).
4. ~~Confluence-strength spec/code ambiguity (row #9)~~ — **RESOLVED IN
   FAVOR OF THE EXISTING (LOOSER) CODE**: A/B tested the stricter,
   spec-literal reading (`require_full_confluence` / `--strict-
   confluence`, requiring BOTH sweep AND CHOCH) across all 4 assets --
   it cut trade count 75.9% for a per-trade PnL only 3.8% different from
   the looser default, i.e. it filtered out mostly GOOD trades along
   with everything else, not selectively bad ones. `docs/strategy_
   spec.md` section 6 was rewritten to state the rule explicitly (sweep
   OR CHOCH), closing the ambiguity in the SPEC rather than leaving code
   silently override unclear prose. See `ENGINEERING_DECISIONS.md` #17.

The fact that identical A/B methodology applied to four similar-looking
"is a stricter/more-connected rule better" changes produced three
negative-or-mixed verdicts and only one clearly positive (and even that
one's positive verdict didn't survive broader testing) is itself the
main lesson of this project: **assuming any of these would help without
measuring would have been wrong at least three times out of four.**
Every core rule defined in `docs/strategy_spec.md` is now implemented,
tested, and (where the spec was ever ambiguous) resolved with real
evidence -- see `ROADMAP.md`'s Phase 1 gate table for overall project
status and what's next (further out-of-sample validation and parameter
tuning, not more core-rule implementation).

Break-even was implemented first because it was the cleanest to
validate: unlike the other two, it changes ONLY exit management, not
which trades get taken or how much size they use — holding entry logic
completely constant makes a before/after backtest comparison a clean,
controlled experiment. Breaker Block was implemented second (adds a new
signal source, still a single clean before/after comparison since it
doesn't touch exit logic). Partial TP remains, deliberately last, since
splitting PnL into two legs is the most confounding of the three to
compare cleanly.
