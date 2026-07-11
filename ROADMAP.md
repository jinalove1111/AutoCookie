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

**Scope lock (operator directive, 2026-07-11)**: the objective for Phase
1 is narrowly "build, validate, and prove ONE profitable JadeCap
automated trading system" — nothing else. No multi-strategy platform, no
quant research platform, no strategy marketplace, no architecture not
required for JadeCap specifically. Every new item must answer "does this
directly increase the probability that JadeCap becomes a profitable
automated trading system?" — if no, it goes in the "Phase 2 (deferred,
out of scope for now)" section below, not implemented. The objective
does not change until JadeCap has completed, in order: Backtest ->
Walk-Forward -> Paper Trading -> Small Live Validation.

## Phase 1 gate status

| Gate | Status | Evidence |
|---|---|---|
| 1. Backtest | ✅ Complete, extensively validated | 4 assets (BTC/ETH/SOL/XRP) x 2026, BTCUSDT also x 2025 — see "Done" below and `CHANGELOG.md`. Every core rule in `docs/strategy_coverage_audit.md` is now implemented, tested, and (where ever ambiguous) resolved with A/B evidence — zero remaining HIGH-priority items, see that doc's summary. **Controlled parameter sweep complete** (`docs/parameter_sweep_report.md`): 4 tuned defaults adopted (`_RR` 2.0->2.5, `_STOP_BUFFER` 0.001->0.0015, `_LOOKBACK` 10->15, `_IMPULSE_MULT` 1.5->1.8), all cleared in-sample + out-of-sample + cross-asset + cross-year validation, +66.7% PnL on the standard BTC 2026 methodology with walk-forward still passing cleanly |
| 2. Walk-forward validation | ✅ CLOSED — PASSED on all 4 assets under the OLD defaults; re-confirmed PASSED on BTCUSDT under the NEW (tuned) defaults | `run_backtest.py --walk-forward` — explicit PASS/FAIL criteria (profitable-period ratio, max losing streak, degradation trend). BTC/ETH/SOL/XRP 2026 baselines (old defaults): **all PASSED** (24/24 periods profitable, 0 losing streaks anywhere). Since the 2026-07-11 parameter sweep changed the defaults, BTCUSDT was re-confirmed PASSED under the new constants (6/6 profitable, 0 losing streak, no degradation, +66.7% PnL vs. the old-default run); ETH/SOL/XRP have NOT yet been re-run at the standard 3000-candle/6-period scale under the new defaults (only at the sweep's own 1500-candle/8-period cross-asset validation scale, where all held up) — see item #1 below |
| 3. Paper trading | ✅ Pipeline complete and running | `scripts/run_paper.py` — real open/close/PnL against live OKX data, no real capital. Break-even wired in (off by default, permanently — see research findings). Risk controls (RR floor, daily/weekly loss limits, circuit breaker, position sizing) all real and enforced. Circuit breaker now auto-resets once a fresh daily/weekly check clears (previously a documented gap — a trip halted trading permanently with no operator-facing reset path) |
| 4. Small live validation | ❌ Not started, intentionally gated | Requires operator-issued API keys + staged approval — explicit stop condition, not a CTO-mode decision. **Scope decision (operator, 2026-07-11)**: replacing `settings.PLACEHOLDER_ACCOUNT_BALANCE` (fixed $10,000 constant used for position sizing and loss-limit math) with a real, live-queried exchange balance is explicitly deferred to THIS gate, not built during Phase 1 paper trading — paper trading has no real capital regardless, so the placeholder is honest and sufficient until real capital is actually at risk |

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

- ~~Re-run the 6-month deep test on ETHUSDT~~ — DONE. **Break-even does
  NOT reproduce**: +9.2% on BTCUSDT, -1.9% on ETHUSDT (mixed per-period,
  not uniformly negative) — the earlier "reproduced positive on two
  independent samples" claim rested on two BTCUSDT time windows, not two
  different assets; this is weaker evidence than that framing implied.
  **Breaker Block and Partial TP both REPRODUCE their negative
  verdicts, more strongly**: Breaker Block -3.8% (BTC) -> -12.0% (ETH,
  4/6 periods affected vs. 1/6 on BTC); Partial TP -32.6% (BTC) ->
  -35.4% (ETH, 6/6 periods worse on both assets, 12/12 total). No code
  changed from this finding — `ENABLE_BREAKEVEN` stays off by default,
  which this result is a reason FOR, not against. See CHANGELOG.md for
  the full comparison table.
- ~~Add a third, less-correlated symbol (SOLUSDT)~~ — DONE. **Break-even
  is now negative on 2 of 3 tested assets**: +9.2% (BTC), -1.9% (ETH),
  -4.8% (SOL) — SOLUSDT's result was uniformly flat-to-negative (0
  periods improved, 4 of 6 worse), not mixed the way ETHUSDT's was. The
  honest read is no longer "asset-dependent, could go either way" but
  "more often negative than positive on the assets tested so far," with
  the caveat that 3 assets is still a small sample of assets.
  **Breaker Block (-1.9% SOL) and Partial TP (-29.1% SOL, 6/6 periods
  worse) both reproduce their negative verdicts on all 3 assets now** —
  Partial TP is 18 of 18 tested periods worse across three independent
  assets with zero exceptions, the most robust finding in the project.
  See CHANGELOG.md for the full 3-asset comparison table.
- ~~Test a 4th asset (XRPUSDT)~~ — DONE. **Break-even's apparent
  2-of-3-negative trend did NOT hold** — XRPUSDT came back +5.4%,
  making the 4-asset picture BTC +9.2% / ETH -1.9% / SOL -4.8% /
  XRP +5.4%: a genuine 2-of-4/2-of-4 split, not a lean in either
  direction. This is itself the important result: a trend that looked
  real after 3 assets reverted to noise with a 4th, exactly the
  small-sample-of-assets risk flagged in the SOLUSDT entry above.
  **Breaker Block also softened** — XRPUSDT's +1.5% is its first
  positive result (3 of 4 assets still negative, so still not
  recommended, but "negative on every asset" is no longer accurate).
  **Partial TP remains unanimous**: -28.7% on XRP, negative on 4 of 4
  assets, 24 of 24 tested periods, zero exceptions — the only one of
  the three findings solid enough to actively recommend against, not
  just decline to recommend. See CHANGELOG.md for the full 4-asset
  comparison table.
- ~~Add time-anchored fetching (`--end-date`) and run a first cross-year
  test~~ — DONE. `CandleFetcher.fetch_ohlcv_history()` gained
  `end_time_ms`; `run_backtest.py --end-date YYYY-MM-DD` anchors a fetch
  to end at a specific past date instead of "now". First real use:
  BTCUSDT 6-month/6-period, anchored to 2025-07-10 instead of the
  existing 2026-07-10 window. **Break-even flips sign on the SAME
  asset**: +9.2% (2026) vs. **-1.9%** (2025) — the clearest evidence yet
  that this feature's effect is regime/time-dependent, not just
  asset-dependent; there is now no dimension (asset OR time) along which
  it has shown a reliable direction. Breaker Block had exactly 0.0%
  effect in the 2025 window (never fired differently from baseline).
  Partial TP reproduced almost exactly across YEARS too: -32.6% (2026)
  vs. -32.1% (2025) — now confirmed across 4 assets in one time window
  AND 2 time windows on one asset, the strongest evidence for any single
  finding in this project. See CHANGELOG.md for the full table.
- ~~Build walk-forward validation (Phase 1 gate #2)~~ — DONE.
  `scripts/run_backtest.py::walk_forward_report()` + `--walk-forward`
  CLI flag: evaluates a chronological period sequence against explicit,
  deterministic criteria (>= 66% profitable periods, <= 2 consecutive
  losing periods, no first-half-vs-second-half degradation >50%) rather
  than just an aggregate sum. Deliberately NOT a rolling
  parameter-refitting walk-forward (see `ENGINEERING_DECISIONS.md` #8 —
  no tunable parameters exist yet to refit). 10 new unit tests
  (`test_run_backtest.py`, previously zero coverage for
  `scripts/run_backtest.py`'s pure functions). **Real result: BTCUSDT
  2026 baseline PASSED** — 6/6 profitable, 0 losing streak, no
  degradation (second half actually outperformed the first). This is
  the formal Phase 1 gate #2 artifact.
- ~~Run `--walk-forward` on the other 3 assets' baselines
  (ETH/SOL/XRP)~~ — DONE. **All 4 assets PASSED**: 24/24 periods
  profitable, 0 losing streaks anywhere, every asset's second half
  flat-or-better than its first (BTC $237->$408, ETH $367->$541, SOL
  $586->$814, XRP $474->$476). Phase 1 gate #2 is now CLOSED for the
  current asset set. This specifically validates the baseline
  strategy's forward-time consistency, not the mixed experimental
  features (break-even/Breaker Block/partial-TP), which stay separately
  tracked.
- ~~Harden risk controls: circuit breaker auto-reset~~ — DONE (Phase 1
  checklist item "build production-ready risk controls"). Found and
  fixed a real gap: the circuit breaker had NO auto-reset mechanism at
  all and no operator-facing reset path (no dashboard endpoint, no
  CLI) — once tripped, trading halted permanently until someone
  manually edited the database. `run_paper.py::_check_drawdown_and_
  maybe_trip` now auto-resets once a fresh daily/weekly check both pass
  again, relying on `TradeJournal`'s reports already being UTC-day/
  ISO-week scoped (no new date-math needed). Alerts fire on auto-reset
  too, not just on trip. Real-balance integration
  (`PLACEHOLDER_ACCOUNT_BALANCE`) explicitly deferred to Phase 1 gate #4
  per operator decision — see the Phase 1 gate table above and
  `app/config.py`. Verified via a real-temp-SQLite-DB script (3
  scenarios: auto-reset when clear, trips on a real breach, stays
  tripped while still breached).
- ~~Resolve the spec/implementation ambiguity in confluence strength~~ —
  DONE (audit item #9, a genuine core JadeCap rule with a real
  spec-vs-code disagreement -- confirmed in scope per the operator's
  "only core rules" instruction, unlike equal-highs/lows below). Added
  opt-in `require_full_confluence` (`--strict-confluence` CLI flag),
  A/B tested across all 4 assets, 6-month/6-period each: requiring BOTH
  sweep AND CHOCH (the strict, spec-literal reading) cuts trade count
  75.9% (457 -> 110) for a per-trade PnL only 3.8% different from the
  looser default -- not meaningfully higher quality, just far fewer
  trades of the same quality, costing ~75% of total profit.
  **Resolved in favor of the existing (looser) implementation** —
  `docs/strategy_spec.md` section 6 rewritten to explicitly state the
  rule (sweep OR CHOCH, not both) with this evidence cited directly in
  the spec text, closing the ambiguity for good. 5 new tests. See
  CHANGELOG.md for the full comparison table.
- ~~Equal-highs/equal-lows liquidity detection~~ — NOT implemented,
  correctly out of scope. Confirmed (again, per the operator's explicit
  "only if they are core JadeCap trading rules" instruction this round):
  `docs/strategy_spec.md` section 2 does not define this rule at all —
  it would be a NEW rule requiring a spec decision first, not an
  ambiguity resolution in an existing rule (unlike confluence strength
  above). Stays documented below as a candidate that needs a spec
  addition before any implementation work, not attempted this round.
- ~~Controlled parameter sweep (`_RR`/`_STOP_BUFFER`/`_LOOKBACK`/
  `_IMPULSE_MULT`)~~ — DONE. One-at-a-time sweep, in-sample selection by
  robustness (not highest profit) on BTCUSDT, validated on held-out
  out-of-sample periods, then ETHUSDT/SOLUSDT/XRPUSDT, then a cross-year
  check (BTCUSDT 2025) added specifically because cross-asset robustness
  alone was already shown insufficient (break-even). **All 4 candidates
  ADOPTED as new defaults**: `_RR` 2.0->2.5, `_STOP_BUFFER`
  0.001->0.0015, `_LOOKBACK` 10->15, `_IMPULSE_MULT` 1.5->1.8. Standard-
  scale confirmatory run (BTC 2026, `--periods 6 --walk-forward`):
  **+66.7% PnL, walk-forward still PASSED**. Full methodology, every
  number, and stated caveats in `docs/parameter_sweep_report.md`.
  Discovered along the way: `BacktestEngine`'s walk-forward scan is far
  worse than linear in period length (3000 candles ~88s vs. 1500
  candles ~7s) — an initial sweep attempt at the usual 3000-candle scale
  ran 80+ minutes with no visible progress before being killed and
  redesigned.

See `CHANGELOG.md`/`HANDOFF.md` for full evidence tables on all of this.

## Immediate (highest ROI, unblocked, no operator input needed)

1. **Re-run walk-forward validation on ETHUSDT/SOLUSDT/XRPUSDT at the
   standard 3000-candle/6-period scale under the NEW tuned defaults** —
   only BTCUSDT has been re-confirmed at that scale so far (the sweep's
   own cross-asset check used smaller 1500-candle/8-period windows,
   where all 3 held up, but a full standard-scale re-confirmation for
   all 4 assets would close Phase 1 gate #2 out completely under the
   new constants, matching how gate #2 was originally closed for the
   old defaults).
2. **Run more `--end-date` cross-year tests, prioritized over more
   assets** — one time-anchored BTCUSDT test just produced a bigger
   revision to the break-even story (a sign flip on the SAME asset)
   than three additional assets combined. Natural next steps: (a) a
   2024 window (further back, only 1 more day-count worth of pagination
   given `--end-date` now works), (b) the same 2025 window on
   ETHUSDT/SOLUSDT/XRPUSDT to see whether Partial TP's time-robustness
   holds for them too. Should now also re-run under the NEW tuned
   defaults, not the old ones.
3. **Break-even and Breaker Block: stop looking for a "final verdict" at
   all — treat "no reliable direction across assets OR time" as the
   actual, settled conclusion.** Both now show sign flips or
   inconsistent effects across every axis tested (4 assets, 2 time
   windows on the asset with the strongest original signal). Further
   testing of either dimension alone has clearly diminishing ROI.
4. **`ENABLE_BREAKEVEN` stays off by default, permanently** — reaffirmed,
   now by a same-asset sign flip across time in addition to the earlier
   cross-asset coin flip. This is not being revisited without a
   fundamentally different kind of evidence (e.g. a parameter change
   that's shown to correlate with the sign, not just "one more sample").

## Near-term (needs the above first, or is inherently larger scope)

5. **Parameter sweep of `BREAKEVEN_TRIGGER_R`/`PARTIAL_TP_TRIGGER_R`/
   `PARTIAL_TP_PORTION`** — deliberately EXCLUDED from the 2026-07-11
   controlled sweep (see `docs/parameter_sweep_report.md` §1): those
   three only affect the break-even/partial-TP EXPERIMENTAL features,
   which are off by default with negative-or-inconsistent evidence, so
   tuning their triggers wasn't part of MVP-baseline hardening. Given
   Partial TP's negative result was explained by this strategy's
   SPECIFIC win-rate/RR profile (which the `_RR` sweep just changed from
   2.0 to 2.5), a smaller `PARTIAL_TP_TRIGGER_R` or re-testing against
   the NEW `_RR` might change that conclusion -- worth investigating
   with the same in-sample/out-of-sample/cross-asset/cross-year
   discipline used for the core-rule sweep, not by assumption. **Hard
   rule, non-negotiable, unchanged**: any sweep MUST reserve genuinely
   held-out data never inspected until the final decision.
6. **Equal-highs/equal-lows liquidity detection** (audit item #3) — spec
   addition required first (see "Done" above for why this is
   deliberately NOT implemented yet): `detect_liquidity_sweep()` only
   recognizes single swing-point sweeps; real SMC also treats clusters
   of near-equal highs/lows as a stronger resting-liquidity signal.
   Neither the spec nor the code currently defines this. If/when the
   operator decides this should become a specified core rule, the
   sequence is: spec addition first, then implementation, then the same
   A/B discipline as every other change here.

## Phase 2 (deferred, out of scope for Phase 1 — do not implement yet)

Per the operator's scope-lock directive: Phase 1 is JadeCap only. These
items do not directly increase the probability that JadeCap specifically
becomes a profitable automated trading system — they are architecture/
scalability ideas that only become relevant AFTER JadeCap has cleared
Backtest -> Walk-Forward -> Paper Trading -> Small Live Validation.
Documented here so they aren't lost, not started.

- **Multi-strategy plug-in architecture** — today `SignalEngine` is a
  single hardcoded pipeline. If/when a second, genuinely different
  strategy is worth trying (not just parameter variants of the current
  one), the Strategy Engine's interface (`generate_signal(symbol,
  ltf_candles, htf_candles) -> TradeSignal | None`) is already a clean
  enough contract to support multiple implementations behind it — no
  redesign needed yet. Explicitly a Phase 2 idea (this would be the
  first step toward a "multi-strategy platform," which the scope lock
  names directly as out of scope for Phase 1).
- **Monte Carlo readiness** — the backtest engine's trade list
  (`BacktestResult.trades`) already has everything needed (`pnl`,
  `direction`, `size`, timestamps) to bootstrap/reshuffle trade
  sequences for Monte Carlo drawdown analysis. Not yet built; a natural
  next step once there are enough real trades across enough periods to
  make resampling meaningful (still on the small side for resampling).
  Not required for JadeCap to clear the 4 Phase 1 gates, so deferred.

## Explicitly NOT started, and why

- **Live Trading** (`LiveBroker`, `exchange/okx_client.py`,
  `exchange/orangex_client.py`) — all `NotImplementedError` stubs,
  deliberately. This is Phase 1 gate #4 (Small Live Validation),
  requires, IN ORDER: (a) out-of-sample validation across genuinely
  different market regimes (substantial progress -- 6-month results now
  exist for FOUR assets AND 2 years on BTCUSDT, walk-forward validation
  built and PASSED for ALL FOUR assets, but two of the three
  experimental features show no reliable direction across assets OR
  time — see items #1-2 above for remaining cross-year work), (b)
  replacing `settings.PLACEHOLDER_ACCOUNT_BALANCE` with a real,
  live-queried exchange balance (explicitly deferred here, not built
  during Phase 1 paper trading — see the Phase 1 gate table above), (c)
  operator-issued OKX API keys with withdrawal
  disabled, (d) a small live-capital limit agreed with the operator, (e)
  step-by-step operator approval at each stage per
  `docs/live_trading_checklist.md`. None of this proceeds without the
  operator present — API credential provisioning and live-trading
  approval are both explicit stop conditions, not something a CTO-mode
  session decides alone.
- **Paper trading Breaker Block or Partial TP** — NOT planned currently.
  Breaker Block's backtest result is now slightly negative (was
  neutral); Partial TP's is negative on two independent samples. Neither
  has positive evidence to justify wiring into paper trading.
