# PROJECT_STATUS — JadeCap Automated Trading Bot

This file is the always-current, English snapshot: what the system does
*right now*, as of the latest commit on `master`. It intentionally has
no history — for the round-by-round session log (in Korean, matching
this project's established working language for that file), see
`HANDOFF.md`. For chronological release notes, see `CHANGELOG.md`. For
the "why" behind specific non-obvious engineering choices, see
`ENGINEERING_DECISIONS.md`. For forward-looking prioritization, see
`ROADMAP.md`.

Last updated: 2026-07-10 (night CTO session: Breaker Block + Partial
Take-Profit both wired and A/B tested; all 3 audit HIGH items now
complete).

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
| Data (candle fetch) | ✅ Complete | Real OKX public API, deep pagination via `/market/history-candles` (fixed a long-standing 300-candle cap bug), no API key needed |
| Strategy Engine | ✅ Complete, actively validated | Bias/sweep/CHOCH/FVG/OB/zone-mitigation/entry-model all real, all tested. Breaker Block detection now wired in too (opt-in, `use_breaker_block`, A/B tested — see findings below) |
| Risk Engine | ✅ Complete | RR floor, daily/weekly loss limits, trades/day cap, position sizing, DB-persisted circuit breaker — all enforced in both paper AND backtest |
| Backtest Engine | ✅ Complete, actively used for research | Real fee/slippage/PnL, no-lookahead HTF cursor, multi-period out-of-sample splitting (`--periods`), opt-in break-even (`--breakeven`, A/B **positive**), opt-in Breaker Block entries (`--breaker-block`, A/B **neutral**), opt-in partial take-profit (`--partial-tp`, A/B **negative** for this strategy) |
| Paper Trading | ✅ Complete | Real open/close/PnL against live OKX data, no real capital. None of the three backtest-validated experimental features (break-even/breaker-block/partial-TP) are wired here yet — backtest-only so far |
| Portfolio/Journal | ✅ Complete | Real trade/signal persistence, daily/weekly/all-time reports |
| Dashboard | ✅ Complete | All 5 endpoints (`status`, `positions`, `logs`, `risk-status`, `bias`, `signals`) real, DB/live-computed |
| Live Trading | ❌ Not implemented, intentionally gated | `LiveBroker`, `exchange/okx_client.py`, `exchange/orangex_client.py` are all `NotImplementedError` stubs. Requires operator-approved API keys + staged approval before ANY code is written here |

## Test suite

185 backend tests, 0 known failures, re-run 2x+ for flakiness on every
change in this session. Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
(or the platform-appropriate venv path). No frontend test failures
(`npx tsc --noEmit` clean as of the last frontend-touching change).

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
  history into independent, non-overlapping chronological chunks). On 6
  independent periods (BTCUSDT + ETHUSDT, 15m, ~31-day span so far): 5/6
  profitable pre-break-even, 6/6 profitable post-break-even.
- **Break-even stop management is implemented and A/B validated**
  (opt-in, `--breakeven`): +13.5% aggregate PnL across the same 6
  periods, mixed-but-net-positive effect (narrows outcome range more
  than it grows the total — the textbook effect).
- **Full rule-by-rule coverage audit exists**: `docs/strategy_coverage_audit.md`.
  Found three items implemented, unit-tested, but never wired into the
  live decision loop. **All three are now wired and A/B tested**, with
  three DIFFERENT outcomes — direct evidence the "verify, don't assume"
  research discipline actually works:
  - **Break-even** (`--breakeven`): **positive**. +13.5% aggregate PnL
    across 6 out-of-sample periods, profitable periods 5/6 → 6/6.
  - **Breaker Block** (`--breaker-block`): **neutral, explained**.
    Measured ZERO effect across the same 6 periods. Diagnosed why rather
    than accepting the null result: the detector fires regularly and CAN
    change signal-level output (2 real differences confirmed by direct
    scan), but both differing moments fell inside an already-open
    trade's window in this sample, so neither reached the actual
    backtest trade sequence.
  - **Partial take-profit** (`--partial-tp`): **negative, explained**.
    Reduced PnL in EVERY SINGLE one of the 6 periods tested (aggregate
    $819.09 → $562.27, -31.4%). Mechanistic cause identified: this
    strategy has a fixed 2:1 RR and, in this sample, a high win rate —
    locking in half the position at 1R trades away half of every full
    winner's upside, while rarely protecting losers (which mostly never
    reach +1R before reversing to the stop). Strategy-shape-dependent,
    not a universal verdict on the technique.

  All three kept opt-in; none made default; none wired into paper
  trading yet.

## Honest caveats (read before citing these results anywhere)

- All out-of-sample periods so far fall within the same ~31-day calendar
  span — genuinely disjoint in trade sequence, but NOT a different
  market regime (trending vs. ranging, high vs. low volatility).
- Only 2 assets checked (BTCUSDT, ETHUSDT), which are highly correlated
  with each other.
- Per-period trade counts (4-12) are small; win-rate confidence
  intervals are wide.
- No strategy parameters have ever been tuned against real data —
  `_LOOKBACK`, `_IMPULSE_MULT`, `_STOP_BUFFER`, `_RR`,
  `BREAKEVEN_TRIGGER_R`, `PARTIAL_TP_TRIGGER_R`, `PARTIAL_TP_PORTION`
  are all disclosed-as-untuned reasonable defaults. If they ever ARE
  tuned, it must be done using the `--periods` tool's held-out-period
  discipline or the entire point of building it is defeated.

**Conclusion: encouraging, not proven.** See `ROADMAP.md` for what
"proven" would actually require.
