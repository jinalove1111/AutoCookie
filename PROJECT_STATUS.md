# PROJECT_STATUS — JadeCap Automated Trading Bot

This file is the always-current, English snapshot: what the system does
*right now*, as of the latest commit on `master`. It intentionally has
no history — for the round-by-round session log (in Korean, matching
this project's established working language for that file), see
`HANDOFF.md`. For chronological release notes, see `CHANGELOG.md`. For
the "why" behind specific non-obvious engineering choices, see
`ENGINEERING_DECISIONS.md`. For forward-looking prioritization, see
`ROADMAP.md`.

Last updated: 2026-07-10 (night CTO session: all 3 audit HIGH items
wired, A/B tested, and re-validated across 6 months of real, diverse
market data -- two findings reproduced, one revised).

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
| Backtest Engine | ✅ Complete, actively used for research | Real fee/slippage/PnL, no-lookahead HTF cursor, multi-period out-of-sample splitting (`--periods`, HTF fetch now correctly sized to the LTF request's real time span), opt-in break-even (`--breakeven`, A/B **positive, reproduced on 2 independent samples**), opt-in Breaker Block entries (`--breaker-block`, A/B **slightly negative on the larger sample** -- revised from an earlier "neutral" finding), opt-in partial take-profit (`--partial-tp`, A/B **negative, reproduced on 2 independent samples**) |
| Paper Trading | ✅ Complete | Real open/close/PnL against live OKX data, no real capital. None of the three backtest-validated experimental features (break-even/breaker-block/partial-TP) are wired here yet — backtest-only so far |
| Portfolio/Journal | ✅ Complete | Real trade/signal persistence, daily/weekly/all-time reports |
| Dashboard | ✅ Complete | All 5 endpoints (`status`, `positions`, `logs`, `risk-status`, `bias`, `signals`) real, DB/live-computed |
| Live Trading | ❌ Not implemented, intentionally gated | `LiveBroker`, `exchange/okx_client.py`, `exchange/orangex_client.py` are all `NotImplementedError` stubs. Requires operator-approved API keys + staged approval before ANY code is written here |

## Test suite

187 backend tests, 0 known failures, re-run 2x+ for flakiness on every
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
  history into independent, non-overlapping chronological chunks) and
  has now been run at two very different scales: an initial ~31-day/3-
  period sample (BTCUSDT + ETHUSDT), and a follow-up 6-month/6-period
  sample (BTCUSDT, January-July 2026, genuinely varied conditions --
  win rates 62.5%-90.48%, trade counts 8-28 across periods). The
  strategy's baseline (no experimental features) was **6 of 6 periods
  profitable** on the larger sample too.
- **Full rule-by-rule coverage audit exists**: `docs/strategy_coverage_audit.md`.
  Found three items implemented, unit-tested, but never wired into the
  live decision loop. **All three are now wired, A/B tested, AND
  re-tested on the larger 6-month sample** — two findings reproduced
  almost exactly, one was meaningfully revised:
  - **Break-even** (`--breakeven`): **positive, REPRODUCED**. +13.5%
    on the small sample, +9.2% on the 6-month sample (same direction,
    independent data) — the most robust of the three findings.
  - **Partial take-profit** (`--partial-tp`): **negative, REPRODUCED**.
    -31.4% on the small sample, -32.6% on the 6-month sample — reduced
    PnL in every single period tested across BOTH samples (12 of 12).
    Mechanistic cause identified: this strategy has a fixed 2:1 RR and
    tends toward a high win rate — locking in half the position at 1R
    trades away half of every full winner's upside, while rarely
    protecting losers (which mostly never reach +1R before reversing to
    the stop).
  - **Breaker Block** (`--breaker-block`): **REVISED from neutral to
    slightly negative**. The small sample showed ZERO effect (the
    detector fires and CAN change signal-level output, but the 2
    confirmed differences both happened to fall inside an already-open
    trade's window). On the 6-month sample it got a real chance to
    matter once (1 of 6 periods: win rate 90.48% -> 85.71%, PnL $567.92
    -> $496.11) -- and the effect was negative. Still too little data to
    call it "proven harmful," but "neutral" no longer accurately
    describes it. This is the out-of-sample methodology doing exactly
    what it's for: a conclusion that looked stable on a small sample
    changed with more data.

  All three kept opt-in; none made default; none wired into paper
  trading yet (break-even is the strongest candidate given it reproduced
  positively on two independent samples).
- **Data-layer bug found and fixed along the way**: `scripts/run_backtest.py`
  requested the same candle COUNT for both LTF and HTF fetches, which
  for a large `--periods` request meant asking for years more HTF
  history than needed (18000 candles at `4h` = ~8.2 years vs. the ~187
  days actually needed). Fixed with `timeframe_to_timedelta()` +
  `htf_candle_count_for_span()`, which size the HTF request off the
  real time span the LTF request covers.

## Honest caveats (read before citing these results anywhere)

- The 6-month sample above is BTCUSDT only so far; ETHUSDT hasn't been
  re-tested at this scale yet (only on the original ~31-day sample).
- Only 2 assets checked at all (BTCUSDT, ETHUSDT), which are highly
  correlated with each other.
- Per-period trade counts (8-28 on the larger sample, 4-12 on the
  smaller one) are still modest; win-rate confidence intervals remain
  wide, especially for the smaller-trade-count periods.
- No strategy parameters have ever been tuned against real data —
  `_LOOKBACK`, `_IMPULSE_MULT`, `_STOP_BUFFER`, `_RR`,
  `BREAKEVEN_TRIGGER_R`, `PARTIAL_TP_TRIGGER_R`, `PARTIAL_TP_PORTION`
  are all disclosed-as-untuned reasonable defaults. If they ever ARE
  tuned, it must be done using the `--periods` tool's held-out-period
  discipline or the entire point of building it is defeated.

**Conclusion: more encouraging than before, still not proven.** Two
independent samples now agree on break-even (positive) and partial-TP
(negative), which is real evidence those aren't flukes. Breaker Block's
revision from neutral to slightly-negative is a reminder that even a
6x-larger sample can still change a conclusion — this system has not
yet been tested across genuinely different assets or years of history.
See `ROADMAP.md` for what's next.
