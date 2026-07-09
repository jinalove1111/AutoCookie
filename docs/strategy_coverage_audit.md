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
| 7 | **Breaker Block Detection** (`detect_breaker_block`) | **Implemented but NEVER called from `SignalEngine.generate_signal()`** — an entire alternate setup type sits completely unused | Unit tested in isolation only; zero integration coverage | `SignalEngine` has no path that ever produces a breaker-block-based signal | Assumes a mitigated OB that reverses (a "breaker") is a valid setup — never empirically checked | Spec section 5 explicitly lists Breaker Block as in-scope for the Strategy Engine, but the orchestrator never uses it | **HIGH** |
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
| 20 | **Handle partial TP** (`OrderManager.handle_partial_tp`) | **Implemented but NEVER called anywhere outside its own module** — same status as #19 | Unit tested in isolation only | Every trade is currently all-or-nothing (full size until stop or full TP); no scaled exits exist anywhere in the real pipeline | Same as #19 | Same as #19 | **HIGH** |
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

## Summary: highest-impact gaps

Three items are marked **HIGH** and share the same shape — real logic
that already exists, is unit-tested in isolation, and is **completely
disconnected from the live decision loop**:

1. Breaker Block detection (never wired into signal generation)
2. Break-even stop management (never wired into trade exit handling)
3. Partial take-profit (never wired into trade exit handling)

Between these, break-even stop management is the cleanest to validate:
unlike the other two, it changes ONLY exit management, not which trades
get taken or how much size they use — holding entry logic completely
constant makes a before/after backtest comparison a clean, controlled
experiment (the other two either add new signal sources or split PnL
into two legs, both confounding a single before/after comparison). It
also directly maps to "improved risk management," one of the operator's
explicitly approved justification categories. Selected as this round's
implementation target.
