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
market data on TWO independent assets. Break-even is wired into paper
trading, off by default -- and that default matters: break-even's
positive result did NOT reproduce on ETHUSDT, while Breaker Block's and
Partial TP's negative results reproduced even more strongly).

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
| Backtest Engine | ✅ Complete, actively used for research | Real fee/slippage/PnL, no-lookahead HTF cursor, multi-period out-of-sample splitting (`--periods`, HTF fetch now correctly sized to the LTF request's real time span), opt-in break-even (`--breakeven`, A/B **positive on BTCUSDT (2 samples), slightly negative on ETHUSDT — asset-dependent, not universal**), opt-in Breaker Block entries (`--breaker-block`, A/B **negative, reproduced on both assets, more strongly on ETHUSDT**), opt-in partial take-profit (`--partial-tp`, A/B **negative, reproduced on both assets — 12 of 12 tested periods worse**) |
| Paper Trading | ✅ Complete | Real open/close/PnL against live OKX data, no real capital. Break-even stop management is wired here too (`settings.ENABLE_BREAKEVEN`, off by default) — shipped while its evidence still looked BTCUSDT-consistent; ETHUSDT has since shown a slightly negative result, so the off-by-default posture is doing real work, not just formality. Breaker Block and partial-TP remain backtest-only (no positive evidence on either asset) |
| Portfolio/Journal | ✅ Complete | Real trade/signal persistence, daily/weekly/all-time reports |
| Dashboard | ✅ Complete | All 5 endpoints (`status`, `positions`, `logs`, `risk-status`, `bias`, `signals`) real, DB/live-computed |
| Live Trading | ❌ Not implemented, intentionally gated | `LiveBroker`, `exchange/okx_client.py`, `exchange/orangex_client.py` are all `NotImplementedError` stubs. Requires operator-approved API keys + staged approval before ANY code is written here |

## Test suite

190 backend tests, 0 known failures, re-run 2x+ for flakiness on every
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
  has now been run at two very different scales, on two different
  assets: an initial ~31-day/3-period sample (BTCUSDT + ETHUSDT), and a
  follow-up 6-month/6-period sample on EACH of BTCUSDT and ETHUSDT
  separately (January-July 2026, genuinely varied conditions -- win
  rates 40%-94.44%, trade counts 5-28 across periods and assets). The
  strategy's baseline (no experimental features) was **6 of 6 periods
  profitable on both assets** at the 6-month scale.
- **Full rule-by-rule coverage audit exists**: `docs/strategy_coverage_audit.md`.
  Found three items implemented, unit-tested, but never wired into the
  live decision loop. **All three are now wired, A/B tested, re-tested
  on a 6-month BTCUSDT sample, AND re-tested again on an independent
  6-month ETHUSDT sample** — two findings reproduced and even
  strengthened; one did NOT reproduce, which is itself an important
  result:
  - **Break-even** (`--breakeven`): **positive on BTCUSDT, did NOT
    reproduce on ETHUSDT.** +13.5% (BTC small sample), +9.2% (BTC
    6-month sample), **-1.9% (ETH 6-month sample)**. The ETHUSDT result
    is genuinely mixed, not uniformly bad: 1 of 6 periods improved
    (+$84.54), 2 of 6 got worse (one flipped from a small win to a small
    loss, win rate 60%->40%), 3 of 6 were unaffected (trigger never
    reached). **Conclusion: break-even's benefit looks asset-dependent,
    not universal** — the earlier "reproduced positive on two
    independent samples" framing rested on two BTCUSDT time windows,
    which is weaker evidence than "two different assets" would be. This
    is exactly why it shipped to paper trading off-by-default rather
    than on.
  - **Partial take-profit** (`--partial-tp`): **negative, REPRODUCED
    on BOTH assets, more strongly.** -31.4% (BTC small), -32.6% (BTC
    6-month), **-35.4% (ETH 6-month)** — 12 of 12 tested periods worse
    across both assets, no exceptions anywhere. Mechanistic cause
    identified and holds on both assets: this strategy has a fixed 2:1
    RR and tends toward a high win rate — locking in half the position
    at 1R trades away half of every full winner's upside, while rarely
    protecting losers (which mostly never reach +1R before reversing to
    the stop).
  - **Breaker Block** (`--breaker-block`): **negative, REPRODUCED on
    BOTH assets, more strongly on ETHUSDT.** Neutral on the small
    sample, -3.8% (BTC 6-month, 1 of 6 periods affected), **-12.0% (ETH
    6-month, 4 of 6 periods affected, all negative, 0 positive)**. Same
    direction on both assets now, at meaningfully larger magnitude on
    the second — the out-of-sample methodology doing exactly what it's
    for.

  All three kept opt-in and non-default in the Backtest Engine. Of the
  three, only break-even was wired into paper trading
  (`settings.ENABLE_BREAKEVEN`, off by default) — it shipped while its
  evidence still looked consistently positive; the ETHUSDT result above
  came from the very next validation round and revised that picture. The
  off-by-default choice was not just caution for its own sake — it is
  now doing real, demonstrated work: an operator who had defaulted it ON
  based on the BTCUSDT evidence alone would be running a slightly
  negative feature on ETHUSDT today.
- **Data-layer bug found and fixed along the way**: `scripts/run_backtest.py`
  requested the same candle COUNT for both LTF and HTF fetches, which
  for a large `--periods` request meant asking for years more HTF
  history than needed (18000 candles at `4h` = ~8.2 years vs. the ~187
  days actually needed). Fixed with `timeframe_to_timedelta()` +
  `htf_candle_count_for_span()`, which size the HTF request off the
  real time span the LTF request covers.

## Honest caveats (read before citing these results anywhere)

- Only 2 assets checked at all (BTCUSDT, ETHUSDT), which are highly
  correlated with each other — and they still disagree on break-even.
  That disagreement between two CORRELATED assets is itself a caution
  sign: a genuinely uncorrelated third asset could easily diverge again.
- Both 6-month samples cover the same calendar window (January-July
  2026) on both assets — this tests asset-generalization, not
  time-generalization; different YEARS remain untested.
- Per-period trade counts (5-28 across both 6-month samples, 4-12 on the
  original small sample) are still modest; win-rate confidence intervals
  remain wide, especially for the smaller-trade-count periods (ETHUSDT
  P3 had only 5 trades).
- No strategy parameters have ever been tuned against real data —
  `_LOOKBACK`, `_IMPULSE_MULT`, `_STOP_BUFFER`, `_RR`,
  `BREAKEVEN_TRIGGER_R`, `PARTIAL_TP_TRIGGER_R`, `PARTIAL_TP_PORTION`
  are all disclosed-as-untuned reasonable defaults. If they ever ARE
  tuned, it must be done using the `--periods` tool's held-out-period
  discipline or the entire point of building it is defeated.

**Conclusion: mixed, and that's a real finding, not a failure.**
Partial-TP and Breaker Block's negative verdicts both reproduced and
strengthened across two independent assets — real evidence those aren't
flukes. Break-even's positive verdict did NOT reproduce across assets
(only across time windows on the same asset) — real evidence that
"reproduced" claims must specify what varied between samples, since
asset-generalization and time-generalization are different claims with
different strength. This system has not yet been tested across
genuinely different years or genuinely uncorrelated assets. See
`ROADMAP.md` for what's next.
