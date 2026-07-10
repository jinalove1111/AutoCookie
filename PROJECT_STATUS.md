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
market data on THREE independent assets. Break-even is wired into paper
trading, off by default -- and that default matters: break-even's
positive result reproduced on only 1 of 3 assets (negative on the other
2), while Breaker Block's and Partial TP's negative results reproduced
on all 3, more strongly each time).

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
| Backtest Engine | ✅ Complete, actively used for research | Real fee/slippage/PnL, no-lookahead HTF cursor, multi-period out-of-sample splitting (`--periods`, HTF fetch now correctly sized to the LTF request's real time span), opt-in break-even (`--breakeven`, A/B **positive on BTCUSDT, negative on ETHUSDT AND SOLUSDT — negative on 2 of 3 tested assets**), opt-in Breaker Block entries (`--breaker-block`, A/B **negative on all 3 tested assets**), opt-in partial take-profit (`--partial-tp`, A/B **negative on all 3 tested assets, 18 of 18 tested periods worse**) |
| Paper Trading | ✅ Complete | Real open/close/PnL against live OKX data, no real capital. Break-even stop management is wired here too (`settings.ENABLE_BREAKEVEN`, off by default) — shipped while its evidence still looked BTCUSDT-consistent; both follow-up assets (ETHUSDT, SOLUSDT) have since shown negative results, so the off-by-default posture is doing real, demonstrated work. Breaker Block and partial-TP remain backtest-only (no positive evidence on any tested asset) |
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
  has now been run on THREE independent assets at 6-month/6-period
  scale (BTCUSDT, ETHUSDT, SOLUSDT — all January-July 2026, genuinely
  varied conditions: win rates 40%-100%, trade counts 5-40 across
  periods and assets). The strategy's baseline (no experimental
  features) was **6 of 6 periods profitable on all three assets**.
- **Full rule-by-rule coverage audit exists**: `docs/strategy_coverage_audit.md`.
  Found three items implemented, unit-tested, but never wired into the
  live decision loop. **All three are now wired, A/B tested, and
  re-tested on three independent 6-month asset samples**:

  | Feature | BTCUSDT | ETHUSDT | SOLUSDT | Verdict |
  |---|---|---|---|---|
  | Break-even (`--breakeven`) | +9.2% | -1.9% | -4.8% | **Positive on 1 of 3, negative on 2 of 3** |
  | Breaker Block (`--breaker-block`) | -3.8% | -12.0% | -1.9% | **Negative on 3 of 3** |
  | Partial TP (`--partial-tp`) | -32.6% | -35.4% | -29.1% | **Negative on 3 of 3, 18/18 periods** |

  - **Break-even**: positive on BTCUSDT (+13.5% small sample, +9.2%
    6-month sample), but negative on both follow-up assets — ETHUSDT
    was genuinely mixed (1 of 6 periods improved, 2 worse, 3
    unaffected), SOLUSDT was uniformly flat-to-negative (0 improved, 4
    of 6 worse, 2 unaffected). **Conclusion: more often negative than
    positive on the assets tested so far** — the earlier "reproduced
    positive on two independent samples" framing rested on two BTCUSDT
    TIME WINDOWS, not two different assets, which overstated how
    general the finding was. This is exactly why it shipped to paper
    trading off-by-default rather than on, and why that default is not
    being reconsidered toward "on" without a 4th asset's result.
  - **Partial take-profit**: negative on all 3 assets, 18 of 18 tested
    periods worse, zero exceptions anywhere. -31.4%/-32.6% (BTC small/
    6-month), -35.4% (ETH), -29.1% (SOL). Mechanistic cause identified
    and holds on every asset: this strategy has a fixed 2:1 RR and
    tends toward a high win rate — locking in half the position at 1R
    trades away half of every full winner's upside, while rarely
    protecting losers (which mostly never reach +1R before reversing to
    the stop). **The single most robust finding in the project.**
  - **Breaker Block**: negative on all 3 assets, magnitude ranging
    -1.9% (SOL) to -12.0% (ETH) to -3.8% (BTC). Neutral on the original
    small sample (never got a real chance to fire); every subsequent
    asset has shown a real, negative effect once it did fire.

  All three kept opt-in and non-default in the Backtest Engine. Of the
  three, only break-even was ever wired into paper trading
  (`settings.ENABLE_BREAKEVEN`, off by default) — it shipped while its
  evidence still looked consistently positive; both follow-up
  validation rounds (ETHUSDT, then SOLUSDT) revised that picture
  further negative each time. The off-by-default choice is now doing
  real, demonstrated work: an operator who had defaulted it ON based on
  the BTCUSDT evidence alone would be running a net-negative feature on
  2 of the 3 assets tested today.
- **Data-layer bug found and fixed along the way**: `scripts/run_backtest.py`
  requested the same candle COUNT for both LTF and HTF fetches, which
  for a large `--periods` request meant asking for years more HTF
  history than needed (18000 candles at `4h` = ~8.2 years vs. the ~187
  days actually needed). Fixed with `timeframe_to_timedelta()` +
  `htf_candle_count_for_span()`, which size the HTF request off the
  real time span the LTF request covers.

## Honest caveats (read before citing these results anywhere)

- 3 assets checked (BTCUSDT, ETHUSDT, SOLUSDT), all large-cap L1s with
  broadly similar market beta — not a genuinely diverse asset set.
  Break-even's results already disagree across even this correlated
  set (positive on 1, negative on 2), which is itself a caution sign:
  2-of-3 could flip again with a 4th, more different asset.
- All three 6-month samples cover the SAME calendar window
  (January-July 2026) — this tests asset-generalization, not
  time-generalization; different YEARS remain completely untested.
- Per-period trade counts (5-40 across the three 6-month samples, 4-12
  on the original small sample) are still modest; win-rate confidence
  intervals remain wide, especially for the smaller-trade-count periods
  (e.g. ETHUSDT P3 and SOLUSDT P4 each had only 5-8 trades).
- No strategy parameters have ever been tuned against real data —
  `_LOOKBACK`, `_IMPULSE_MULT`, `_STOP_BUFFER`, `_RR`,
  `BREAKEVEN_TRIGGER_R`, `PARTIAL_TP_TRIGGER_R`, `PARTIAL_TP_PORTION`
  are all disclosed-as-untuned reasonable defaults. If they ever ARE
  tuned, it must be done using the `--periods` tool's held-out-period
  discipline or the entire point of building it is defeated.

**Conclusion: two findings are now solid, one is genuinely unsettled —
and that's real information, not a failure of the process.**
Partial-TP and Breaker Block's negative verdicts have now reproduced on
every one of three independent assets, which is strong evidence those
aren't flukes. Break-even's positive verdict reproduced across TIME on
one asset (BTCUSDT) but not across ASSETS — a distinction that matters
and that this project's docs now call out explicitly (see
`ENGINEERING_DECISIONS.md` entry #15). This system has not yet been
tested across genuinely different years or genuinely uncorrelated asset
classes. See `ROADMAP.md` for what's next.
