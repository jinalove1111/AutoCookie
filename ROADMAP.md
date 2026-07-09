# ROADMAP — JadeCap Automated Trading Bot

Forward-looking, prioritized backlog. This file answers "what's next and
why," not "what happened" (see `CHANGELOG.md`/`HANDOFF.md` for that) or
"why did we build it this way" (see `ENGINEERING_DECISIONS.md`).

Guiding principle (see `PROJECT_STATUS.md`'s "Project Philosophy" and
`docs/strategy_coverage_audit.md`): this is a research platform first.
Every item below is ranked by how much it moves the project closer to a
**statistically validated** profitable strategy — not by how much new
code it produces. Evidence over assumption; a rule stays in the system
because data proves it, not because it's popular in ICT/SMC communities.

## Done (this session, night CTO mode)

All three HIGH-priority `docs/strategy_coverage_audit.md` findings are
now wired and A/B tested, with three genuinely different outcomes:

- ~~Wire Breaker Block detection into `SignalEngine`~~ — DONE (opt-in
  `--breaker-block`). Result: **neutral**, measured ZERO effect across 6
  out-of-sample periods (BTCUSDT/ETHUSDT 15m). Diagnosed why: the
  detector fires regularly and CAN change signal-level output (2 real
  differences confirmed by direct scan), but both moments fell inside an
  already-open trade's window in this sample. Kept opt-in.
- ~~Wire break-even stop management into `BacktestEngine`~~ — DONE
  (opt-in `--breakeven`). Result: **positive**, +13.5% aggregate PnL
  across the same 6 periods, profitable periods 5/6 → 6/6. Kept opt-in
  (not enough samples yet to make it default).
- ~~Wire partial take-profit into `BacktestEngine`~~ — DONE (opt-in
  `--partial-tp`). Result: **negative**, reduced PnL in ALL 6 of 6
  periods (aggregate -31.4%). Diagnosed why: this strategy's fixed 2:1
  RR + high win rate in this sample means locking in half the position
  at 1R trades away upside on winners without meaningfully protecting
  losers. Kept opt-in; actively not recommended for the current strategy
  shape.

See `CHANGELOG.md`/`HANDOFF.md` for full evidence tables on all three.

## Immediate (highest ROI, unblocked, no operator input needed)

1. **Expand out-of-sample periods to different market regimes** — every
   period checked so far (all three experiments above) falls within the
   same ~31-day calendar span. Fetch materially more history
   (`--candles 3000 --periods 6` or larger) or re-run this tooling after
   more calendar time has passed, specifically looking for periods with
   different volatility/trend characteristics. This is now the single
   highest-value next step: it's the direct way to check whether
   Breaker Block's null result, Partial TP's negative result, AND
   break-even's positive result all hold up outside this one sample, or
   are themselves artifacts of this particular ~31-day window.
2. **Wire break-even into paper trading** (`scripts/run_paper.py`) — the
   only one of the three experiments with a positive backtest result.
   Requires a new `TradeTracker.update_stop_loss()`-style method
   (doesn't exist yet) since paper positions are DB rows, not an
   in-memory candle scan. Should ship as opt-in (`ENABLE_BREAKEVEN`
   setting, mirroring `ENABLE_TELEGRAM_ALERTS`'s pattern).
3. **Add more, less-correlated symbols** — only BTCUSDT/ETHUSDT checked
   so far (highly correlated with each other). Lower-correlation assets
   would make all three findings above meaningfully stronger evidence.

## Near-term (needs the above first, or is inherently larger scope)

4. **Parameter sweep of `_LOOKBACK`/`_IMPULSE_MULT`/`_STOP_BUFFER`/`_RR`/
   `BREAKEVEN_TRIGGER_R`/`PARTIAL_TP_TRIGGER_R`/`PARTIAL_TP_PORTION`** —
   all seven are disclosed-as-untuned defaults. **Hard rule,
   non-negotiable**: any sweep MUST reserve a subset of `--periods`
   output as a genuinely held-out test set never inspected until the
   final decision. Tuning against the same periods used to pick the
   "best" value and then reporting that value's performance on those
   same periods is not validation, it's overfitting with extra steps —
   this is exactly the failure mode the out-of-sample tooling exists to
   prevent (see `ENGINEERING_DECISIONS.md` entry on this). Given Partial
   TP's negative result was explained by this strategy's SPECIFIC win-
   rate/RR profile, a smaller `PARTIAL_TP_TRIGGER_R` or a different
   `_RR` might change that conclusion -- worth investigating with proper
   held-out discipline, not by assumption.
5. **Resolve the spec/implementation ambiguity in confluence strength**
   (audit item #9) — `docs/strategy_spec.md` section 6 reads as requiring
   bias + sweep + CHOCH + FVG/OB all in confluence; the actual code
   requires only bias + (sweep OR choch) + (FVG OR OB), a strictly
   looser bar. Decide, with backtest evidence, whether requiring stronger
   confluence (more factors aligned) produces meaningfully better
   trades, or whether the looser bar is correct and the spec wording
   should be relaxed to match reality instead.
6. **Equal-highs/equal-lows liquidity detection** (audit item #3) —
   `detect_liquidity_sweep()` only recognizes single swing-point sweeps;
   real SMC also treats clusters of near-equal highs/lows as a stronger
   resting-liquidity signal. Neither the spec nor the code currently
   defines this — would need a spec addition first, then implementation,
   then the same A/B discipline as every other change here.

## Medium-term (architecture / scalability)

7. **Multi-strategy plug-in architecture** — today `SignalEngine` is a
   single hardcoded pipeline. If/when a second, genuinely different
   strategy is worth trying (not just parameter variants of the current
   one), the Strategy Engine's interface (`generate_signal(symbol,
   ltf_candles, htf_candles) -> TradeSignal | None`) is already a clean
   enough contract to support multiple implementations behind it — no
   redesign needed yet, just keep new strategies behind the same
   interface rather than special-casing them into the existing modules.
8. **Monte Carlo readiness** — the backtest engine's trade list
   (`BacktestResult.trades`) already has everything needed (`pnl`,
   `direction`, `size`, timestamps) to bootstrap/reshuffle trade
   sequences for Monte Carlo drawdown analysis. Not yet built; a
   natural next step once there are enough real trades across enough
   periods to make resampling meaningful (current per-period counts of
   4-12 trades are too small to resample usefully yet).

## Explicitly NOT started, and why

- **Live Trading** (`LiveBroker`, `exchange/okx_client.py`,
  `exchange/orangex_client.py`) — all `NotImplementedError` stubs,
  deliberately. Requires, IN ORDER: (a) out-of-sample validation across
  genuinely different market regimes (not yet done, see item #1 above),
  (b) operator-issued OKX API keys with withdrawal disabled, (c) a small
  live-capital limit agreed with the operator, (d) step-by-step operator
  approval at each stage per `docs/live_trading_checklist.md`. None of
  this proceeds without the operator present — API credential
  provisioning and live-trading approval are both explicit stop
  conditions, not something a CTO-mode session decides alone.
- **Paper trading break-even** — see item #2, deliberately sequenced
  after the backtest-only validation that already shipped, not done in
  the same round (one validated change at a time).
- **Paper trading Breaker Block or Partial TP** — NOT planned currently.
  Breaker Block's backtest result was neutral; Partial TP's was
  negative. Neither has positive evidence to justify wiring into paper
  trading. Revisit only if item #1 (different market regimes) changes
  either conclusion.
