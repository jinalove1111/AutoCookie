# JadeCap Strategy Coverage Audit

Date: 2026-07-10. Scope: every rule documented in `docs/architecture.md`'s
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
| 6 | Order Block Detection (`order_block.py`) | Implemented, now returns `impulse_index` | Unit tested | Only the single most-recent OB is ever considered; `_LOOKBACK=10`/`_IMPULSE_MULT=1.5` explicitly documented as untuned | Untuned constants, disclosed in-code | None | MEDIUM |
| 7 | **Breaker Block Detection** (`detect_breaker_block`) | **UPDATE #2 (re-tested at scale): wired into `SignalEngine.generate_signal(use_breaker_block=False)`, opt-in, A/B tested on TWO independent samples.** Small sample (~31 days): zero measured effect. Larger sample (6 months, BTCUSDT): fired for real in 1 of 6 periods, effect NEGATIVE (win rate 90.48% -> 85.71%, aggregate -3.8%). Conclusion REVISED from "neutral" to "slightly negative" -- exactly the kind of thing more out-of-sample data is supposed to reveal. See CHANGELOG.md/HANDOFF.md/ENGINEERING_DECISIONS.md #14 for full evidence. Kept opt-in, not made default | Unit + end-to-end integration tests exist (`test_strategy_entry_model.py`, `test_strategy_signal_engine.py`) | None remaining at the wiring level; still only 1 real data point of "it fired and hurt" -- more samples would sharpen this further | Assumes a mitigated OB that reverses (a "breaker") is a valid setup -- tested twice, leaning negative so far | Resolved: now wired, matching spec section 5 | LOW (wired + tested; evidence leans negative, not neutral) |
| 8 | Zone Mitigation Filter (`utils.is_zone_mitigated`) | Implemented this session | Unit + end-to-end regression test | None major yet | Any wick overlap = mitigated (no partial-fill/percentage nuance) | None | LOW (just shipped, verified against real data) |
| 9 | Entry Model / confluence combination (`entry_model.py`) | Implemented | Unit tested | Binary confluence only (no strength scoring); a signal with exactly 1 of 4 possible confluence factors is treated identically to one with all 4; RR is always a fixed 2.0, never derived from structure | `_RR=2.0`, `_STOP_BUFFER=0.001` both explicitly disclosed as "reasonable defaults, not tuned" | Spec section 6 says entry requires bias + sweep + CHOCH + FVG/OB to "have confluence" (reads as ALL); actual code requires bias + (sweep OR choch) + (FVG OR OB) — a real, never-resolved gap between spec wording and implementation | MEDIUM |
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
| 19 | **Handle break-even move** (`OrderManager.move_to_breakeven`) | **Implemented but NEVER called anywhere outside its own module** — no live/paper/backtest trade has ever had its stop moved to break-even | Unit tested in isolation only (pure function correctness); zero integration coverage | Never triggers automatically during an open trade in paper OR backtest | Assumes moving to break-even after a favorable move improves risk-adjusted returns — **completely unverified empirically** | None — this is unambiguous dead code, and `docs/architecture.md` explicitly lists it as a core Execution Engine responsibility | **HIGH** |
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

## Summary: highest-impact gaps — ALL THREE RESOLVED

Three items were originally marked **HIGH** and shared the same shape —
real logic that already existed, was unit-tested in isolation, and was
**completely disconnected from the live decision loop**. All three are
now wired, A/B tested against an initial 6-period sample (BTCUSDT/ETHUSDT
15m, ~31 days), AND re-tested against a much larger 6-month/6-period
sample (BTCUSDT only so far) -- two verdicts reproduced, one was revised:

1. ~~Break-even stop management (never wired into trade exit handling)~~ —
   **RESOLVED, POSITIVE, REPRODUCED**: wired (opt-in `--breakeven`),
   +13.5% on the small sample, +9.2% on the 6-month sample (same
   direction, independent data -- the most robust of the three). Kept
   opt-in (backtest-only so far; not yet wired into paper trading, see
   `ROADMAP.md` item #1 — this is the one with the strongest case for
   eventually promoting to paper trading).
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

The fact that identical A/B methodology applied to three similar-looking
"wire up dead code" changes produced three different verdicts (neutral /
positive / negative) is itself the main lesson: **assuming any of these
would help without measuring would have been wrong at least twice out of
three times.** See `ROADMAP.md` for what's next (expanding out-of-sample
periods to different market regimes is now the highest-value item,
since all three verdicts above rest on the same single ~31-day window).

Break-even was implemented first because it was the cleanest to
validate: unlike the other two, it changes ONLY exit management, not
which trades get taken or how much size they use — holding entry logic
completely constant makes a before/after backtest comparison a clean,
controlled experiment. Breaker Block was implemented second (adds a new
signal source, still a single clean before/after comparison since it
doesn't touch exit logic). Partial TP remains, deliberately last, since
splitting PnL into two legs is the most confounding of the three to
compare cleanly.
