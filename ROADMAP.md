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

- ~~Wire Breaker Block detection into `SignalEngine`~~ — DONE, A/B tested
  (opt-in `--breaker-block`). Result: measured ZERO effect across 6
  out-of-sample periods (BTCUSDT/ETHUSDT 15m). Diagnosed why: the
  detector fires regularly and CAN change signal-level output (2 real
  differences confirmed by direct scan), but both moments fell inside an
  already-open trade's window in this sample, so neither reached the
  actual backtest trade sequence. Kept opt-in per the "no measurable
  improvement -> stay optional" rule. See `CHANGELOG.md`/`HANDOFF.md` for
  full evidence. Re-test candidate once out-of-sample periods expand
  (item below) — a sample with more idle time between trades might
  behave differently.

## Immediate (highest ROI, unblocked, no operator input needed)

1. **Wire partial take-profit** (`OrderManager.handle_partial_tp()`,
   audit item #20) — the last of the three HIGH-priority audit findings.
   Real logic, unit-tested, unused anywhere in the live decision loop.
   Structurally more complex to A/B-test than break-even/breaker-block
   were (splits PnL into two legs, needs a decision on what portion% to
   close and what happens to the remaining size's target) — now that
   break-even and breaker block are both shipped and validated, this is
   the natural next single-variable change.
2. **Wire break-even into paper trading** (`scripts/run_paper.py`) — the
   backtest A/B result was positive (+13.5% aggregate, 5/6 → 6/6
   profitable periods). Requires a new `TradeTracker.update_stop_loss()`-
   style method (doesn't exist yet) since paper positions are DB rows,
   not an in-memory candle scan. Should ship as opt-in
   (`ENABLE_BREAKEVEN` setting, mirroring `ENABLE_TELEGRAM_ALERTS`'s
   pattern) so it can be toggled without a code change once enabled in
   production.
3. **Expand out-of-sample periods to different market regimes** — every
   period checked so far (break-even AND breaker-block validation both)
   falls within the same ~31-day calendar span. Fetch materially more
   history (`--candles 3000 --periods 6` or larger) or re-run this
   tooling after more calendar time has passed, specifically looking for
   periods with different volatility/trend characteristics. Also the
   most direct way to re-test whether Breaker Block's null result holds
   up outside this specific sample.
4. **Add more, less-correlated symbols** — only BTCUSDT/ETHUSDT checked
   so far (highly correlated with each other). Lower-correlation assets
   would make the "6/6 profitable periods" evidence meaningfully
   stronger.

## Near-term (needs the above first, or is inherently larger scope)

5. **Parameter sweep of `_LOOKBACK`/`_IMPULSE_MULT`/`_STOP_BUFFER`/`_RR`/
   `BREAKEVEN_TRIGGER_R`** — all five are disclosed-as-untuned defaults.
   **Hard rule, non-negotiable**: any sweep MUST reserve a subset of
   `--periods` output as a genuinely held-out test set never inspected
   until the final decision. Tuning against the same periods used to
   pick the "best" value and then reporting that value's performance on
   those same periods is not validation, it's overfitting with extra
   steps — this is exactly the failure mode the out-of-sample tooling
   exists to prevent (see `ENGINEERING_DECISIONS.md` entry on this).
6. **Resolve the spec/implementation ambiguity in confluence strength**
   (audit item #9) — `docs/strategy_spec.md` section 6 reads as requiring
   bias + sweep + CHOCH + FVG/OB all in confluence; the actual code
   requires only bias + (sweep OR choch) + (FVG OR OB), a strictly
   looser bar. Decide, with backtest evidence, whether requiring stronger
   confluence (more factors aligned) produces meaningfully better
   trades, or whether the looser bar is correct and the spec wording
   should be relaxed to match reality instead.
7. **Equal-highs/equal-lows liquidity detection** (audit item #3) —
   `detect_liquidity_sweep()` only recognizes single swing-point sweeps;
   real SMC also treats clusters of near-equal highs/lows as a stronger
   resting-liquidity signal. Neither the spec nor the code currently
   defines this — would need a spec addition first, then implementation,
   then the same A/B discipline as every other change here.

## Medium-term (architecture / scalability)

8. **Multi-strategy plug-in architecture** — today `SignalEngine` is a
   single hardcoded pipeline. If/when a second, genuinely different
   strategy is worth trying (not just parameter variants of the current
   one), the Strategy Engine's interface (`generate_signal(symbol,
   ltf_candles, htf_candles) -> TradeSignal | None`) is already a clean
   enough contract to support multiple implementations behind it — no
   redesign needed yet, just keep new strategies behind the same
   interface rather than special-casing them into the existing modules.
9. **Monte Carlo readiness** — the backtest engine's trade list
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
  genuinely different market regimes (not yet done, see item #3 above),
  (b) operator-issued OKX API keys with withdrawal disabled, (c) a small
  live-capital limit agreed with the operator, (d) step-by-step operator
  approval at each stage per `docs/live_trading_checklist.md`. None of
  this proceeds without the operator present — API credential
  provisioning and live-trading approval are both explicit stop
  conditions, not something a CTO-mode session decides alone.
- **Paper trading break-even** — see item #2, deliberately sequenced
  after the backtest-only validation that already shipped, not done in
  the same round (one validated change at a time).
- **Paper trading Breaker Block** — NOT planned currently. Its backtest
  A/B result was neutral (zero measured effect, not proven harmful or
  helpful), so there is no positive evidence yet to justify wiring it
  into paper trading. Revisit only if item #3 (different market regimes)
  produces evidence it actually matters somewhere.
