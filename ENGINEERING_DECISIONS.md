# ENGINEERING_DECISIONS — JadeCap Automated Trading Bot

Architecture-decision-record style log, organized by TOPIC (not
chronologically — see `CHANGELOG.md`/`HANDOFF.md` for the timeline).
Each entry: the decision, why it was made, what alternatives were
considered, and the trade-off accepted. Written so a new engineer never
has to ask "why is it built this way?"

---

## 1. Zone-mitigation filtering lives in `SignalEngine`, not inside the detectors

**Decision**: `is_zone_mitigated()` (`app/strategy/utils.py`) is applied
in `SignalEngine.generate_signal()`, AFTER calling
`detect_fair_value_gap()`/`detect_order_block()`, not inside those
functions themselves.

**Why**: `detect_breaker_block()` depends on `detect_order_block()`
returning the RAW, unfiltered order block so it can independently check
whether that same zone was later closed-through and retested (a breaker
pattern is specifically defined in terms of a mitigated OB reversing).
Filtering mitigation out at the detector level would silently break that
downstream consumer.

**Alternative considered**: add a `mitigated: bool` field to the
returned zone dict instead of filtering. Rejected — would require every
caller (including tests) to remember to check the flag, whereas
filtering at the orchestration layer means `build_entry_model()` (a pure
function) never has to know mitigation exists at all.

**Trade-off accepted**: `detect_fair_value_gap`/`detect_order_block`'s
own return values are honest about "what structure exists" but not
"what's tradeable right now" — a caller that imports them directly
(bypassing `SignalEngine`) gets unmitigated-aware raw zones. Acceptable
since nothing in the codebase currently does that except `detect_breaker_block`,
which needs exactly that raw behavior.

---

## 2. `ltf_bias` reuses `detect_htf_bias()` on the LTF candle series

**Decision**: `/dashboard/bias`'s `ltf_bias` field runs the SAME
structural-bias algorithm (`detect_htf_bias()`) against LTF candles
instead of HTF candles.

**Why**: `docs/strategy_spec.md`/`signal_engine.py` never define an "LTF
bias" concept — `detect_htf_bias()` is called ONLY on HTF candles in the
real strategy; LTF candles feed the sweep/CHoCH/FVG/order-block
detectors instead. The `ltf_bias` API field predates this design (an
early Milestone-1-era contract field) and was kept for API-contract
stability rather than removed.

**Alternative considered**: remove the field entirely (breaking the
frontend type contract), or hardcode it to always be `"neutral"`.
Rejected both — reusing the real, generic structural-bias algorithm on a
second real dataset produces a genuine (if differently-scoped) reading,
not fabricated data.

**Trade-off accepted**: this is a judgment call, not a spec-derived
decision — made without operator sign-off since it fell outside the
explicit approval-required categories (API credentials, live trading,
paid services, security, destructive ops). Flagged in `ROADMAP.md`/`PROJECT_STATUS.md`
as worth reconfirming if this field ever drives an actual trading
decision rather than just dashboard display.

---

## 3. `PLACEHOLDER_ACCOUNT_BALANCE` centralized in `settings`, not duplicated

**Decision**: moved from a private constant in `scripts/run_paper.py`
into `settings.PLACEHOLDER_ACCOUNT_BALANCE` (`app/config.py`).

**Why**: `/dashboard/risk-status` needed the exact same fixed
denominator `run_paper.py`'s `_pnl_to_percent()` uses to convert
realized PnL into daily/weekly loss-limit percentages. Two independent
copies of the same "no real account-balance source exists yet" constant
would silently drift the moment one was changed and the other wasn't.

**Trade-off accepted**: none significant — this is a pure DRY win, no
behavior change for existing callers.

---

## 4. Backtest daily/weekly loss-limit denominator is the run's STARTING balance, not the compounding one

**Decision**: `BacktestEngine.run()`'s daily/weekly PnL% (fed to
`risk_manager.evaluate()`) divides realized PnL by the `account_balance`
value passed into `run()` at the start — a fixed number — even though
position sizing within the same run uses the COMPOUNDING running
balance.

**Why**: mirrors `scripts/run_paper.py`'s `PLACEHOLDER_ACCOUNT_BALANCE`-based
`_pnl_to_percent()` (also fixed, not compounding), so backtest and paper
loss-limit percentages stay comparable to each other and to what an
operator would actually see triggering a real halt in paper/live.

**Alternative considered**: use the compounding balance (consistent with
position sizing in the same engine). Rejected — would make backtest
loss-limit percentages diverge from paper's real behavior, defeating the
point of backtesting as a predictor of paper/live outcomes.

**Trade-off accepted**: backtest's OWN internal consistency is slightly
uneven (sizing compounds, loss-limit-% does not) in exchange for
cross-engine (backtest vs. paper) consistency, which was judged more
important.

---

## 5. `CandleFetcher` uses two different OKX endpoints for two different jobs

**Decision**: `fetch_ohlcv()` (single page, used by paper trading's
"give me the latest N candles" need) hits `/market/candles`.
`fetch_ohlcv_history()` (deep pagination, used by backtesting) hits the
separate `/market/history-candles` endpoint.

**Why** (confirmed empirically against the real OKX API, not assumed
from documentation): `/market/candles` is hard-capped at ~1440 total
candles regardless of how many pages are fetched (repeated `after`-cursor
pagination against it returns an empty page after exactly 1440 candles,
every time, verified directly). `/market/history-candles` has the same
request/response shape and cursor semantics but pages back reliably far
deeper (verified 3000 candles / ~125 days with no early cutoff).

**Also fixed in the same pass**: `fetch_ohlcv`'s `since` parameter was
wired to OKX's `before` query param, which (confirmed empirically)
returns candles NEWER than the given timestamp — the opposite of
backward pagination. Now correctly maps to `after`.

**Trade-off accepted**: two code paths instead of one, but they serve
genuinely different needs (paper trading never needs more than the
latest window; backtesting needs deep history) and unifying them behind
one method would obscure the real difference in guarantees between the
two OKX endpoints.

---

## 6. Break-even stop management implemented independently in `BacktestEngine`, not by reusing `OrderManager.move_to_breakeven()`

**Decision**: `BacktestEngine._simulate_trade()`'s break-even logic
(effective-stop tracking, trigger detection) is implemented inline,
rather than calling the existing `OrderManager.move_to_breakeven(position)`.

**Why**: `move_to_breakeven()`'s contract is a one-shot call against a
DB-row-shaped `position` dict — designed to be invoked externally,
once, when a caller (paper/live loop) decides "move this now."
`_simulate_trade()`'s candle-scanning loop needs to check the trigger
condition on EVERY candle internally as part of a tight forward scan;
forcing that loop to construct/mutate position-dict-shaped objects on
every iteration just to call a function designed for a different calling
pattern would add complexity without benefit.

**Trade-off accepted**: `OrderManager.move_to_breakeven()` remains
unused in this round (see `ROADMAP.md` item #2 — it's the natural fit
once break-even is wired into PAPER trading, where positions genuinely
are DB rows and the one-shot-call contract fits naturally).

---

## 7. Signal persistence (`/dashboard/signals`) scoped to `run_paper.py` only, not `run_backtest.py`

**Decision**: `SignalTracker.record_signal()` is called from
`scripts/run_paper.py`'s `run_once()`, never from `scripts/run_backtest.py`.

**Why**: backtest signals are simulation output, already exported via
CSV/markdown reports per backtest run. The `signals` DB table (and
`Signal` model) has no `mode` column (unlike `Trade`, which does), so
persisting backtest signals into the same table as real paper signals
would make the live dashboard unable to distinguish "a real signal from
the currently-running paper bot" from "a signal from someone's backtest
three weeks ago." Solving that properly needs a `mode` column addition
first — a deliberate, deferred scope boundary, not an oversight.

---

## 8. Out-of-sample validation is period-splitting, not walk-forward parameter refitting

**Decision**: `scripts/run_backtest.py --periods N` splits fetched
history into `N` equal, non-overlapping chronological chunks and runs
each independently (fresh account balance, no shared state) — NOT a
rolling walk-forward window that refits parameters on each window before
testing the next.

**Why**: the strategy currently has no tunable/fitted parameters
(`_LOOKBACK`, `_IMPULSE_MULT`, `_STOP_BUFFER`, `_RR`, `BREAKEVEN_TRIGGER_R`
are all fixed constants, explicitly disclosed in-code as "reasonable
defaults, not tuned"). A walk-forward refitting loop would have nothing
to refit yet — building one now would be premature machinery for a
capability the strategy doesn't have. Period-splitting still achieves
the real goal (checking whether results are consistent across
genuinely disjoint historical windows rather than resting on one
continuous sample) without that unused complexity.

**Future note** (see `ROADMAP.md` item #6): the MOMENT any parameter
tuning/sweeping work begins, this tool's held-out periods become
load-bearing for avoiding overfitting — tune only against a subset of
periods, verify only against periods never inspected during tuning.
Skipping this discipline defeats the entire reason the tool exists.

---

## 9. Conservative same-candle ordering for simultaneous stop/target/breakeven touches

**Decision**: when a single candle's `[low, high]` range would trigger
more than one exit-relevant condition in the same bar (original
stop-loss AND take-profit; or original stop-loss AND the break-even
trigger level), `BacktestEngine._simulate_trade()` always resolves in
favor of the WORSE outcome for the trader — stop-loss over take-profit,
and the original stop over an "optimistically triggered then saved by
breakeven" outcome.

**Why**: OHLC candle data cannot reveal the true intra-candle
sequencing of price action. Assuming the favorable order whenever
ambiguous would systematically bias backtest results optimistic in a way
that could never be verified or corrected later. This principle
predates the break-even feature (the SL-before-TP assumption was already
in place) and was extended to cover the new breakeven-trigger-vs-original-stop
case using the identical reasoning.

**Trade-off accepted**: real fills might occasionally be more favorable
than this pessimistic assumption produces — deliberately, since a
backtest that's too optimistic is more dangerous than one that's overly
cautious.
