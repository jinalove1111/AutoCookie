# PROJECT_STATUS — JadeCap Automated Trading Bot

This file is the always-current, English snapshot: what the system does
*right now*, as of the latest commit on `master`. It intentionally has
no history — for the round-by-round session log (in Korean, matching
this project's established working language for that file), see
`HANDOFF.md`. For chronological release notes, see `CHANGELOG.md`. For
the "why" behind specific non-obvious engineering choices, see
`ENGINEERING_DECISIONS.md`. For forward-looking prioritization, see
`ROADMAP.md`.

Last updated: 2026-07-11 (night CTO session: built walk-forward
validation, Phase 1 gate #2 -- now CLOSED, PASSED unanimously on all 4
tested assets (BTC/ETH/SOL/XRP). Hardened risk controls: circuit breaker
now auto-resets once a fresh daily/weekly check clears, closing a real
gap where a trip previously halted trading permanently with no
operator-facing reset path. Real-balance integration explicitly deferred
to gate #4 by operator decision. Resolved the confluence-strength spec
ambiguity (audit item #9, a genuine core rule) with real A/B evidence
across all 4 assets -- the existing looser rule is confirmed correct,
`docs/strategy_spec.md` rewritten to remove the ambiguity. Equal-highs/
equal-lows liquidity detection deliberately NOT implemented -- confirmed
not a currently-specified core rule, so out of scope per operator
instruction. Scope locked by operator directive this round: Phase 1 =
JadeCap only, tracked against 4 explicit gates, see below. All 3 audit
HIGH items wired, A/B tested, and
re-validated across 6 months of real market data on FOUR independent
assets AND a second independent YEAR via a new `--end-date` time-anchored
fetch capability. Break-even shows NO reliable direction across either
dimension -- it even flips sign on BTCUSDT alone between 2025 and 2026 --
so `ENABLE_BREAKEVEN` stays off by default, permanently. Partial TP is
the one finding solid enough to actively recommend against, having
reproduced negative across 4 assets (24/24 periods) AND across 2 years
on BTCUSDT alone).

## Phase 1 gate status (operator scope lock)

Objective: build, validate, and prove ONE profitable JadeCap automated
trading system. Nothing else. See `ROADMAP.md`'s "Phase 2 (deferred)"
section for ideas explicitly out of scope until these 4 gates clear.

| Gate | Status |
|---|---|
| 1. Backtest | ✅ Complete — 4 assets x 2026, BTCUSDT also x 2025 |
| 2. Walk-forward validation | ✅ CLOSED — PASSED on all 4 tested assets (24/24 periods profitable, 0 losing streaks, no degradation anywhere) |
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
| Strategy Engine | ✅ Complete, actively validated | Bias/sweep/CHOCH/FVG/OB/zone-mitigation/entry-model all real, all tested. Breaker Block detection now wired in too (opt-in, `use_breaker_block`, A/B tested — see findings below). Confluence-strength spec ambiguity RESOLVED — the existing looser rule (sweep OR CHOCH) is confirmed correct with A/B evidence; `require_full_confluence`/`--strict-confluence` available as an opt-in but not recommended |
| Risk Engine | ✅ Complete | RR floor, daily/weekly loss limits, trades/day cap, position sizing, DB-persisted circuit breaker — all enforced in both paper AND backtest. Circuit breaker now auto-resets once a fresh daily/weekly check clears (previously a documented gap — see `ENGINEERING_DECISIONS.md` #16). Sizing/loss-limit math still keys off `PLACEHOLDER_ACCOUNT_BALANCE`, intentionally, until Phase 1 gate #4 |
| Backtest Engine | ✅ Complete, actively used for research | Real fee/slippage/PnL, no-lookahead HTF cursor, multi-period out-of-sample splitting (`--periods`, HTF fetch now correctly sized to the LTF request's real time span), time-anchored fetching (`--end-date`), walk-forward validation (`--walk-forward`, explicit PASS/FAIL criteria — PASSED for BTCUSDT baseline), opt-in break-even (`--breakeven`, A/B **no reliable direction across 4 assets OR across 2 years on the same asset — even flips sign on BTCUSDT alone**), opt-in Breaker Block entries (`--breaker-block`, A/B **mostly negative across assets, zero effect in the 2025 BTCUSDT window**), opt-in partial take-profit (`--partial-tp`, A/B **negative on all 4 tested assets AND both tested years on BTCUSDT — the most robust finding in the project**) |
| Paper Trading | ✅ Complete | Real open/close/PnL against live OKX data, no real capital. Break-even stop management is wired here too (`settings.ENABLE_BREAKEVEN`, off by default, PERMANENTLY -- see research findings below) — no reliable direction exists across assets OR across time (it flips sign on BTCUSDT alone between 2025 and 2026), so there is no direction to ever default toward. Breaker Block and partial-TP remain backtest-only (no positive evidence justifying paper trading) |
| Portfolio/Journal | ✅ Complete | Real trade/signal persistence, daily/weekly/all-time reports |
| Dashboard | ✅ Complete | All 5 endpoints (`status`, `positions`, `logs`, `risk-status`, `bias`, `signals`) real, DB/live-computed |
| Live Trading | ❌ Not implemented, intentionally gated | `LiveBroker`, `exchange/okx_client.py`, `exchange/orangex_client.py` are all `NotImplementedError` stubs. Requires operator-approved API keys + staged approval before ANY code is written here |

## Test suite

206 backend tests, 0 known failures, re-run 2x+ for flakiness on every
change in this session. Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
(or the platform-appropriate venv path). No frontend test failures
(`npx tsc --noEmit` clean as of the last frontend-touching change).
`scripts/run_paper.py` itself has no direct pytest coverage (needs a live
network candle feed); its DB-backed logic (`TradeTracker.update_stop_loss`,
`_maybe_move_to_breakeven`) is instead verified via a real-temp-SQLite-DB
script exercising long/short/idempotency/disabled-gate paths end to end.

## Current research findings (the actual point of this project)

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
- No strategy parameters have ever been tuned against real data —
  `_LOOKBACK`, `_IMPULSE_MULT`, `_STOP_BUFFER`, `_RR`,
  `BREAKEVEN_TRIGGER_R`, `PARTIAL_TP_TRIGGER_R`, `PARTIAL_TP_PORTION`
  are all disclosed-as-untuned reasonable defaults. If they ever ARE
  tuned, it must be done using the `--periods` tool's held-out-period
  discipline or the entire point of building it is defeated.

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
