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
now wired, A/B tested on an initial ~31-day/3-period sample, AND
re-tested on a much larger 6-month/6-period sample (BTCUSDT, genuinely
varied conditions):

- ~~Wire break-even stop management into `BacktestEngine`~~ — DONE
  (opt-in `--breakeven`). Result: **positive, REPRODUCED**: +13.5% on
  the small sample, +9.2% on the 6-month sample. The most robust of the
  three findings -- same direction on two independent datasets.
- ~~Wire partial take-profit into `BacktestEngine`~~ — DONE (opt-in
  `--partial-tp`). Result: **negative, REPRODUCED**: -31.4% on the small
  sample, -32.6% on the 6-month sample -- reduced PnL in every single
  period tested across BOTH samples (12 of 12, no exceptions).
- ~~Wire Breaker Block detection into `SignalEngine`~~ — DONE (opt-in
  `--breaker-block`). Result: **REVISED, neutral -> slightly negative**.
  Zero effect on the small sample (the detector fires and can change
  output, but the 2 confirmed differences happened to fall inside an
  already-open trade's window). On the 6-month sample it fired for real
  once (1 of 6 periods) and the effect was negative (win rate 90.48% ->
  85.71%). Still thin evidence (1 affected period), but "neutral" no
  longer accurately describes it.
- ~~Fixed a real HTF over-fetch bug~~ found while running the 6-month
  test: `run_backtest.py` requested the same candle COUNT for LTF and
  HTF, so a large `--periods` request asked for years more HTF history
  than needed. Added `timeframe_to_timedelta()`/`htf_candle_count_for_span()`
  to size the HTF request off the real time span instead.

- ~~Wire break-even into paper trading~~ — DONE. Added
  `TradeTracker.update_stop_loss()` (raises `ValueError` on an unknown or
  already-closed trade id, same contract style as `close_trade`), a new
  `_maybe_move_to_breakeven()` step in `scripts/run_paper.py`'s
  `run_once()` (runs right after the exit-check step, before the
  concurrency guard -- mirrors `BacktestEngine`'s same-pass conservative
  ordering: a position reaching the 1R trigger this pass is still
  exit-checked against its OLD stop this same pass), and
  `settings.ENABLE_BREAKEVEN`/`BREAKEVEN_TRIGGER_R` (the trigger value is
  imported from `app.config.settings`, shared with `BacktestEngine`'s own
  `use_breakeven` A/B-test path, so paper trading and backtesting always
  agree on the same trigger distance). Off by default. Verified via 3 new
  `test_portfolio.py` tests (round-trip move, unknown-id error,
  closed-trade error) plus a real-temp-SQLite-DB script exercising long,
  short, idempotency (a stop already at breakeven is never re-processed
  or re-written), and the disabled-gate path — see CHANGELOG.md.

See `CHANGELOG.md`/`HANDOFF.md` for full evidence tables on all of this.

## Immediate (highest ROI, unblocked, no operator input needed)

1. **Re-run the 6-month deep test on ETHUSDT** — the 6-month/6-period
   validation above was BTCUSDT only (time-boxed this round). Confirming
   the same three verdicts (break-even positive, partial-TP negative,
   breaker-block slightly negative) hold on ETHUSDT too would meaningfully
   strengthen all three findings; a DIFFERENT verdict on ETHUSDT would be
   equally informative (asset-specific rather than universal effects).
2. **Add more, less-correlated symbols** — only BTCUSDT/ETHUSDT checked
   so far (highly correlated with each other). Lower-correlation assets
   would make all three findings above meaningfully stronger evidence.
3. **Extend even further back in time / to other years** — the 6-month
   sample (Jan-Jul 2026) is still one continuous span of recent history.
   Genuinely different YEARS (different macro conditions) would be a
   stronger test than a longer contiguous window in the same period.

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
   periods to make resampling meaningful (the 6-month sample's 8-28
   trades per period is still on the small side for resampling).

## Explicitly NOT started, and why

- **Live Trading** (`LiveBroker`, `exchange/okx_client.py`,
  `exchange/orangex_client.py`) — all `NotImplementedError` stubs,
  deliberately. Requires, IN ORDER: (a) out-of-sample validation across
  genuinely different market regimes (partially done -- see the 6-month
  BTCUSDT result above, but ETHUSDT and other years/assets remain, see
  items #1-3 above), (b) operator-issued OKX API keys with withdrawal
  disabled, (c) a small live-capital limit agreed with the operator, (d)
  step-by-step operator approval at each stage per
  `docs/live_trading_checklist.md`. None of this proceeds without the
  operator present — API credential provisioning and live-trading
  approval are both explicit stop conditions, not something a CTO-mode
  session decides alone.
- **Paper trading Breaker Block or Partial TP** — NOT planned currently.
  Breaker Block's backtest result is now slightly negative (was
  neutral); Partial TP's is negative on two independent samples. Neither
  has positive evidence to justify wiring into paper trading.
