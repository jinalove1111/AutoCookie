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

**Trade-off accepted**: `OrderManager.move_to_breakeven()` remained
unused for the rest of that round. **Update**: now consumed exactly as
anticipated — `scripts/run_paper.py::_maybe_move_to_breakeven()` calls
`OrderManager(PaperBroker()).move_to_breakeven(position)` to compute the
new stop, then persists it via the new
`TradeTracker.update_stop_loss()`. The one-shot-call contract fits
paper trading's DB-row positions naturally, exactly as predicted; only
the "should we call this right now" trigger/idempotency logic (1R
distance, already-at-breakeven check) is new, since `move_to_breakeven()`
itself has no concept of a trigger condition — it just moves the stop
unconditionally whenever called.

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

**Follow-up (walk-forward validation built as Phase 1 gate #2)**: the
operator's scope-lock directive named "walk-forward validation" as an
explicit, required Phase 1 deliverable distinct from backtesting. Rather
than build a refitting loop with nothing to refit (which this decision
already rejected), `run_backtest.py::walk_forward_report()` was added on
TOP of the existing period-splitting: it takes the same chronological
period sequence and checks it against explicit PASS/FAIL criteria
(minimum profitable-period ratio, maximum consecutive losing periods, a
first-half-vs-second-half degradation check) instead of just printing an
aggregate sum. This satisfies the actual intent behind "walk-forward
validation" (does performance hold up moving forward through time,
un-hidden by averaging) without pretending there's parameter-refitting
happening where there isn't. First real result: BTCUSDT 2026 baseline
PASSED (6/6 profitable, 0 losing streak, second half outperformed the
first). The distinction this decision draws (no refitting mechanism
exists) remains accurate and unchanged — this follow-up adds a
validation GATE on top of period-splitting, not a refitting loop.

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

---

## 10. Every new strategy-behavior change ships as an opt-in flag, threaded end-to-end, before any default changes

**Decision**: break-even (`use_breakeven`) and Breaker Block
(`use_breaker_block`) both follow the identical pattern: a `False`-
default parameter on `SignalEngine.generate_signal()`/`BacktestEngine.run()`,
threaded through to a `scripts/run_backtest.py` CLI flag, so the exact
same `--symbol`/`--timeframe`/`--candles`/`--periods` invocation can be
re-run with only that one flag toggled for a clean A/B comparison.

**Why**: this is the only way to make "compare before vs. after" (an
explicit operator requirement) a literal, mechanical, repeatable
operation rather than an informal eyeball comparison across separate
runs that might differ in other ways. It also means a feature that
turns out NOT to help (see decision #11 below) costs nothing to keep in
the codebase — it's inert until explicitly requested, and remains
available for re-testing against future, larger, or differently-timed
samples without writing new code.

**Alternative considered**: implement directly as new default behavior,
then revert via `git` if a backtest comparison looked bad. Rejected —
requires re-running the *entire* validation after implementation to
decide "was this real," rather than being able to compare in one
invocation-pair; also leaves no reusable, permanent lever for re-testing
under different future conditions (a git-reverted feature is gone, an
opt-in flag is dormant and instantly available again).

**Trade-off accepted**: every new strategy behavior adds one more
boolean parameter threaded through several layers (`SignalEngine` →
`BacktestEngine` → CLI). Accepted as a small, mechanical cost against the
alternative of ad-hoc, harder-to-reproduce comparisons.

---

## 11. A "no measurable effect" A/B result is documented as a finding, not silently discarded

**Decision**: when Breaker Block's A/B backtest showed literally zero
difference in trade count/PnL/win-rate across all 6 tested periods, the
response was NOT to assume the feature doesn't work and move on
silently. Instead: (a) directly scanned every walk-forward step of a
real dataset to confirm the detector fires and CAN change output (it
does — 124/970 raw detections, 29 unmitigated, 2 confirmed signal-level
differences), then (b) determined precisely why those 2 differing
moments never affected the actual backtest (both fell inside an
already-open trade's window, per the one-trade-at-a-time concurrency
guard).

**Why**: "no effect measured" and "proven not to work" are different
claims, and conflating them would either (a) wrongly discard a feature
that might matter in a different sample, or (b) leave a future engineer
unable to tell whether "we tried this and it failed" or "we tried this
and got inconclusive results due to how the test sample happened to be
shaped." The diagnostic step turns an ambiguous null result into a
precise, falsifiable, reusable piece of evidence: "this feature is
functionally correct; it needs a sample with more idle time between
trades to get a fair test."

**Trade-off accepted**: the diagnostic scan (re-running detection/signal
generation at every step outside the normal backtest flow) is extra work
beyond what the operator's instructions strictly required ("document the
evidence and keep it optional" would have been satisfiable with just the
null aggregate result). Accepted because a coverage-audit/research
project's entire value proposition is evidence quality, not
throughput — an unexplained null result is much weaker evidence than an
explained one.

---

## 12. Partial-TP checked BEFORE take-profit within a candle, not after

**Decision**: in `BacktestEngine._simulate_trade()`, the per-candle check
order is: original stop-loss (worst case) → partial-TP trigger (if not
yet triggered) → take_profit → break-even trigger. Partial-TP
deliberately comes BEFORE take_profit, not after.

**Why**: `PARTIAL_TP_TRIGGER_R` (1R) is always closer to entry than
`take_profit` (`RR * 1R`, and `_RR = 2.0` in this codebase) for any
RR > 1. That means any real, monotonic price path that reaches
take_profit necessarily passed through the partial-TP trigger price
first. If the code checked take_profit before the partial trigger, a
single candle whose range happened to span both levels would close the
FULL size at take_profit and skip the partial leg entirely — silently
wrong, since in reality the partial trigger would have executed on the
way there. Checking partial-TP first ensures a same-candle jump straight
to take_profit still correctly banks the partial leg at its own, nearer
price before the remaining size continues to take_profit.

**Alternative considered**: treat a same-candle multi-level touch as
ambiguous and resolve conservatively in the "worse" direction, the same
policy already used for stop-loss-vs-take-profit ambiguity. Rejected
here specifically — unlike stop-vs-target (where either order is
physically plausible and unknowable from OHLC), partial-trigger-then-
target is not actually ambiguous: the price LEVELS themselves guarantee
the ordering (partial trigger is strictly between entry and target), so
assuming it is not a favorable-case guess, it's a certainty derivable
from the trade's own parameters.

**Trade-off accepted**: none — this ordering is not a probabilistic
assumption like the SL-vs-TP one, it's a deterministic consequence of
`PARTIAL_TP_TRIGGER_R < RR`. (If a future change ever made
`PARTIAL_TP_TRIGGER_R >= RR` for some configuration, this ordering
argument would no longer hold and would need to be revisited.)

---

## 13. HTF fetch size is derived from the LTF request's real time span, not copied from its candle count

**Decision**: `scripts/run_backtest.py` no longer requests the same
candle COUNT for the HTF fetch as the LTF fetch. `htf_candle_count_for_span()`
converts the LTF request into a real time span (via the new
`app.data.candle_fetcher.timeframe_to_timedelta()`) and divides by the
HTF bar's own duration to get the right HTF candle count for that same
span, with a 300-candle floor.

**Why**: discovered as a real bug, not a theoretical concern -- a
6-period/3000-candles-per-period regime-validation run (`--candles 3000
--periods 6`) requested 18000 candles for BOTH the `15m` LTF fetch
(correctly ~187 days) and the `4h` HTF fetch (~8.2 years, since a fixed
candle count means wildly different real time spans across timeframes).
The HTF fetch consequently paged through far more history than needed
and had to be killed after 10+ minutes with no output. A candle COUNT is
not a portable unit of "how much history do I need" across different
timeframes; a time SPAN is.

**Alternative considered**: cap the HTF request at some fixed maximum
(e.g. `min(total_requested, 2000)`) rather than computing the real
span. Rejected — an arbitrary cap either over-fetches for small LTF
requests (wasteful) or under-fetches for large ones (risks starving
`detect_htf_bias()` of real runway for genuinely long backtests), while
computing the actual required span gets the right answer in both
directions automatically.

**Trade-off accepted**: none significant — `timeframe_to_timedelta()`
only supports the same timeframe formats `to_okx_timeframe()` already
does (`m`/`h`/`d`/`w` suffixes), so no new format support was needed to
implement this.

---

## 14. Out-of-sample results are re-validated at larger scale before being trusted, not assumed to generalize

**Decision**: after the initial A/B tests for break-even/Breaker Block/
partial-TP (all on a single ~31-day/3-period sample), the SAME three
experiments were re-run on a 6-month/6-period sample before treating any
of the three conclusions as settled.

**Why**: this is not redundant busywork -- it changed one of the three
conclusions. Break-even and partial-TP reproduced almost exactly (+13.5%
-> +9.2%; -31.4% -> -32.6%), which is real evidence those effects are
robust, not sample-specific flukes. Breaker Block did NOT reproduce as
"neutral" -- on the larger sample it fired for real once and the effect
was negative. Had the project stopped at the first (smaller) sample and
called Breaker Block's result final, it would have carried a materially
wrong (too optimistic) belief about that feature forward. The entire
point of building out-of-sample tooling (see decision #8) is defeated if
its output is only ever checked once and then trusted indefinitely.

**Alternative considered**: treat the first sample as sufficient once
each experiment showed SOME result (positive/neutral/negative) and move
on to the next roadmap item. Rejected — a single sample, however
carefully split into non-overlapping periods, is still one dataset from
one continuous slice of history; "reproduces on an independent, larger,
more varied sample" is a categorically stronger evidentiary bar than
"produced a result once."

**Trade-off accepted**: real time and API calls spent re-running
experiments that had already produced results once. Accepted because
the Breaker Block revision alone justified the cost -- it changed a
real conclusion this project would otherwise be carrying forward
incorrectly.

---

## 15. "Reproduced" must specify what varied between samples -- a second time window is not a second asset

**Decision**: when re-validating an A/B finding, the writeup (CHANGELOG.md/
PROJECT_STATUS.md/ROADMAP.md) always states explicitly what changed
between the two samples being compared (same asset/different time window,
vs. different asset/same time window, vs. both) rather than saying only
"reproduced" or "did not reproduce."

**Why**: decision #14 re-ran break-even/Breaker Block/partial-TP on a
6-month BTCUSDT sample and called break-even "the most robust of the
three findings -- same direction on two independent datasets," since it
reproduced its small-sample result (+13.5% -> +9.2%). That phrasing was
technically true but misleading: both of those "independent datasets"
were BTCUSDT, just different time windows. When break-even was then
tested on a 6-month ETHUSDT sample (same methodology, different asset),
it came back slightly NEGATIVE (-1.9%, mixed per-period) -- the opposite
conclusion. Partial-TP and Breaker Block, by contrast, reproduced their
negative verdicts on ETHUSDT too (even more strongly), so the SAME
"reproduced across two independent samples" language that turned out to
be fragile for break-even turned out to be genuinely robust for the
other two. The lesson is not "re-validation failed" -- it's that
asset-generalization and time-generalization are different claims with
different strength, and collapsing them into one word ("reproduced")
let an overconfident claim about break-even stand for one release cycle
longer than it should have.

**Alternative considered**: treat any second confirming sample,
regardless of what varied, as sufficient to call a finding "robust."
Rejected — this is exactly the failure mode that just occurred: two time
windows on a correlated single asset gave false confidence that would
not have survived a single additional asset test.

**Trade-off accepted**: writeups are longer and more hedged than a flat
"positive"/"negative" verdict would be. Accepted because the entire
point of this project's evidence-over-assumption philosophy (see
`ROADMAP.md`'s guiding principle) is defeated if "reproduced" is used
loosely enough to paper over exactly the kind of gap this decision
describes. `ENABLE_BREAKEVEN` shipping off-by-default (decision area:
see paper-trading wiring in CHANGELOG.md) is a direct, practical
consequence of taking this distinction seriously — an operator reading
only the headline verdict, not the fine print, still gets the safe
default.

**Follow-up (SOLUSDT then XRPUSDT rounds)**: the same lesson recurred one
level up. After a 3rd asset (SOLUSDT), break-even looked like it had a
real negative LEAN (2 of 3 assets negative) rather than being purely
asset-dependent noise — a 4th asset (XRPUSDT, +5.4%) broke that lean
back to a genuine 2-of-4/2-of-4 split. A small COUNT OF ASSETS can
manufacture the appearance of a trend exactly the way a small count of
PERIODS can (the original concern this decision was written for) —
"how many assets have been tested" needs the same explicit skepticism
as "how many periods have been tested." Breaker Block showed the same
pattern in miniature: unanimously negative across 3 assets, then a 4th
(XRPUSDT, +1.5%) broke the unanimity. Partial TP is the calibration
case that shows this ISN'T just "more data always overturns findings" —
it has now stayed negative on all 4 assets and 24 of 24 periods with no
sign of reverting, so a real, robust effect and an apparent-but-fragile
trend look different once enough independent samples exist; the risk is
mistaking the latter for the former too early.

**Follow-up (time-anchored `--end-date` testing)**: a third dimension
was added -- `CandleFetcher.fetch_ohlcv_history()` gained `end_time_ms`,
letting a fetch be anchored to a specific past date instead of always
"now". The very first cross-year test (BTCUSDT, 2025-07-10 vs.
2026-07-10) produced the single clearest data point yet: break-even
flipped sign on the SAME asset (+9.2% in 2026, -1.9% in 2025). Combined
with the cross-asset coin flip above, break-even has now shown no
reliable direction along either axis that's been tested (asset, or
time on the one asset checked both ways). Partial TP, again, held:
-32.6% (2026) vs. -32.1% (2025), nearly identical. The practical lesson
compounds: "how many time windows have been tested" needs the same
skepticism as asset count and period count -- and, notably, ONE
time-anchored test on ONE asset moved the break-even conclusion further
than THREE additional assets did, suggesting time/regime may be a
bigger driver of these effects than asset choice. This directly
reprioritized `ROADMAP.md` toward more `--end-date` testing over more
assets.

---

## 16. Circuit breaker auto-resets via the drawdown-check caller, not via internal date-math

**Decision**: `scripts/run_paper.py::_check_drawdown_and_maybe_trip` now
calls `circuit_breaker.reset()` when the breaker is currently tripped
but a fresh daily/weekly check both pass. `CircuitBreaker`/
`PersistentCircuitBreaker` themselves gained NO new date-boundary logic
-- the reset decision lives entirely in the caller that already computes
fresh, correctly-scoped PnL every iteration.

**Why**: `CircuitBreaker.reset()`'s docstring had long flagged this as
an explicit gap ("day-boundary scheduling... is a future milestone's
responsibility"), and in practice there was no way to clear a trip at
all short of manually editing the database -- no dashboard endpoint, no
CLI, nothing. For risk controls billed as "production-ready" (Phase 1
checklist item), a limit that can never un-trip itself is a real defect,
not a minor gap: `MAX_DAILY_LOSS_PERCENT`/`MAX_WEEKLY_LOSS_PERCENT` are
inherently periodic by definition, so a trip caused by one bad day
should not permanently halt trading on all subsequent good days.

The key insight that made this cheap to fix correctly: `TradeJournal.
generate_daily_report()`/`generate_weekly_report()` are ALREADY
UTC-calendar-day / ISO-calendar-week scoped (built for the loss-limit
checks themselves). That means `_check_drawdown_and_maybe_trip` already
recomputes the CORRECT "as of right now" daily/weekly PnL on every
iteration -- once a new day/week genuinely begins, those numbers
naturally reflect only the new period without any additional date
tracking. So the fix needed no new state (no "when was this tripped,
has a day passed" bookkeeping) -- just: if currently tripped AND the
fresh check now passes, reset.

**Alternative considered**: give `CircuitBreaker` its own
`tripped_at`-based auto-expiry (e.g. "auto-reset 24 hours after
`tripped_at`"). Rejected -- a fixed time-since-trip window doesn't
actually match a UTC-calendar-day boundary (a trip at 23:50 UTC would
"expire" at 23:50 the next day, not at UTC midnight), and would require
`CircuitBreaker` to know about calendar semantics it currently has zero
dependency on. Piggybacking on the drawdown-check caller's already-
correct day/week-scoped queries is both simpler and more accurate.

**Trade-off accepted**: the auto-reset logic implicitly assumes every
trip routes through this one drawdown-check call site (true today -- it
is the only `trip()` call site in the codebase, documented explicitly in
that function's docstring). If a future trip reason unrelated to
drawdown is ever added (e.g. "exchange API failure", mentioned as a
hypothetical in `circuit_breaker.py`'s module docstring), this logic
would incorrectly auto-clear it too and would need to become
reason-aware first (e.g. only auto-reset when `reason` matches a
drawdown-breach pattern). Documented as a caveat rather than solved
preemptively for a trip reason that doesn't exist yet.

---

## 17. Confluence-strength ambiguity resolved by fixing the SPEC, not the code

**Decision**: `docs/strategy_spec.md` section 6 was rewritten to
explicitly state that the confluence rule requires EITHER a matching
liquidity sweep OR a matching CHOCH (not both) -- matching
`entry_model.build_entry_model`'s existing default behavior. The
stricter reading (require both) was implemented as an opt-in
(`require_full_confluence`), A/B tested, and rejected based on real
evidence rather than assumed to be an improvement.

**Why**: this is the fourth time in this project a "surely a stricter/
more cautious rule is better" intuition was tested and found NOT to
hold (after break-even, Breaker Block, and partial-TP). Requiring both
sweep AND CHOCH across all 4 tested assets (BTC/ETH/SOL/XRP, 6-month/
6-period each) cut trade count by 75.9% (457 -> 110) while producing a
per-trade average PnL only 3.8% different from the looser rule --
statistically indistinguishable given the resulting small per-period
sample sizes (some periods dropped to 0-2 trades). The stricter rule
does not filter FOR better trades; it just filters out MOST trades,
including plenty of good ones, for no measurable quality gain. Total
realized profit dropped ~75% as a direct, near-proportional consequence
of trading 76% less often.

**Alternative considered**: leave the spec's ambiguous wording alone and
just document in `docs/strategy_coverage_audit.md` that the code is
"intentionally looser than a strict reading of the spec." Rejected --
an ambiguous spec that's silently overridden by code is worse than no
spec at all; a future reader (human or agent) re-deriving intent from
the spec text alone would reasonably conclude the code has a bug. Since
real evidence now exists showing the looser behavior is correct (not
just convenient), the spec should say so directly rather than staying
vague forever.

**Trade-off accepted**: `docs/strategy_spec.md` is no longer a
"conceptual contract written before implementation" document in this
one section -- it now cites specific A/B backtest numbers inline,
mixing spec-level and evidence-level content. Accepted because the
alternative (spec silent, evidence buried only in CHANGELOG.md) is
exactly the kind of gap that let this ambiguity go unresolved for as
long as it did in the first place -- the rule's actual definition
should live where someone reading the spec would look for it.

---

## 18. Parameter sweep monkey-patches module constants; doesn't add CLI flags for values likely to stay at defaults

**Decision**: `scripts/parameter_sweep.py` sweeps `entry_model._RR`/
`_STOP_BUFFER` and `order_block._LOOKBACK`/`_IMPULSE_MULT` by directly
overwriting the module attribute for the duration of each test
(`setattr(module, attr, value)`, always restored in a `finally` block),
rather than adding a new constructor/CLI parameter to
`build_entry_model()`/`detect_order_block()` the way `use_breaker_block`/
`require_full_confluence`/`use_breakeven` were added as real, permanent
opt-in parameters.

**Why**: those other flags represent genuinely NEW BEHAVIOR that a
caller might reasonably want to toggle in production (paper trading,
future backtests) — they earned a real parameter. These four constants
are different: per the operator's own methodology (step 10, "keep the
original defaults if no robust improvement is proven"), the expected
outcome of a sweep is usually "no change" — building permanent CLI
surface area for values that will likely never move from their default
is speculative complexity for a one-time research question, not a
feature. Monkey-patching is scoped exactly to the sweep script's own
process and always restored, so it cannot leak into or affect any other
code path.

**Consequence when the sweep DID find robust improvements**: all four
candidates cleared every validation gate (see `docs/parameter_sweep_
report.md`), so the actual module constants were changed directly in
`entry_model.py`/`order_block.py` (not left as sweep-only findings) —
the minimal, correct change once a real conclusion exists, matching this
decision's own reasoning: no new indirection was needed, because the
right long-term state was simply "the default is now this value",
exactly what changing the constant achieves.

**Alternative considered**: add real, permanent parameters (`rr=2.0`,
`stop_buffer=0.001`, etc.) to `build_entry_model()`/`detect_order_block()`
regardless of the sweep's outcome, on the theory that "future sweeps
will need this anyway". Rejected — per this project's established
"opt-in flag threaded end-to-end before any default changes" pattern
(decision #10), a real parameter implies a real, currently-supported use
case for varying it at runtime; no such use case exists yet for these
four constants (unlike `use_breakeven`, which paper trading genuinely
needs to toggle via `settings.ENABLE_BREAKEVEN`). Adding the plumbing
preemptively for a hypothetical future sweep would be exactly the kind
of scope expansion the operator's Phase 1 lock explicitly prohibits.

**Trade-off accepted**: re-running a similar sweep in the future (e.g.
after the deferred `BREAKEVEN_TRIGGER_R`/`PARTIAL_TP_TRIGGER_R`/
`PARTIAL_TP_PORTION` sweep, see `ROADMAP.md`) requires either extending
`parameter_sweep.py`'s own `PARAMETERS` dict (already designed to make
this cheap — see that file) or writing a similar monkey-patching
harness for those constants too, rather than reusing pre-built CLI
flags. Accepted because `parameter_sweep.py` itself is the reusable
artifact — the harness pattern, not a growing set of flags on
`run_backtest.py`, is what's meant to be reused.

**Follow-up (standard-scale re-confirmation across all 4 assets)**: the
sweep's own cross-asset validation used smaller 1500-candle/8-period
windows (chosen purely for sweep runtime, see the "period sizing" note
in `docs/parameter_sweep_report.md`). Since Phase 1 gate #2's ORIGINAL
closure (for the old defaults) used this project's standard 3000-candle/
6-period scale on all 4 assets, adopting new defaults without
re-confirming at that same standard scale would have left gate #2's
"closed" status resting on a smaller, faster check than the bar it was
originally held to. Re-ran `--candles 3000 --periods 6 --walk-forward`
on ETHUSDT/SOLUSDT/XRPUSDT under the new defaults (BTCUSDT had already
been done as the sweep's own final confirmatory run) — all three PASSED
unanimously, with PnL improving on every asset (ETH +4.6%, SOL +32.6%,
XRP +39.0%). This closes gate #2 to the SAME evidentiary standard it was
originally closed to, not a lesser one just because the new defaults
happened to be found via a faster-scale tool.

**Follow-up (cross-year check reveals a genuine period-granularity
sensitivity)**: extending the standard-scale check to 2025 on all 4
assets surfaced something the sweep's own smaller-scale (1500-candle)
BTC-2025 spot-check had NOT: at the standard 3000-candle/6-period scale,
BTCUSDT 2025 fails its walk-forward degradation check (every period
individually profitable, but the second half retained only 35.4% of the
first half's average PnL — the smaller-scale check's different period
boundaries happened not to isolate this same pattern). This is not a
contradiction to resolve by picking "the right" period size — it is
direct, first-hand evidence that walk-forward degradation conclusions
are sensitive to where period boundaries fall, not just what the
underlying price data says. The practical consequence: a single
period-size choice (even this project's own "standard" 3000-candle
scale) should be treated as one lens on the data, not the final word:
a result that looks clean at one granularity and degraded at another is
genuinely ambiguous, not resolved in favor of whichever run happened
first or looked better. Documented in `docs/parameter_sweep_report.md`
and `PROJECT_STATUS.md` rather than silently kept as only the more
favorable (1500-candle) result — the entire discipline this project has
built around "reproduced" claims (decision #15) applies here too:
"passed walk-forward" must specify at what granularity, the same way it
must specify on what asset or in what time window.

## 19. Premium/Discount range uses "most recent swing high/low independently", not "strict alternation"

**Decision**: `app.strategy.premium_discount.calculate_premium_discount()`
defines the "current swing range" as `[most recent swing low, most recent
swing high]`, where each is found independently via the existing
`find_swing_highs`/`find_swing_lows` helpers (`market_structure.py`) —
NOT by requiring the two to strictly alternate (e.g. "the last swing high
AND the swing low that immediately preceded/followed it"). If the range
is degenerate (`top <= bottom` — the most recent swing high's value is at
or below the most recent swing low's, meaning that high has already been
broken through), the function returns `None` rather than guessing.

**Why**: real market structure routinely prints two swing lows before the
next swing high confirms (or vice versa) — requiring strict alternation
would mean silently ignoring a fresher, more relevant swing point just
because it's the same type as the previous one, which contradicts the
project's existing convention: `bias.py`'s `detect_htf_bias()` already
reads "the last N swing highs" and "the last N swing lows" as two
independent series, not an alternating pair. Premium/Discount reuses that
same independence for consistency, and because "most recent swing point
of each type" is what actually defines the range a trader is currently
inside, regardless of how many same-type swings happened to print before
it confirmed.

**Why return `None` instead of clamping/swapping when the range is
degenerate**: a `top <= bottom` result means structure has already moved
past the point where "the current range" is a coherent concept (the most
recent high is no longer above the most recent low) — swapping top/bottom
or clamping to zero-width would produce a plausible-looking but
meaningless classification. Every other detector in this package
(`detect_htf_bias`, `detect_choch_mss`, `detect_liquidity_sweep`) already
follows this "return `None`/`neutral` on insufficient or incoherent
structure rather than fabricate an answer" pattern; this is the same
discipline applied to a new detector.

**Status**: detection-only as of this decision (see `docs/strategy_spec.md`
section 8, `PROJECT_STATUS.md`'s "Core rule completion (MVP)" table). Not
yet wired into `SignalEngine`/`build_entry_model` as an entry-quality
filter or take-profit target — that wiring is core-rule-MVP item #4
(structure-based TP), which depends on this AND on previous swing high/
low detection (item #2), both still pending as of this entry. Per
decision #10 (opt-in flag threaded end-to-end before any default
changes), when that wiring happens it should follow the same pattern
already established for `use_breaker_block`/`require_full_confluence`
rather than becoming an unconditional new filter on every existing
caller.

**Context**: this is the first of 5 core JadeCap rules the operator
directed be completed (2026-07-11) before any further parameter
optimization, sweeps, or multi-year backtesting resumes — see
`ROADMAP.md`'s "CURRENT PRIORITY: Core Rule MVP completion" section for
the full priority-ordered list and status.

## 20. OB+FVG confluence and structure-based TP ship as opt-in flags with NO backtest evidence yet, unlike this project's usual practice

**Decision**: core-rule-MVP items #3 (`require_ob_fvg_confluence`) and #4
(`use_structure_tp`) both landed as opt-in, default-`False` parameters on
`build_entry_model` (threaded through `SignalEngine`/`BacktestEngine`/
`run_backtest.py`), following decision #10's "opt-in flag before any
default change" pattern — but, unlike `use_breaker_block`/
`require_full_confluence`/`use_breakeven`/`use_partial_tp`, they shipped
WITHOUT an accompanying A/B backtest round in the same session.

**Why**: these two items were explicit, named entries on an
operator-directed priority list (`ROADMAP.md` "Core Rule MVP
completion"), scoped as "implement the rule," not "implement AND
A/B-validate the rule" — items #1 (Premium/Discount) and #5 (Equal
High/Equal Low) on the same list shipped detection-only, with no
backtest evidence either, and were accepted as "done" on that same
basis. Treating #3/#4 differently (blocking on a backtest round neither
the list nor the operator asked for at this step) would have been scope
creep against an explicit priority list, not extra rigor.

**Why this does NOT relax the project's "evidence over assumption"
standard**: both flags default `False`, so neither changes any existing
caller's behavior — the exact same non-negotiable discipline every prior
experimental flag in this project has followed before being A/B tested.
"Implemented" is documented everywhere (`ROADMAP.md`, `PROJECT_STATUS.md`,
`docs/strategy_spec.md`) as explicitly NOT the same claim as "evidenced,"
using the same "not yet A/B backtested" language applied to `use_breaker_
block` between its implementation commit and its first A/B round. Turning
either flag on by default remains gated on a future backtest round with
the same in-sample/out-of-sample/cross-asset discipline as every other
finding in this project (see decisions #14/#15).

**Status**: both opt-in, both default `False`, both unvalidated by real
backtest data as of this entry. A/B evaluation is listed as follow-up
work, not committed to a specific session.

## 21. OB+FVG "both agree" and structure-TP "farther of the two" resolve genuinely ambiguous ROADMAP prose, documented as judgment calls

**Decision**: `ROADMAP.md`'s item #3 said "change from 'either zone' to
'both agree'" — implemented literally: `require_ob_fvg_confluence=True`
requires a matching order block/breaker AND a matching FVG both present
(zone SELECTION, i.e. which one becomes the entry zone, is unchanged —
still "most recent index wins" between the two, since the prose only
named a presence requirement, not a selection rule). Item #4 said "long
targets previous high first; if HTF structure allows, target the 0.5
equilibrium instead/in addition" — implemented as: use the previous
swing high/low as the default target, but use whichever of {previous
swing high/low, equilibrium} is FURTHER from entry in the trade's favor,
among candidates that are still valid forward targets (beyond entry
price). "HTF structure allows" is read as "the broader swing-range
context makes a farther target reachable," not a literal second (HTF)
candle series — every other structural input `build_entry_model`
receives (sweep, CHoCH, FVG, OB) is LTF-only per `docs/strategy_spec.md`
section 1's HTF/LTF-separation rule, and `find_previous_swing_high`/
`calculate_premium_discount` both operate on a single candle list by
contract, so genuinely fetching a third (HTF) series for this one
parameter would break that established separation for no stated reason
in the roadmap text.

**Why "farther of the two" rather than "always equilibrium when it
exists" or "always previous high"**: "instead/in addition" is read
literally — the FURTHER candidate is strictly the more favorable
reading of "reaching past" the nearer one, and picking the maximum (long)
/minimum (short) of the two valid candidates is the simplest rule that
satisfies both "targets previous high first" (the default when
equilibrium is absent, nearer, or invalid) and "if structure allows,
[reach further]" (when equilibrium legitimately extends beyond it)
without needing a separate, undocumented tie-break rule.

**Why `rr` is recomputed instead of staying the fixed `_RR` constant
when a structure target is used**: `risk_manager.py`'s `RiskManager.
evaluate()` reads `signal.rr` directly against `settings.MIN_RR` as a
real risk-approval gate (see decision context in `docs/strategy_spec.md`
section 6's OB+FVG/structure-TP bullets). Once `take_profit` is no
longer defined as `entry +/- risk * _RR`, reporting the fixed constant
would misrepresent the trade's actual reward:risk to that gate — a
correctness fix, not a style choice, same category as decision #12
(ordering checks correctly within a single evaluation step) rather than
an optional refinement.

**Status**: both are documented, testable interpretations of prose that
had no single unambiguous reading — flagged here explicitly (per this
project's rule that every non-obvious judgment call gets its "why"
recorded) rather than presented as the only possible implementation.

## 22. Equal-highs/equal-lows uses a fractional tolerance and ADJACENT-pair-only comparison, not exact-match or all-pairs

**Decision**: `app.strategy.liquidity.detect_equal_highs`/
`detect_equal_lows` treat two confirmed swing highs (or lows) as "equal"
if they're within a fractional `tolerance` (default 0.1%) of each other
— not requiring exact price equality — and only compare ADJACENT pairs
in the swing-point sequence (index `i` vs. `i+1` in `find_swing_highs`/
`find_swing_lows`'s output), never every possible pair.

**Why tolerance, not exact equality**: real OHLCV price data essentially
never prints two swing highs/lows at the exact same float value; an
exact-equality rule would report zero real-world zones, making the
detector correct but useless. 0.1% was chosen as a reasonable starting
default (explicitly NOT backtest-tuned, same "disclosed, not yet
evidenced" status as `_RR`/`_STOP_BUFFER` before their 2026-07-11 sweep
— see decision #18) and exposed as a parameter specifically so it CAN be
tuned later with the same held-out-period discipline, rather than
hardcoded.

**Why adjacent pairs only, not all pairs**: standard ICT/SMC "equal
highs/lows" reads as two (or more) CONSECUTIVE failed attempts at a new
high/low near the same level — a level struck twice with an unrelated,
genuinely different swing in between is a different structural event
(a new range extreme was set and abandoned), not "the same liquidity
pool being retested." Comparing all pairs would additionally report
false-seeming zones between two swing points separated by real
intervening structure, overstating how much resting liquidity actually
sits at a given level.

**Status**: detection-only, matching Premium/Discount's original ship
status (decision #19) — not yet wired into `SignalEngine`. No wiring
plan exists yet in `ROADMAP.md`; unlike structure-TP (which had an
explicit dependent roadmap item), equal-highs/lows integration (e.g. as
sweep-target confirmation or additional confluence) is unscoped future
work.

## 23. Jade Entry Point Engine: a separate, parallel module built directly against an operator-supplied spec, not an extension of `entry_model.py`

**Decision**: `app.strategy.entry_point_engine.py` (operator directive,
2026-07-12, "JADE ENTRY POINT ENGINE — OFFICIAL SPECIFICATION")
implements the 5 Jade entry models as a standalone module, independent
of `entry_model.build_entry_model`/`SignalEngine` — neither of those is
modified. It reuses the same underlying detectors (`order_block.py`,
`fvg.py`, `liquidity.py`, `premium_discount.py`, `market_structure.py`)
without changing them, composed under the new spec's own rules, which
differ from `SignalEngine`'s in one deliberate way: zone mitigation
(`is_zone_mitigated`) is NOT applied here — the spec states "Repeated
FVG tests do not invalidate the setup. Only the invalidation level
invalidates the trade," directly conflicting with `SignalEngine`'s
mitigation filter.

**Why a separate module instead of extending `entry_model.py`**: the
spec itself instructs "Implement ONLY the Entry Point Engine... Do not
modify unrelated files," and its rules (e.g. no mitigation filtering,
Premium/Discount as a standing limit zone rather than a live-price
gate) are incompatible with `SignalEngine`'s existing, already-validated
behavior. Two coexisting, independently-testable implementations of
overlapping ICT concepts is the correct outcome here, not a duplication
to clean up — they encode two different, deliberately-diverging rule
sets against the same underlying detectors.

**Key judgment calls made across several operator review rounds** (full
rationale in each function's own docstring in the module):
- **Liquidity Raid (Model 2)** uses only Equal High/Equal Low
  (`detect_equal_highs`/`detect_equal_lows`) of the spec's 7 listed
  liquidity sources — the only one with an existing, unambiguous
  detector. Previous Weekly/Daily/Session High-Low and Asian/London
  High-Low are explicit `TODO`s in the docstring, deferred pending real
  session/timezone-boundary definitions this repo doesn't have (a wrong
  session boundary would silently produce a WRONG level, not a missing
  one — worth deferring rather than guessing).
- **Breaker Block (Model 5)** confidence: 5 with a matching FVG overlap,
  4 without (operator decision; the spec's own priority table only
  states the FVG-overlap tier).
- **Confidence scale**: integers 1–5, mapping the spec's ★ ratings
  directly (operator decision).
- **Premium/Discount (Model 1)**: the entry zone is a STANDING limit
  zone (Equilibrium to the matching range extreme) that is NEVER gated
  on current price — unlike Models 3–5, which require the current
  candle to already be retracing into their zone. Both were genuinely
  ambiguous readings of the spec prose; both confirmed as operator
  decisions after being flagged.
- **"Prefer Displacement-Formed Ranges" (Model 1)**: the spec's 5
  qualitative criteria (breaks structure, oversized impulse, leaves a
  valid FVG, one dominant candle rather than many small ones,
  strong-bodied) are each operationalized against a real detector or a
  disclosed-not-tuned numeric threshold (40% dominant-candle share of
  the move's range, 50% body-to-range ratio) — see
  `_displacement_strength`'s docstring for the exact mapping of each
  criterion. This is ranking-only: a move that fails to qualify never
  rejects a setup, it only fails to be PREFERRED over the existing
  most-recent-swing-range fallback.

**Status**: feature-complete against the spec as clarified across every
review round, including the explicitly-deferred liquidity sources.
34 tests (`tests/test_strategy_entry_point_engine.py`), all
real-detector integration style. Not yet wired into any live/paper
trading path — this module currently has no caller besides its own
tests, same "detection-only until a wiring decision is made deliberately"
discipline as Premium/Discount's original ship status (decision #19).

## 24. Jade Exit Point Engine: take-profit targets as a ranked list of independent structural candidates, not a single fixed-RR level

**Decision**: `app.strategy.exit_point_engine.find_exit_targets()`
computes take-profit targets for an already-valid trade
(`direction`/`entry_price`) as a RANKED LIST (`TP1`...`TPn`, nearest to
farthest), not a single price. Candidate sources, each included only
when it's a genuine forward target (strictly beyond `entry_price`):
Equal High/Equal Low (nearest liquidity pool), previous swing high/low,
the premium/discount equilibrium, and the opposite extreme of the
current premium/discount range. Same "separate, parallel module" pattern
as the Entry Point Engine (decision #23) — built independently of
`entry_model.build_entry_model`'s existing `use_structure_tp` opt-in
(which already does something similar but narrower: a SINGLE target,
"previous high/low, extend to equilibrium if farther," tied to the OLD
entry model's fixed-RR fallback design).

**Why a ranked list instead of one target**: no spec document defines
Jade's exact exit methodology (unlike the Entry Point Engine, which had
one) — per operator instruction (2026-07-12: "if any ambiguity exists,
implement the most reasonable ICT/Jade interpretation and document it
here instead of waiting for approval"), this is the chosen
interpretation. Standard ICT/SMC practice targets the NEXT liquidity
pool first (a natural TP1/partial-exit point) and a further structural
target second (TP2+/runner) — a single collapsed target throws away
information a caller (future partial-exit logic) would want. Every
valid candidate is returned rather than picking just one, deferring the
"how many tiers, what portion at each" decision to whatever consumes
this output (explicitly NOT this module's job — see its own docstring
on scope: no position-sizing/portion-split logic here, that stays Risk
Engine/`PARTIAL_TP_PORTION` territory).

**Why each target's `level` is buffered INWARD (short of the raw
liquidity level), reusing `entry_model._STOP_BUFFER`**: standard ICT
observation that price reversing exactly AT a liquidity level without
fully trading through it is common — a take-profit sitting fully at or
past the raw level routinely misses fills that a level just short of it
would have caught. This is the mirror of how `_STOP_BUFFER` already
pushes a stop-loss AWAY from its invalidation level (for the opposite
reason: to avoid being stopped out by a wick that doesn't truly
invalidate the setup) — same constant, same magnitude, opposite
direction of intent, reused rather than introducing a second
similarly-named buffer constant.

**Status**: 7 tests (`tests/test_strategy_exit_point_engine.py`),
real-detector integration style. Like the Entry Point Engine, not yet
wired into any live/paper trading path.

## 25. HTF/LTF confluence is a pure 0-3 confirmation score, never a gate, built on 3 checks reusing detectors called against the HTF series

**Decision**: `app.strategy.htf_ltf_confluence.evaluate_htf_ltf_
confluence(direction, entry_zone, htf_candles)` scores how much a real
HTF series confirms an LTF entry candidate via 3 independent checks,
each reusing an existing detector called against `htf_candles` instead
of `ltf_candles`:

1. `htf_premium_discount_alignment` -- the LTF direction isn't on the
   wrong half of the HTF premium/discount range (`calculate_premium_
   discount` on `htf_candles`).
2. `htf_pd_array_overlap` -- the LTF entry zone overlaps a real,
   direction-matching HTF Order Block or HTF FVG (`detect_order_block`/
   `detect_fair_value_gap` on `htf_candles`).
3. `htf_liquidity_draw` -- real HTF liquidity exists beyond the entry to
   draw price toward, reusing `exit_point_engine.find_exit_targets`
   directly against `htf_candles` (a non-empty target list = a real
   draw exists).

Returns a `confluence_score` (0-3, the count of checks that passed), a
per-check boolean breakdown, and a reasons list.

**Why 3 checks, these specific 3**: no spec document defines Jade's
exact HTF/LTF confluence rules (unlike the Entry Point Engine); per
operator instruction (2026-07-12: "if any ambiguity exists, implement
the most reasonable ICT/Jade interpretation and document it here
instead of waiting for approval"), these are standard ICT/SMC "does the
bigger picture agree" concepts already represented by detectors this
project already has, just called against a genuinely separate HTF
series (same discipline as `bias.py`'s existing HTF/LTF separation,
docs/strategy_spec.md section 1) -- rather than inventing new detection
logic, this module composes 3 existing detectors against a different
input. `find_exit_targets` reuse for check 3 is itself notable: an
HTF-series "is there room to run" check IS an exit-target search, just
scoped to the higher timeframe, so calling the Exit Point Engine
directly (decision #24) instead of re-deriving liquidity-draw logic
avoids a third implementation of the same concept.

**Why a score, never a reject**: same "ranking/scoring only" discipline
already established for Entry Model 1's displacement preference
(decision #23) -- this module has no basis (no spec, no backtest
evidence) for choosing a "minimum acceptable confluence" threshold, so
it reports what it found and defers any accept/reject decision entirely
to whatever consumes this output. Inventing a threshold here would be
exactly the kind of unevidenced rule this project's "evidence over
assumption" discipline (`ROADMAP.md`'s guiding principle) exists to
prevent.

**Why the LTF entry zone's MIDPOINT is used as the reference price for
check 3** (`find_exit_targets` needs a single `entry_price`, but
`entry_zone` is a range): the simplest, most defensible single
representative point for "is there room beyond this zone" without
favoring either the zone's near or far edge -- no spec or existing
convention states otherwise.

**Status**: 12 tests (`tests/test_strategy_htf_ltf_confluence.py`),
real-detector integration style. Not yet wired into any live/paper
trading path or into `find_entry_point`'s own output, same status as
the Entry/Exit Point Engines (decisions #23/#24).

## 26. Trendlines are 2-point lines through the most recent matching swing pair, not a best-fit regression through more

**Decision**: `app.strategy.trendline.detect_trendline(candles,
direction)` defines a trendline using exactly the TWO most recent
confirmed swing points of the matching type -- `"support"` connects the
last two confirmed swing lows (`find_swing_lows`), `"resistance"` the
last two confirmed swing highs (`find_swing_highs`) -- fitting an exact
line through those two points (`slope`/`intercept`), not a best-fit
(e.g. least-squares) regression through three or more touch points.
`trendline_price_at(trendline, index)` projects the line's price at any
index, including forward extrapolation past the two defining points.
`detect_trendline_break`/`detect_trendline_liquidity_sweep` mirror
`detect_choch_mss`/`detect_liquidity_sweep`'s own break/sweep mechanics
exactly, generalized from a constant horizontal level to the
trendline's projected (diagonal) price at the current candle's index.

**Why 2 points, not a best-fit line through more**: no spec document
defines Jade's exact trendline construction; per operator instruction
(2026-07-12: "if any ambiguity exists, implement the most reasonable
ICT/Jade interpretation and document it here instead of waiting for
approval"), a 2-point line is the simplest, most literal, and most
commonly taught definition ("connect the last two swing lows") --
unambiguous and deterministic given just `find_swing_lows`/
`find_swing_highs`'s existing output, with no additional parameters
(how many points, what fitting method, how to weight touches) that a
regression approach would require without any evidence to justify a
specific choice. This is the same "don't invent an unevidenced
parameter" discipline as decision #25's confluence-threshold call.

**Why the trendline is recomputed fresh from `candles` on every call,
not a persistent, evolving object**: matches this package's existing
functional, stateless-detector convention throughout (every other
detector -- `detect_order_block`, `detect_fair_value_gap`,
`calculate_premium_discount` -- takes a candle list and returns a fresh
result, with no detector maintaining state across calls). A caller
wanting to track how a trendline evolves over time (e.g. re-anchoring
after a break) recomputes it each time it needs a fresh read, the same
way every other caller in this codebase already re-runs detectors on an
updated candle window rather than mutating a persisted detector object.

**Status**: 9 tests (`tests/test_strategy_trendline.py`), real-detector
integration style. Not yet wired into any other module -- like the
Entry/Exit Point Engines and HTF/LTF confluence (decisions #23/#24/#25),
this is a standalone, independently-testable piece with no caller yet
besides its own tests.

## 27. Session/day/week liquidity: standard ICT session windows, day/week math reimplemented (not imported) to avoid an inverted layer dependency, and graceful degradation for non-`datetime` timestamps

**Decision**: `app.strategy.session_liquidity.py` closes the 5 sources
`entry_point_engine.py`'s Liquidity Raid model left as `TODO`s
(decision #23): `previous_weekly_high_low`, `previous_daily_high_low`,
`previous_session_high_low`, `asian_session_high_low`,
`london_session_high_low`. Asian = 00:00-08:00 UTC, London =
08:00-16:00 UTC (the commonly-cited ICT convention). Wired into
`_evaluate_liquidity_raid` as the first 5 sources checked, in that
priority order (highest timeframe/most significant first), falling
through to Equal High/Equal Low (the pre-existing 6th source) only if
none of the 5 produce a confirmed sweep + close-back-inside on the last
candle.

**Why these specific session windows, and why now (previously
deferred)**: no spec document defines Jade's exact session windows; per
operator instruction (2026-07-12: "if any ambiguity exists, implement
the most reasonable ICT/Jade interpretation and document it here
instead of waiting for approval"), these are standard, disclosed (not
backtest-tuned) ICT convention -- unlike the earlier deferral (decision
#23), which was about not having ANY defensible default, this round's
instruction explicitly asks for the most reasonable interpretation
rather than waiting.

**Why day/week boundary math is REIMPLEMENTED here rather than
importing `app.backtesting.backtest_engine`'s existing `_day_bounds`/
`_week_bounds`** (same UTC-day/ISO-week convention, deliberately kept
identical): `backtest_engine.py` already imports from the `strategy`
package (`SignalEngine`, etc.), so `strategy` importing FROM
`backtesting` would invert the established layer dependency direction
(backtesting depends on strategy, never the reverse elsewhere in this
codebase) for the sake of ~10 lines of date arithmetic. A small,
disclosed duplication of trivial boundary math is preferable to
introducing a new, backwards cross-layer dependency; both
implementations are named and documented as intentionally mirroring the
same convention (`TradeJournal`'s daily/weekly report boundaries, per
docs/risk_rules.md), so a future convention change would need to update
both, which is disclosed here, not hidden.

**Why the 5 session-based sources gracefully degrade (return `None` via
`entry_point_engine._session_high_low`'s try/except) rather than raise,
when `timestamp` isn't a real `datetime`**: `session_liquidity.py` is
the FIRST detector in this entire package that needs `timestamp` parsed
as a real calendar date -- every other detector only cares about candle
ORDER (index), so every hand-built candle fixture across this package's
entire test suite (34 tests in `test_strategy_entry_point_engine.py`
alone) uses plain strings (`"t0"`, etc.) for that field, since nothing
ever read it. Real production candles DO carry a real `datetime`
(`app.data.data_normalizer.normalize_candle` always produces one).
Raising on a non-`datetime` timestamp would have broken every existing
test fixture in this package the moment Liquidity Raid started checking
these 5 new sources; treating it as "source unavailable" instead keeps
every existing test passing unchanged (proven directly: all 34 pre-existing
`entry_point_engine` tests pass byte-for-byte after this wiring, with 3
new tests added specifically to prove BOTH the real-`datetime` path
(`previous_daily_low`/`previous_weekly_high` fire correctly) AND the
graceful-degradation path (string timestamps fall through to Equal
Lows, exactly as the model behaved before this round).

**Status**: 8 new tests (`tests/test_strategy_session_liquidity.py`) for
the module itself, plus 3 new tests in
`tests/test_strategy_entry_point_engine.py` proving the wiring. 330/330
backend tests passing. This closes out ALL 7 of the spec's Liquidity
Raid sources -- Entry Model 2 is now feature-complete, not just
Equal-High/Low-only.

## 28. Jade modules composed by a separate top-level function, not by merging them into `find_entry_point` itself

**Decision**: `app.strategy.jade_trade_plan.build_trade_plan(ltf_candles,
htf_candles, bias)` is a NEW, separate top-level function that calls
`find_entry_point`, `find_exit_targets`, and `evaluate_htf_ltf_
confluence` in a fixed pipeline and merges their results into one dict
-- none of the three modules it composes were modified to call each
other directly.

**Why a separate composer instead of having `find_entry_point` call the
other two itself**: `find_entry_point`, `find_exit_targets`, and
`evaluate_htf_ltf_confluence` are independently useful and independently
tested with zero coupling between them (any one can be called alone,
with only `ltf_candles`/`htf_candles`/a direction as inputs) -- folding
exit-target and HTF-confluence computation INTO `find_entry_point`
would force every caller that only wants entry detection (e.g. a future
A/B test isolating just the entry-model change) to also pay for exit-
target and HTF-confluence computation, and would require
`find_entry_point` to take an `htf_candles` parameter it has never
needed. A thin composition layer gets the "one full trade plan" call
site this system will eventually want without coupling the 3 already-
shipped, already-tested pieces to each other.

**Why `entry_price` for `find_exit_targets` is the entry zone's
MIDPOINT**: identical reasoning and identical convention to
`htf_ltf_confluence`'s own choice for the same "a zone, but this
function needs one price" mismatch (decision #25) -- deliberately kept
consistent rather than introducing a second convention for the same
underlying problem.

**Status**: 3 tests (`tests/test_strategy_jade_trade_plan.py`),
real-detector integration style, 333/333 backend tests passing. Still
NOT wired into `SignalEngine`/paper trading -- this composer completes
the DETECTION-side Jade system (entry + exit targets + HTF confluence,
all reusable independently or together), but wiring any of it into a
live/paper decision path remains a deliberate, separate step not taken
in this round, same "detection-only until a wiring decision is made
deliberately" status every Jade module has shipped with so far
(decisions #19/#23/#24/#25/#26/#27).

## 29. `build_trade_plan` computes HTF bias itself; no other Jade module does

**Decision**: `jade_trade_plan.build_trade_plan(ltf_candles,
htf_candles)` no longer takes `bias` as a parameter -- it computes bias
itself via `bias.detect_htf_bias(htf_candles)` (an existing, already-
tested detector, unmodified) and short-circuits to `None` immediately
on a `"neutral"` read, before calling any of the 3 composed modules.
Every OTHER Jade module (`find_entry_point`, `find_exit_targets`,
`evaluate_htf_ltf_confluence`) still takes `direction`/`bias` as a
caller-supplied, trusted input and is UNCHANGED by this decision.

**Why only the top-level composer computes bias, not each module
individually**: `detect_htf_bias` already existed and was already
tested before any Jade module in this series was written -- operator
directive (2026-07-12, "1. HTF Bias Engine") asked for it to be
COMPLETED as part of the Jade system, and the actual gap was that
nothing in the new pipeline called it, not that it needed to be
rebuilt. Computing it once, at the single entry point where both
`ltf_candles` AND `htf_candles` are already available together, and
threading the result down, is the same pattern `SignalEngine.
generate_signal` already uses for its own (separate, `entry_model.py`-
based) pipeline -- consistency with an established, working precedent,
rather than inventing a second bias-computation convention. Pushing
bias computation into each of the 3 lower-level modules individually
would mean each would need its own `htf_candles` parameter (only
`evaluate_htf_ltf_confluence` currently has one) and would recompute
the identical bias redundantly on every composed call.

**Status**: `test_build_trade_plan_none_on_neutral_htf_bias` added,
proving the new short-circuit; the 3 existing tests updated to the new
signature (no more explicit `bias` argument) and a real bullish-bias
HTF fixture (matching `test_strategy_signal_engine.py`'s own
`_htf_bullish_candles` shape) rather than a hardcoded string. 334/334
backend tests passing.

## 30. Session Bias reports each completed session's OWN printed direction; it does not predict one session from another

**Decision**: `app.strategy.session_bias.py` (`asian_session_bias`,
`london_session_bias`, `session_bias_agreement`) reports the directional
bias a completed session itself printed -- that session's first
candle's `open` compared to its last candle's `close` (bullish if it
closed higher, bearish if lower, neutral if unchanged). Reuses
`session_liquidity.asian_session_high_low`/`london_session_high_low`
unmodified for session-window detection (their `window_start`/
`window_end` fields are exactly what's needed to find that session's
own first/last candle). `session_bias_agreement` reports whether the
two most recently completed sessions agreed, as an observed fact.

**Why this stops at "what did the session do" and does NOT attempt
"what does session X predict for session Y"**: a genuinely common ICT
teaching is a PREDICTIVE claim (e.g. "a bullish Asian session favors
continuation/expects London to raid the Asian low before reversing
bullish") -- but that is a specific, falsifiable trading hypothesis
this project has no backtest evidence for, and per this project's
"evidence over assumption" discipline (`ROADMAP.md`'s guiding
principle, and the precedent of `break-even`/`Breaker Block`/`partial-
TP` all shipping opt-in and unproven until A/B tested — see decisions
#10/#11), inventing and shipping an unevidenced predictive rule as if
it were a settled definition would be exactly backwards. Reporting each
session's own observed bias (an objective fact readable directly from
its candles) and how the two most recent sessions relate to each other
(also an objective fact) is the part of "Session Bias" that IS a
definition, not a hypothesis -- anything predictive built on top of it
is future, separately-evidenced work, not this module's job.

**Status**: 9 tests (`tests/test_strategy_session_bias.py`),
real-`datetime` fixtures (same requirement as `session_liquidity.py`,
the only other detector needing real calendar time). 343/343 backend
tests passing. Not yet wired into `jade_trade_plan`/`SignalEngine` --
same status as every other standalone Jade module.

## 31. CRT (Candle Range Theory) takes the range candle and the checked series as two SEPARATE inputs, enabling both same-timeframe and cross-timeframe usage from one function

**Decision**: `app.strategy.crt.detect_crt(range_candle, candles)`
checks whether the LAST candle in `candles` manipulates (wicks beyond
one side of) then distributes (closes back on the originating side of)
`range_candle`'s own `[low, high]` range -- the exact same "sweep then
close back inside, a bare wick alone is never a signal" mechanic as
`detect_liquidity_sweep`/`entry_point_engine`'s Liquidity Raid model,
except the "liquidity" being swept is a single reference candle's own
range, not a swing point or session/day/week high-low.
`detect_crt_from_previous_candle(candles)` is a convenience wrapper for
the simplest same-timeframe reading (`candles[-2]` as the range
candle).

**Why `range_candle` and `candles` are two separate parameters, not one
series with an implicit "N-1 vs. N" reading baked in**: CRT is most
commonly taught ACROSS timeframes -- a single HTF (e.g. daily/weekly)
candle's range, manipulated and distributed by LTF price action within
it -- not necessarily the immediately preceding candle of the SAME
series. Taking them as independent inputs makes both readings possible
from one function (same-timeframe: pass `candles[-2]`; cross-timeframe:
pass a real HTF candle) without a second, parallel implementation for
each case. `detect_crt_from_previous_candle` exists only because the
same-timeframe case is common enough to deserve a one-line convenience
wrapper, not because the general function is somehow incomplete without
it.

**Why `target_reference` is always the OPPOSITE side of the range from
whichever side was swept**: standard CRT target -- once manipulation
sweeps one side's liquidity, price is expected to travel toward the
other side. Identical concept, identical field name, to
`entry_point_engine`'s Liquidity Raid model's own `target_reference`
("opposite side of the range" per that spec) -- kept consistent rather
than inventing new terminology for the same idea.

**Status**: 8 tests (`tests/test_strategy_crt.py`), including one
explicitly proving cross-timeframe usage (a real HTF candle as the
range, an independent LTF series as the check). 351/351 backend tests
passing. Not yet wired into `jade_trade_plan`/`SignalEngine`.

## 32. BOS chosen as "the confirmed remaining market structure detector"; implemented as a disclosed near-duplicate of `detect_choch_mss`, not a shared-code refactor

**Decision**: `market_structure.detect_bos(candles, n=2, swept_index=None)`
detects Break of Structure -- a structural break that CONFIRMS the
prevailing trend (an uptrend breaking above its own most recent swing
high, or a downtrend breaking below its own most recent swing low),
the direct mirror of `detect_choch_mss`'s reversal detection (a trend
breaking in the OPPOSITE direction). Same signature, same `swept_index`
gating, same return shape (`{"type", "broken_level", "broken_index",
"confirm_index"}`) so callers can handle either uniformly. Implemented
as its OWN self-contained function in `market_structure.py`, not
refactored to share an internal helper with `detect_choch_mss`.

**Why BOS was the confirmed gap chosen** (operator directive,
2026-07-12, "5. Remaining market structure detectors"): BOS and CHOCH
are always taught as a PAIR in ICT/SMC material -- you cannot have the
concept of "a break that signals reversal" (CHOCH) without the
complementary concept of "a break that confirms continuation" (BOS).
This codebase already had a real, tested CHOCH detector but no BOS
counterpart at all -- the clearest, most unambiguous, most clearly
"confirmed Jade methodology" gap available, unlike more speculative
candidates (internal/external structure grading, wave counting) that
would require inventing thresholds with no clear settled definition.

**Why a disclosed duplication instead of extracting shared code**:
`detect_choch_mss` is an already-shipped, heavily-relied-upon function
(used directly by `SignalEngine.generate_signal`, tested since this
project's early milestones). Refactoring it to share logic with a new
function carries real risk of a subtle regression in code every other
part of the live/paper/backtest pipeline depends on, for the sake of
avoiding ~15 lines of duplicated trend-detection logic that will not
independently drift (both functions read the exact same swing-high/
swing-low trend condition, just apply it to the opposite break
direction) -- same "small, disclosed duplication preferred over a risky
cross-cutting change to already-shipped code" judgment already applied
in `session_liquidity.py` (decision #27, day/week boundary math) and
`crt.py`'s independence from `detect_liquidity_sweep`.

**Status**: 10 new tests
(`tests/test_strategy_market_structure.py`), including one proving
`detect_bos` and `detect_choch_mss` are mutually exclusive on the exact
same real fixture (a genuine CHOCH), not just independently correct in
isolation. 357/357 backend tests passing. Not yet wired into
`SignalEngine`/`jade_trade_plan` -- `detect_choch_mss` itself remains
`SignalEngine`'s only structural-break input for now; wiring BOS in
anywhere is a separate, deliberate step.

## 33. Trendline/CRT/session-bias attached to `build_trade_plan` as purely informational context, exactly like `htf_confluence` -- none of the three can reject a trade

**Decision**: `jade_trade_plan.build_trade_plan` now attaches 3 more
fields, completing operator directive item #6 ("any remaining Jade
methodology required for signal generation"): `trendline_signal`
(`detect_trendline` in whichever direction -- `"support"`/`"resistance"`
-- matches the entry, plus `detect_trendline_break`/`detect_trendline_
liquidity_sweep` against it), `crt_signal`
(`detect_crt_from_previous_candle` on `ltf_candles`), and
`session_bias` (`session_bias_agreement` on `ltf_candles`, gracefully
`None` on non-`datetime` timestamps -- same rationale as
`entry_point_engine._session_high_low`, decision #27). None of the
three can make `build_trade_plan` return `None` -- they're attached
after `find_entry_point` has already produced a real entry candidate,
purely as additional context on top of it.

**Why purely informational, not additional entry requirements**: exact
same reasoning as `htf_confluence` (decision #25) and Entry Model 1's
displacement ranking (decision #23) -- this project has no backtest
evidence for what minimum trendline/CRT/session-bias condition should
gate an entry, and inventing one here would be exactly the kind of
unevidenced rule `ROADMAP.md`'s "evidence over assumption" principle
exists to prevent. Reporting what each detector found and deferring any
accept/reject threshold to whatever eventually consumes this output
(the same posture already established for every other Jade confluence
signal) keeps the detection layer and the (future, separately
evidenced) decision layer cleanly separated.

**Why CRT uses the SAME-timeframe reading (`detect_crt_from_previous_
candle` on `ltf_candles`) rather than a cross-timeframe one (an HTF
candle as the range)**: `build_trade_plan` already has a well-defined
role for `htf_candles` (bias + HTF confluence) and a well-defined role
for `ltf_candles` (entry/exit/trendline/CRT/session) -- using an HTF
candle as the CRT range here would mix those roles for one detector
only, without a clear reason to. The general, cross-timeframe-capable
`detect_crt` function still exists and is directly available to any
caller that wants that reading (see decision #31); this composer just
doesn't default to it.

**Status**: 2 new tests
(`tests/test_strategy_jade_trade_plan.py`), one confirming the 3 new
fields' shape/behavior on the existing real fixture (trendline found,
CRT/session-bias both correctly absent for that specific data), one
proving `crt_signal` populates correctly when the data genuinely
contains a manipulation+distribution pair. 358/358 backend tests
passing. `build_trade_plan` is now the single, complete Jade
signal-generation composer -- bias, all 5 entry models, exit targets,
HTF confluence, trendline, CRT, and session bias, all reused from their
own independently-tested modules with zero duplicated detection logic.
Still NOT wired into `SignalEngine`/paper trading.

## 34. SignalEngine.generate_signal gets a use_jade_engine opt-in flag; TradeSignal gets an additive jade_plan field -- and a real ordering bug was caught during this integration

**Decision**: `SignalEngine.generate_signal` gains `use_jade_engine:
bool = False`. When `True`, it bypasses the ENTIRE legacy pipeline
(bias/sweep/CHOCH/FVG/OB/breaker via `entry_model.build_entry_model`)
and calls `jade_trade_plan.build_trade_plan` instead, mapping the
result onto `TradeSignal`'s existing DB-mapped fields. `TradeSignal`
gains one new field, `jade_plan: dict | None = None` (additive, at the
end, with a default) -- the full Jade plan, for any caller that wants
the rich detail (`confidence_score`, ranked `exit_targets`,
`reason_list`, `htf_confluence`, `trendline_signal`, `crt_signal`,
`session_bias`) the fixed `TradeSignal` shape cannot represent. This
implements the "Recommended" option from the operator's own 3-option
framing (2026-07-12) over the two alternatives (map onto existing
fields only and silently drop the rest, or defer SignalEngine wiring
entirely).

**Why additive, not persisted**: `app.portfolio.signals.py` (confirmed
by reading it directly before this change) persists a `TradeSignal` via
EXPLICIT named-field access (`signal.symbol`, `signal.direction`, ...),
never `dataclasses.asdict()` or similar blind serialization -- so a new
field with a default is invisible to every existing consumer
(`routes_dashboard.py`, `paper_broker.py`, `safety_checks.py`,
`risk_manager.py`, `portfolio/signals.py`, all checked directly) unless
that consumer is deliberately updated to read it. Zero risk of trying
to insert an extra, non-existent column.

**Field mapping decisions**:
- `entry_price`: the entry zone's `top` (long) / `bottom` (short) --
  matching `entry_model.build_entry_model`'s own existing convention
  (the more conservative, worse-realistic-fill assumption), NOT the
  zone-midpoint convention `find_exit_targets`/`evaluate_htf_ltf_
  confluence` use internally (decision #25) for a different problem.
- `take_profit`: the NEAREST of the exit targets, RECOMPUTED against
  this specific `entry_price` (see the real bug caught below), not
  reused from `plan["exit_targets"]` as-is.
- `rr`: the REAL reward:risk implied by this entry/stop/target, not a
  fixed constant -- same discipline `use_structure_tp` already
  established for the legacy path (the Risk Engine's `MIN_RR` gate reads
  this field directly).
- `sweep_type`/`choch_detected`: always `None`/`False` on the Jade path
  -- legacy-pipeline-specific concepts with no clean Jade equivalent,
  not meaningfully wrong, just not applicable.
- `fvg_zone`: carries the Jade entry zone (`{"top", "bottom"}`) -- same
  ROLE this field already plays (the zone actually used), different
  shape (no `type`/`index`).

**A real bug was found and fixed during this integration, before it
ever shipped**: the first implementation reused `plan["exit_targets"]`
directly, which `build_trade_plan` computes against the zone's
MIDPOINT. Since `entry_price` here is the zone's TOP (further from the
zone's center than the midpoint, for a long), a target that cleared the
midpoint did not necessarily also clear this closer, more conservative
`entry_price` -- confirmed with a real fixture where the resulting
`take_profit` (100.35) landed BELOW `entry_price` (101), an inverted,
unsafe signal that would have passed the Risk Engine's `MIN_RR` check
anyway (the ratio is still a positive number even when the price
ORDERING is backwards -- `risk_manager.evaluate()` checks the ratio,
not level ordering). Fixed by recomputing `find_exit_targets(...,
entry_price=<the real one>)` fresh inside `_generate_signal_via_jade_
engine`, instead of trusting the plan's own midpoint-based list. A new
test (`test_generate_signal_use_jade_engine_produces_a_real_signal`)
asserts `stop_loss < entry_price < take_profit` explicitly so this
exact regression can never silently reappear.

**Status**: 5 new tests
(`tests/test_strategy_signal_engine.py`), plus confirmation that all
14 pre-existing `SignalEngine` tests pass byte-for-byte unchanged
(`use_jade_engine` defaults to `False`, touching nothing on the legacy
path). 363/363 backend tests passing. This is the first Jade module
actually wired into `SignalEngine` -- still NOT wired into
`BacktestEngine`/`scripts/run_paper.py` (neither passes
`use_jade_engine` through), so no backtest or paper-trading run
actually exercises this path yet without a further, separate wiring
step -- same "opt-in, unproven until exercised/evidenced" status every
new SignalEngine behavior in this project has shipped with
(`use_breaker_block`, `require_full_confluence`, etc., decision #10).

## 35. Real performance bug found and fixed while attempting the first Jade engine A/B backtest: unbounded all-pairs displacement candidates

**Decision**: `entry_point_engine._candidate_dealing_ranges` now bounds
its swing-point inputs to the most recent `_MAX_CANDIDATE_SWING_POINTS`
(10) of each type (`find_swing_highs(candles)[-10:]`/`find_swing_lows(
candles)[-10:]`), instead of every confirmed swing point across the
ENTIRE candle history.

**What happened**: attempting the first real A/B backtest of
`use_jade_engine` (operator directive, 2026-07-12) at this project's
standard scale (`--candles 3000 --periods 6 --walk-forward`), the Jade
side never completed within a 5-minute wait -- even a SINGLE 3000-candle
period alone (not all 6) still hadn't finished after 5 more minutes.
Root cause, confirmed by isolated timing tests: `_candidate_dealing_
ranges` (decision #23's displacement-ranking feature) built an
UNBOUNDED all-pairs cross join of every swing high x every swing low in
the given candle slice, and `_displacement_strength` calls
`detect_choch_mss(candles[:end_index+1])` (an `O(n)` rescan) once per
candidate. Swing-point count grows with candle count, so candidate
count grew roughly quadratically with candle count, each candidate
costing another `O(n)` CHOCH rescan -- and `BacktestEngine`'s
walk-forward loop calls this fresh at every one of `O(n)` steps with an
ever-growing candle slice. The result was effectively unbounded, not
just slow: 300 candles ran in ~1.6s, 1000 in ~2.75s, but 3000 never
finished in 5+ minutes -- a real complexity blowup, not a constant-
factor slowdown.

**Why bounding to 10 is the right fix, not just a performance
workaround**: a dealing range candidate formed thousands of candles in
the past is not a real candidate for "the CURRENT dealing range" in the
first place -- the entire concept Entry Model 1 is about. Bounding to
the most recent 10 swing points of each type is simultaneously the
performance fix (candidate count capped at 100 regardless of total
history length, bringing this step back to the same `O(n)`-per-step
complexity class every other detector in this package already has) AND
the more semantically correct behavior. No existing test's fixtures
(all small, hand-built, well under 10 swing points per type) were
affected by this bound -- confirmed by the full 363-test suite passing
unchanged before and after.

**Verified fix**: the same 3000-candle single-period case that
previously hung 5+ minutes now completes in ~37 seconds (vs. ~2-3s for
the equivalent legacy-pipeline run at that scale -- the Jade engine
evaluating all 5 entry models per step, instead of the legacy path's
one, is expected to cost more; this is a reasonable, bounded overhead,
not a runaway one).

**Status**: found and fixed BEFORE any A/B backtest results were
recorded -- this entry exists specifically so the performance
characteristics of the Jade engine are disclosed alongside its
strategy-quality findings (which follow in a later entry once the
actual A/B backtest completes), not silently absent from the record.

## 36. First real A/B result: the Jade engine underperforms the legacy pipeline badly on BTCUSDT at standard scale -- stays opt-in, default off, NOT recommended

**Decision**: `use_jade_engine=True` remains opt-in and default `False`
everywhere it was wired in (decisions #34/#35) -- this first real
backtest result does not justify changing that default, and actively
argues against ever flipping it without a fundamentally different
finding.

**The test**: `run_backtest.py --symbol BTCUSDT --candles 3000
--periods 6 --walk-forward`, this project's standard reporting scale
(same exact methodology/window as every prior A/B test in this
project), run twice on the identical fetched candle data -- once with
the existing (legacy `entry_model.build_entry_model`) pipeline, once
with `--jade-engine`.

| | Legacy (baseline) | Jade engine |
|---|---|---|
| Total trades (6 periods) | 47 | 6 |
| Profitable periods | 6/6 (100%) | 0/6 (0%) |
| Total PnL | +$1,334.17 | -$77.28 |
| Max losing streak | 0 | 6 |
| Walk-forward | **PASSED** (>=66% profitable, <=2 losing streak) | **FAILED** on both criteria |

This is not a close or mixed result: the Jade engine produced roughly
1/8th as many trades as the legacy pipeline on the identical data, was
profitable in ZERO of 6 periods (vs. all 6 for the legacy pipeline),
and lost money in aggregate where the legacy pipeline made $1,334.17.

**Plausible (not yet confirmed) explanation for the trade-count gap**:
3 of the Jade engine's 5 entry models (Order Block, Breaker Block, Fair
Value Gap) require the CURRENT (most recent) candle to already be
actively retracing INTO the zone at that exact bar
(`_last_candle_overlaps_zone`, ENGINEERING_DECISIONS.md #23) before
producing a candidate at all. The legacy pipeline's zone selection has
no equivalent same-bar timing requirement -- it accepts whichever
zone (FVG/OB/breaker) is most recent among what's currently unmitigated,
without requiring price to be touching it on this exact candle. This is
a real structural difference between the two systems worth
investigating further, but is disclosed here as a HYPOTHESIS, not a
confirmed root cause -- no isolated test was run to confirm it
specifically explains the gap.

**Why this is being recorded as a real, if early, negative finding
rather than "insufficient data, no conclusion yet"**: the gap is large
enough (0/6 vs 6/6 profitable periods, not a marginal difference) that
even a single-asset, single-window result is informative -- consistent
with how this project has always treated a first real result: reported
honestly, not dismissed for being early, but also explicitly flagged as
NOT yet cross-asset or cross-year validated (same caveat this project
applied to every one of its OWN findings before broader validation --
see decisions on break-even/Breaker Block/partial-TP, all of which
took 3-4 assets and 2 calendar years before being treated as settled).
Unlike those features, which were built ON TOP of the same core
pipeline and A/B tested as narrow, single-variable toggles, the Jade
engine REPLACES the entire pipeline -- a first bad result here is
grounds for real caution before investing further validation effort
onto it, not a false alarm to explain away.

**Recommendation**: do NOT enable `use_jade_engine` in paper trading
(`settings.USE_JADE_ENGINE` stays `False`) or backtesting by default.
If the Jade engine is revisited, the highest-value next steps (not
undertaken in this round) would be: (1) confirm or rule out the
same-bar-retracement-requirement hypothesis directly, (2) check
whether the low trade count is specific to BTCUSDT/this window or
general, (3) only then decide whether further tuning or cross-asset
validation is worth the effort, given how large this first gap is.

**Status**: 1 asset (BTCUSDT), 1 time window (2026, same 6-period/3000-
candle-per-period standard scale every prior finding in this project
used for its OWN first pass), 0 cross-asset or cross-year validation
yet. Full reports: `scripts/reports/jade_btc_period{1-6}.md`/`.csv`
alongside the baseline's own `scripts/reports/baseline_btc_period{1-6}.md`/`.csv`.

## 37. `scripts/experiment_runner.py`: one fixed-anchor fetch reused across every config, in-sample/held-out-out-of-sample split enforced structurally

**Decision** (operator directive, 2026-07-12 "AUTONOMOUS 2-HOUR
PROFITABILITY SPRINT", Phase B): built a new harness that (a) fetches LTF+HTF
candles exactly ONCE per invocation, anchored to a caller-fixed `--end-date`
(not "now"), and reuses that identical candle data across every named config
in the run, and (b) splits the resulting periods into in-sample (used for
the keep/reject decision) and a held-out tail (`--holdout-periods`, never
used to pick a candidate, only to confirm one afterward). Results append to
`scripts/reports/experiment_results.json` -- one JSON record per config per
invocation, including the exact config dict and an exact reproducing
command.

**Why a fixed anchor, not "now"**: earlier the same session, comparing the
Legacy baseline against the Jade engine required a full re-run because the
original baseline's fetch and a later comparison fetch landed a few days
apart (`--end-date` wasn't used), producing non-identical candle data for
what was meant to be an apples-to-apples comparison. A fixed anchor shared
across every config in one invocation makes that class of error structurally
impossible going forward, not just something to remember to avoid.

**Why in-sample/out-of-sample is enforced by the runner itself, not left to
the caller's discipline**: this project's controlled parameter sweep
(decision #18) already established the held-out-period discipline
manually; this runner makes it the DEFAULT behavior of the tool, so a future
caller cannot accidentally skip it the way an ad-hoc single-invocation
comparison could (see decision #38 below for a concrete example of what
skipping it costs).

**Status**: `scripts/reports/experiment_results.json`, machine-readable,
append-only. See `docs/PROFITABILITY_EXPERIMENT_REPORT.md` for the full
results table and every config tested.

## 38. `structure_tp` reproduces cleanly under rigorous methodology; an earlier same-session ad-hoc verdict on drawdown is superseded, not overturned by new evidence

**Decision**: `use_structure_tp` clears this project's three-metric keep
rule (Net Profit AND Profit Factor AND worst-period Drawdown all improve
over baseline) under decision #37's fixed-anchor, in-sample/out-of-sample
methodology -- Net Profit $753.32 -> $2,731.46, Profit Factor 2.81 -> 6.29,
worst-period drawdown 1.16% -> 1.14% (slightly BETTER, not worse),
walk-forward PASSED at 5/5 profitable periods with 0 losing streak, and
**confirmed on the held-out out-of-sample period** ($611.01, 66.7% win
rate, PF 5.77) -- never touched during the decision. This does NOT flip
any production default (see decision #10's discipline, unchanged); it is
evidence toward a future decision, gated on cross-asset/cross-year
validation per decisions #14/#15's standing bar.

**Why this appears to contradict an earlier finding from the SAME
session**: an ad-hoc comparison earlier that session (no fixed `--end-date`,
all 6 periods combined, no held-out split) found `structure_tp`'s
worst-period drawdown (1.17%) WORSE than baseline's (0.77%) and rejected it
on that basis. Both numbers are real, reproducible, and now recorded (the
ad-hoc one in this session's own tool-call history and prior chat turns,
the rigorous one in `scripts/reports/experiment_results.json`). The
discrepancy traces to exactly where period boundaries fell: a few hours'
difference in fetch anchor between the two ad-hoc runs moved which candles
landed in which period, changing which period showed the worst drawdown --
the SAME mechanism decision #18 already documented for BTCUSDT 2025's
standard-scale degradation check. This is not "the earlier number was
wrong" -- it's that period-boundary sensitivity is real and a less
disciplined methodology (no fixed anchor, no confirmed-out-of-sample check)
is not a reliable basis for a keep/reject call. The rigorous, fixed-anchor,
out-of-sample-confirmed result in this entry supersedes the earlier one.

**Diagnosis (separating entry edge / sizing / target distance / duration)**:
`use_structure_tp` provably only changes `take_profit`/`rr` -- zone/entry/
stop selection is byte-identical to the default path (verified directly
from `entry_model.py`'s code, decision context in
`docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 8). Position sizing is
therefore also identical (same formula, same entry/stop distance). Average
R per trade jumped 0.78 -> 2.95 -- the entire Net Profit/PF improvement is
a target-distance effect: wins run much farther, at the cost of a lower hit
rate (68.6% -> 60.6%). The `structure_tp_capped_3r` variant (decision #39)
isolates drawdown specifically: capping the target's implied R at 3.0 cuts
average R back to 1.14 and roughly halves Net Profit, but worst-period
drawdown is UNCHANGED (1.14% either way) -- meaning target distance drives
profit here but is NOT what's driving drawdown; drawdown appears to be set
by which specific trades/periods lose, independent of how far winners run.
This refines the sprint's own initial framing ("~3x profit but failed the
drawdown rule") -- under rigorous measurement, profit and drawdown did not
trade off against each other the way that framing assumed.

**Status**: 1 asset (BTCUSDT), 1 fixed time window, 5 in-sample + 1
out-of-sample period. Cross-asset/cross-year validation is the explicit
next step (not undertaken this round) before any default-flip discussion --
see `docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 10.

## 39. `structure_tp_max_r`: a bounded target-distance cap, additive to `use_structure_tp`, not a new trading concept

**Decision**: `entry_model.build_entry_model` gains `structure_tp_max_r:
float | None = None` (opt-in, zero effect unless both `use_structure_tp=True`
AND this is explicitly set). When the uncapped structure target's implied
reward:risk exceeds the given ceiling, `take_profit` is clamped back toward
`entry_price` at exactly that R multiple -- entry/zone/stop_loss selection
is completely untouched, so this can only ever make a trade's target
NEARER than the uncapped version would have chosen, never farther or
different in kind. Threaded through the same 4-layer path as every other
Legacy-pipeline flag (`entry_model.build_entry_model` ->
`signal_engine.generate_signal` -> `BacktestEngine.run()` ->
`run_backtest.run_backtest()`), matching decision #10's established
pattern exactly.

**Why this is not "inventing a new trading concept"** (explicit sprint
scope-lock constraint): it is a bounded version of an already-implemented,
already-shipped target (`use_structure_tp`, decision #19-context), built
specifically to answer this sprint's own Phase D #5 request ("test whether
a conservative risk or exit treatment can reduce drawdown without changing
the entry strategy") -- see decision #38's diagnosis section for what
running it revealed (drawdown did not move; only profit did).

**Status**: 3 new unit tests (`tests/test_strategy_entry_model.py`) -- cap
applies and clamps correctly, cap is a no-op when the uncapped target is
already under the ceiling, cap has zero effect when `use_structure_tp=False`.
81 pre-existing tests across the touched files (`test_strategy_entry_model.py`,
`test_strategy_signal_engine.py`, `test_backtest_engine.py`) pass unchanged
(one test fixture, `_FakeSignalEngineFixedSignal` in
`test_backtest_engine.py`, needed a new optional parameter added to its
stub signature -- not a behavior change). Not wired into any CLI flag or
paper trading yet -- available only via `scripts/experiment_runner.py`'s
`structure_tp_capped_3r` config pending a decision on broader exposure.

## 40. Paper-trading observability gaps closed additively, without touching the already-running process

**Decision** (2026-07-12 profitability sprint, Phase E): audited
`app.database.models`/`app.portfolio.trades`/`app.portfolio.signals`
against the sprint's required observability field list and found 4 real
gaps -- `Signal.rejection_reason`, `Trade.exit_reason`, `Trade.r_multiple`,
`Trade.strategy_config` were all computable in-process at the moment of the
decision (e.g. `risk_decision.reasons`, `exit_info["reason"]`) but never
persisted, visible only in that process's own stdout/alert at the moment it
happened. All 4 added as new NULLABLE columns, with `TradeTracker.close_trade`/
`record_trade` and `SignalTracker.update_signal_status` gaining new OPTIONAL
parameters (default `None`, backward compatible with every existing
caller). `scripts/run_paper.py`'s 3 relevant call sites updated to actually
populate them going forward.

**Why this is safe against the CURRENTLY RUNNING paper-trading process**
(started 19:29:11, before this change): Python does not hot-reload already-
imported modules -- the running process's `Trade`/`Signal`/`TradeTracker`/
`SignalTracker` classes are the OLD in-memory definitions it loaded at
start, matching the OLD `paper_validation.db` schema on disk exactly. This
change only edits source files on disk; the running process never re-reads
them. `paper_validation.db` itself was never touched (no migration run
against it) -- verified by smoke-testing the new columns against a
separate, throwaway sqlite DB instead. The improvements take effect the
next time `run_paper.py` is started fresh, not on the currently running
instance -- consistent with the sprint's explicit "do not restart the
running production paper trader unless it is genuinely broken" instruction.

**Real gap found while wiring this in**: `models.py` is NOT this project's
actual schema source of truth for tests/production -- `app/database/
migrations/` (Alembic) is; the test suite bootstraps its DB via `alembic
upgrade head`, not `Base.metadata.create_all()` directly. Editing
`models.py` alone left the 4 new columns entirely absent from every test
DB, failing 27 tests with `no column named exit_reason` until migration
`393afdf7fe67` (chained after the existing head `4b8a822a475b`) was added
alongside it. `tests/test_db_bootstrap.py`'s pinned-migration-head
assertion was updated to match (a self-documenting pattern the test itself
already called out: "update this alongside adding any new migration").

**Status**: smoke-tested end-to-end (record/close a trade with
`exit_reason`/`r_multiple`/`strategy_config`, record/reject a signal with
`reason`) against a throwaway DB, all fields round-trip correctly. Full
backend test suite: 366/366 passing (363 pre-existing + 3 new
`structure_tp_max_r` tests, decision #39).

## 41. Cross-asset candidate promotion is asset-specific, not a single verdict -- and a ranking score needs a trustworthiness gate in front of it, not folded into it

**Decision** (operator directive, 2026-07-13: "keep Legacy as the engine,
don't force one strategy onto every asset, optimize BTC/ETH/SOL
independently, rank by Net Profit/PF/Max Drawdown/Sharpe not win rate,
keep generating and auto-backtesting candidates without approval"):
`use_structure_tp` is promoted to documented CANDIDATE status (explicitly
NOT a production default -- see decision #10's unchanged discipline) for
BTC and SOL only, on their own independent evidence. XRP and ETH get NO
candidate. This is 3 different per-asset outcomes from testing the SAME
feature family, not one project-wide verdict -- directly implementing the
operator's "don't force one strategy onto every asset" instruction as a
structural property of the result, not just a framing choice.

**Ranking key redesigned around 4 metrics, with 2 gates kept in front of
it**: `experiment_runner.evaluate_candidate`'s `rank_key` now sorts by Net
Profit / Profit Factor / (negative) Max Drawdown / Sharpe, per the
operator's explicit instruction to rank by these and not win rate.
Walk-forward-pass and out-of-sample-profitability remain separate GATES
evaluated before the score, not merged into it.

**Why gates instead of folding everything into one score**: the operator
also instructed continuous, unattended candidate generation ("계속 생성하고
자동 백테스트해서... 사람 승인 없이 자동으로 계속 실험해라"). An unattended
loop that ranks purely by in-sample Net Profit/PF/DD/Sharpe with no
trustworthiness filter would, given enough candidates, eventually surface
one that curve-fits the specific in-sample periods tested -- exactly the
multiple-comparisons/p-hacking risk this project's entire methodology
(ENGINEERING_DECISIONS.md #8/#14/#15/#18, the Phase 1 scope lock's
"never optimize solely for in-sample Net Profit") exists to prevent.
Gating on walk-forward pass + confirmed out-of-sample profitability BEFORE
ranking means the score only ever orders candidates that have already
cleared a held-out check -- the operator's ranking instruction is honored
exactly as stated, just with the trustworthiness check kept structurally
prior to it rather than mixed into the same tuple.

**ETH's rejection is reproducible, not tunable away**: 5 configs tested at
the 2026-07-12 anchor (uncapped `structure_tp` + 4 `structure_tp_max_r`
values + 1 combo) ALL fail walk-forward with the byte-identical signature
(`profitable_ratio=0.80, max_losing_streak=1, degrading=True`) the Legacy
baseline itself produces in that same window -- confirming this is a
regime characteristic of the underlying price data in this window, not a
property of any specific `structure_tp` variant. A second, independent
2025-07-12 anchor also rejects (different failure mode: a real drawdown
regression, 0.37%->1.48%). Two independent windows, both negative, is
treated as this round's real, final answer for ETH -- continuing to
generate ETH-targeted variants would mean searching for a parameter
combination that happens to dodge these two specific windows' behavior,
which is curve-fitting by definition, not the "find a profitable
strategy" objective the operator stated.

**BTC's cap-value sweep shows the cap has a real optimum, not "smaller is
always safer"**: `structure_tp_capped_2r` (the tightest cap tested)
actually REJECTS on BTC -- Net Profit falls to $946 (below baseline's
$1,149) even as drawdown improves to 0.45%. 2.5R-4.0R all KEEP. This
confirms decision #38's diagnosis empirically: capping too aggressively
just removes the source of profit (structure_tp's larger average R) without
a large enough drawdown benefit to compensate near the tight end.

**XRP's near-miss, disclosed not discarded**: `structure_tp_capped_3r`
ties (not beats) baseline's worst-period drawdown exactly (0.7826% both,
to 4 decimal places) while still improving Net Profit and Profit Factor.
The keep rule requires strict improvement (`<`), so this rejects --
correctly, per the rule as stated -- but a tie is a materially different,
more favorable result than a regression, and is recorded as a candidate
worth revisiting if the tie rule is ever relaxed to `<=` (an operator
decision, not made unilaterally here).

**Status**: 38 records in `scripts/reports/experiment_results.json`
across BTC/ETH/SOL/XRP, 2 time windows on ETH. Full table:
`docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 12. A real race
condition in the shared JSON ledger (3 parallel asset runs earlier this
session, no file lock) was found and fixed with a portable mutex before
this round's parallel runs -- see that file's `_acquire_ledger_lock`.

**Follow-up (2026-07-13/14, same-day continuous optimization round)**:
`rank_key` was updated a second time per an explicit follow-up operator
instruction ("rank every candidate by out-of-sample robustness") to lead
with out-of-sample Profit Factor/Net Profit, falling back to in-sample
Net Profit/PF/DD/Sharpe only as tie-breakers -- the gates (walk-forward
pass, out-of-sample profitable) are unchanged and still evaluated first.
Two results from applying this: (1) XRP's near-miss from this decision's
first version was independently reconfirmed via a completely different
lever -- `premium_discount_filter` (an ENTRY-side change) produces the
exact same 0.7826% worst-period drawdown as every `structure_tp_max_r`
(EXIT-side) variant already tested, strong evidence this is an
irreducible property of the underlying price data in this window, not a
configuration gap; further XRP search was stopped as genuinely redundant,
not merely paused. (2) SOL's candidate was upgraded: the SOL analogue of
BTC's `structure_tp_capped_3r_and_premium_discount_filter` combo (untested
until this round) has a materially better risk-adjusted profile than
plain `structure_tp` (drawdown 1.11%->0.75%, a real improvement not a
tie; Sharpe 0.76->1.08; out-of-sample PF infinite, zero losing trades)
despite lower raw in-sample profit ($2,238.66 vs $4,292.03) -- promoted as
the new SOL candidate specifically because the operator's instruction was
to rank/promote by robustness, not by the single highest raw number.

## 42. `entry_delay_candles`: a real backtest-fidelity gap closed, and the first robustness test it enabled found a material, not cosmetic, failure

**Decision**: `BacktestEngine.run()` gains `entry_delay_candles: int = 0`
(opt-in, zero effect unless set). When `> 0`, the actual fill price
shifts to `i + entry_delay_candles`'s own close instead of the signal's
originally-planned structural `entry_price` -- everything else (stop_loss/
take_profit levels, position sizing, which both happen against the
ORIGINAL planned entry/stop) stays unchanged. Implemented via
`copy.copy(signal)` + attribute overwrite rather than `dataclasses.
replace()` specifically so it works against ANY signal-shaped object
(including this project's plain, non-dataclass test fakes), not just the
real `TradeSignal` dataclass.

**Why this gap existed and mattered**: every backtest this entire project
has ever run (`run_backtest()`, `experiment_runner.py`, `parameter_sweep.py`,
all of it) has silently assumed a signal fills INSTANTLY at its planned
structural price -- zero network/exchange/dispatch latency. This is not
how real paper/live trading works (`scripts/run_paper.py` polls on a
fixed interval and then still has to place/confirm an order). No test in
this project's history had ever quantified how much that zero-latency
assumption was worth.

**First real use, operator-directed 2026-07-14 robustness validation**:
tested against the BTC production candidate
(`use_structure_tp=True, structure_tp_max_r=3.0,
require_premium_discount_filter=True`) at delays of 0/1/2/3 candles (5m
timeframe, so 0/5/10/15 minutes). Result: Profit Factor collapses from
5.24 (no delay) to 0.16 at just ONE candle of delay (a full sign
reversal, not a graceful degradation) and stays there at 2-3 candles.
Root cause identified mechanistically, not just observed: this
candidate's average stop distance is 0.23% of entry price (the
`structure_tp_max_r`/`premium_discount_filter` combination that won
sections 12-14's validation produces very tight structural stops) --
ordinary 5-minute price movement can be comparable to or exceed that
distance, so a delayed fill routinely lands already invalidated relative
to the risk math the position was sized against.

**Why this is treated as a material robustness failure, not just another
disclosed sensitivity** (contrast with the SAME test round's slippage/fee
stress results, which degrade gracefully and only fail at unrealistic
extremes -- `docs/ROBUSTNESS_REPORT.md` tests 3/4): a sign-reversing
collapse from the SHORTEST delay tested is qualitatively different from a
gradual erosion -- it means the entire backtested edge is conditional on
an assumption (zero latency) that cannot be guaranteed in any real
deployment, paper or live. Per the operator's own explicit decision rule
for this round ("only reject if robustness materially fails"), the
candidate is NOT promoted as deployable-as-is.

**Status**: 2 new unit tests (`tests/test_backtest_engine.py`) --
delayed fill uses the later candle's close (not the original signal
entry_price) with sizing unaffected, and `entry_delay_candles=0` is
byte-for-byte identical to omitting the parameter. `scripts/run_backtest.py`'s
wrapper also gained caller-overridable `fee_percent`/`slippage_percent`/
`account_balance` (previously hardcoded) for the same round's fee/
slippage stress tests. 368/368 backend tests passing. Full 7-part
robustness suite: `scripts/robustness_report.py`,
`scripts/reports/robustness_report.json`,
`docs/ROBUSTNESS_REPORT.md`.

## 43. Strategy Interface is a `Protocol`, adapters wrap `SignalEngine` rather than reimplementing pipeline selection

**Decision** (operator directive, 2026-07-15, adaptive-platform pivot --
`docs/ADAPTIVE_ARCHITECTURE.md` section 3): `app.strategy.strategy_interface`
defines `Strategy` as a `@runtime_checkable Protocol` (`name: str`,
`generate_signal(symbol, ltf_candles, htf_candles) -> TradeSignal | None`),
with two adapters -- `LegacyStrategy` (Strategy A) and `JadeStrategy`
(Strategy B) -- plus an `AVAILABLE_STRATEGIES: dict[str, Strategy]`
registry.

**Why `Protocol`, not an ABC**: neither `entry_model.build_entry_model`
(Legacy) nor `jade_trade_plan.build_trade_plan` (Jade) were designed
around a shared base class -- both are free functions with different
internal composition. A `Protocol` (structural typing) lets both conform
via a thin wrapper without restructuring either's actual implementation,
consistent with this project's long-standing "wrap, don't modify"
discipline for anything already shipped and tested.

**Why adapters delegate to `SignalEngine` instead of calling
`build_entry_model`/`build_trade_plan` directly**: `SignalEngine.
generate_signal(..., use_jade_engine=...)` is the ALREADY-EXISTING,
ALREADY-TESTED integration point (`ENGINEERING_DECISIONS.md` #34) that
handles bias/sweep/CHOCH/FVG/order-block orchestration for Legacy and the
full Jade composition for Jade. Reimplementing that orchestration inside
the adapter would duplicate real logic and create a second place for it
to drift out of sync. The adapter's entire job is translation (uniform
interface in, `TradeSignal | None` out), not detection -- proven directly
by 2 of the 7 new tests asserting the adapter's output is BYTE-IDENTICAL
to calling `SignalEngine` directly with the matching `use_jade_engine`
value.

**Why the registry is a plain `dict`, not a class**: the Strategy
Selection Engine (`docs/ADAPTIVE_ARCHITECTURE.md` section 4, not yet
built) is what will decide WHICH registered strategy to invoke per
market regime -- the registry itself only needs to answer "what strategy
modules exist and conform to the interface," which a dict answers
without inventing selection logic prematurely.

**Production impact**: none. `scripts/run_paper.py` still calls
`SignalEngine().generate_signal(...)` directly, unchanged -- this module
has no callers yet outside its own tests. Legacy's live behavior is
provably unaffected (same delegation-equivalence tests above).

**Status**: 7 new tests (`tests/test_strategy_interface.py`) -- protocol
conformance for both adapters, `.name` values, delegation-equivalence for
both, and registry completeness/conformance. 387/387 backend tests
passing.

## 44. Performance Database extended for the adaptive platform: 6 new `Trade` columns + a new snapshot table, additive and unpopulated until their producers exist

**Decision** (operator directive, 2026-07-15, adaptive-platform pivot --
`docs/ADAPTIVE_ARCHITECTURE.md` section 6): `Trade` gains 6 nullable
columns (`market_regime` JSON, `strategy_name` indexed String,
`holding_time_seconds`, `max_adverse_excursion`, `max_favorable_excursion`,
`latency_ms`) and a new `strategy_performance_snapshots` table (rolling
win-rate/profit-factor/expectancy/max-drawdown/Sharpe/Sortino/recovery-
factor per strategy, optionally per regime, plus an `is_disabled`/
`disabled_reason` pair). Migration `e3110e6a6b59`, chained after
`393afdf7fe67`.

**Why these columns now, before the components that populate them
exist**: same reasoning as decision #40's observability columns --
adding the schema is cheap and safe (nullable, no behavior change,
verified via a throwaway-DB smoke test, same discipline as #40), and
every day this is delayed is a day of lost future backfill potential
once the Regime Detector (section 2, not yet built) and MAE/MFE/latency
tracking (section 6.2, requires touching `run_paper.py`'s open-position
loop, milestone 5) actually exist. The columns exist now; they will
simply stay NULL until their producers are built, exactly like
`exit_reason`/`r_multiple`/`strategy_config` did between their own
schema-addition (#40) and `run_paper.py` actually being updated to
populate them.

**Why a snapshot table instead of computing rolling metrics live on every
read**: rolling metrics need a consistent, replayable definition of "the
window" (e.g. last 30 trades, or last 30 days). Computing them fresh on
every read risks two call sites (e.g. the Strategy Selector vs. a
dashboard) disagreeing about what "current" means at slightly different
moments. A snapshot table makes each evaluation a discrete, timestamped,
auditable event -- the same "don't fabricate an answer, show your work"
principle this project's detectors already follow (every existing
detector returns its reasoning, not just a label), applied to
performance evaluation instead of signal detection.

**Why `market_regime` on `StrategyPerformanceSnapshot` is a plain String,
while `market_regime` on `Trade` is the full JSON classification**:
`Trade.market_regime` needs to preserve the COMPLETE audit trail (trend +
volatility + event flags + raw metrics, section 2.4's design) for a
single trade's own record. `StrategyPerformanceSnapshot.market_regime` is
a GROUPING KEY (which regime bucket this rollup covers, or NULL for an
all-regime aggregate) -- a simple indexed string is the right shape for
"group by," not the full classification object.

**Status**: schema-only this round -- no code yet populates any of the 6
new `Trade` columns or writes to the new table in production paths
(`scripts/run_paper.py` unchanged). Smoke-tested end-to-end (write/read
all 6 columns + insert a snapshot row) against a throwaway DB, same
verification method as decision #40. `tests/test_db_bootstrap.py`
updated: pinned migration head (`e3110e6a6b59`) and `EXPECTED_TABLES`
(added `strategy_performance_snapshots`). 387/387 backend tests passing.

## 45. Market Regime Detector: composite output (trend x volatility x independent event flags), percentile-relative volatility, disclosed-not-tuned thresholds

**Decision** (operator directive, 2026-07-15, adaptive-platform pivot --
`docs/ADAPTIVE_ARCHITECTURE.md` section 2): `app.regime.regime_detector.
detect_market_regime(candles) -> MarketRegime | None` classifies market
state as a COMPOSITE (`trend`: one of `strong_trend`/`weak_trend`/`range`;
`volatility`: one of `high_volatility`/`normal_volatility`/`low_volatility`;
plus 3 independent boolean event flags: `breakout`, `mean_reversion`,
`liquidity_sweep_environment`) rather than one flat label, with every
classification carrying its own `metrics` dict of raw values for audit.

**Why composite, not one flat label**: the operator's own list (Strong
Trend / Weak Trend / Range / High Volatility / Low Volatility / Breakout
/ Mean Reversion / Liquidity Sweep Environment) mixes states that are
naturally mutually exclusive (a market can't be both "Strong Trend" and
"Range") with states that genuinely co-occur (a "Strong Trend" can also
be "High Volatility"; a "Breakout" is a moment-in-time event that can
happen inside either a trend or a range). Forcing all eight into one flat
label would either lose real information or require an arbitrary,
unevidenced priority order.

**Why volatility classification is PERCENTILE-relative, not an absolute
threshold**: `volatility_percentile()` ranks the CURRENT realized
volatility against its own rolling history (default 100-reading window),
not against a fixed number -- the same classification logic then works
identically across BTC, a lower-volatility asset, or a genuinely
different regime for the SAME asset, without per-asset hardcoded
constants. Same reasoning `entry_model.py`'s R-multiple-based sizing
already uses (relative to the trade's own risk, not an absolute dollar
figure) applied to a new problem.

**Why `strong_trend` requires BOTH high ADX AND coherent swing
structure**: ADX alone can be driven by one violent, structurally
incoherent move. `swing_trend_direction()` (reusing `find_swing_highs`/
`find_swing_lows` unmodified) independently confirms the last 2 swing
highs AND the last 2 swing lows are both moving the same direction (a
real HH+HL or LH+LL pattern) before ADX >= 25 is allowed to classify as
`strong_trend` -- ADX >= 25 with incoherent structure degrades to
`weak_trend` instead.

**Why `mean_reversion` and `strong_trend` are mutually exclusive by
construction** (`detect_market_regime`'s `mean_reversion = is_mean_reversion(...)
and trend != "strong_trend"`): an extreme distance-from-MA reading during
a genuine strong trend is a continuation signal, not a reversion setup --
conflating the two would misclassify trend continuation as a reversal
opportunity.

**Why ADX/moving-average/VWAP are new code but not "new indicators" in
the sense the operator's "do not invent new indicators" instruction
means**: all three are standard, textbook technical-analysis measures
explicitly NAMED in the operator's own feature list -- the instruction's
intent (read in context of the whole adaptive-platform directive) is "do
not invent new PATTERN-RECOGNITION/trading concepts," not "do not write
any new calculation at all." Every existing detector this project has
ever shipped (FVG, order block, CHOCH, premium/discount) was also "new
code" the first time it was written; ADX/MA/VWAP are held to the exact
same standard (standard, disclosed, tested), not a stricter one.

**Disclosed limitation**: OKX's public candle endpoint returns TOTAL
volume per candle, not a buy/sell split -- a true "Volume Delta" (named
in the operator's feature list) would need tick-level trade data, a
genuinely different, currently-unused market-data source. Not silently
assumed available; deferred until/unless tick data is added as a new
Market Data source (section 1 of the architecture doc).

**Disclosed simplification**: `average_directional_index`'s final
DX->ADX step is a plain trailing average of the last `lookback` DX
values, not Wilder's own exact recursive smoothing formula for that
specific step -- a reasonable, standard approximation, not textbook-exact
Wilder smoothing end to end. Flagged in the function's own docstring, not
hidden.

**Status**: 20 new tests (`tests/test_regime_detector.py`) covering every
helper function (SMA, distance-from-MA, VWAP, realized volatility, swing
trend direction, breakout with/without volume confirmation, liquidity
sweep counting, ADX minimum-history and relative-magnitude checks, mean
reversion) plus integration tests for `detect_market_regime` itself.
407/407 backend tests passing. Not yet wired into any live/paper trading
path or into the Strategy Selection Engine (`docs/ADAPTIVE_ARCHITECTURE.md`
section 4, milestone 4, not yet built) -- same "detection-only until a
wiring decision is made deliberately" status this project has used for
every new detector since decision #19.

## 46. Strategy Selection Engine ships as `DefaultToLegacySelector` -- selects `legacy` unconditionally, on principle, not as a placeholder to revisit soon

**Decision** (operator directive, 2026-07-15, adaptive-platform pivot --
`docs/ADAPTIVE_ARCHITECTURE.md` section 4): `app.strategy.selector.
StrategySelector` is a `@runtime_checkable Protocol` with one method,
`select(regime, available) -> Strategy`. Its only implementation,
`DefaultToLegacySelector`, ignores `regime` entirely and always returns
`available["legacy"]`.

**Why this is deliberately the least interesting possible
implementation, not an oversight**: no regime-tagged trade history exists
yet -- the Performance Database extensions (decision #44) added the
columns/table to start COLLECTING that evidence, but zero rows have been
written by any producer yet. Inventing a `"strong_trend" -> jade`-style
rule table now would be exactly the "evidence over assumption" violation
this project's entire discipline (decisions #10, #14, #15, #17-#18, #20)
exists to prevent, applied at the architecture level instead of the
parameter level. `docs/ADAPTIVE_ARCHITECTURE.md` section 4.3 explicitly
names the evolution path (a `RollingPerformanceSelector` choosing argmax
strategy by rolling expectancy per regime, gated on this project's
established 20+ trade confidence floor, `experiment_runner.
MIN_TRADES_FOR_CONFIDENCE`) as future work sequenced AFTER real data
exists, not built speculatively now.

**Why `regime` is typed `MarketRegime | None`, not `MarketRegime`, unlike
the doc's section 4.1 signature**: `detect_market_regime()` (decision
#45) returns `None` below its minimum candle-history floor -- a real,
already-existing case the selector's caller will hit (e.g. early in a
freshly-started paper session before enough candles have accumulated).
Typing `select()` to accept `None` and handling it identically to any
other regime (still returns `legacy`) is more honest than a signature
that implies a regime is always available when the upstream detector's
own contract says otherwise.

**Practical consequence**: turning this system on changes NOTHING about
production behavior today -- every call still resolves to `legacy`,
satisfying "keep Legacy unchanged as the production baseline" literally.
Its value is structural: every downstream stage (Risk Engine, Execution,
Performance Evaluation, Continuous Learning) now has a real Strategy
Selection stage to integrate against once milestone 5's MAE/MFE/latency
tracking and milestone 6's rolling metrics start producing the evidence
`RollingPerformanceSelector` will need.

**Status**: 4 tests (`tests/test_strategy_selector.py`) -- protocol
conformance, regime-invariance across all 3 trend states, `None`-regime
handling, and confirming the selector ignores which strategies happen to
be available (still picks by key, not by inspecting the registry).
411/411 backend tests passing. Not yet wired into any live/paper trading
path -- `scripts/run_paper.py` still calls `SignalEngine` directly, same
as before this milestone.

## 47. MAE/MFE/latency tracking wired into paper trading as running maximums in R-multiples and per-pass wall-clock measurement, scoped narrowly to milestone 5's own title

**Decision** (operator directive, 2026-07-15, adaptive-platform pivot --
`docs/ADAPTIVE_ARCHITECTURE.md` section 7, milestone 5): `scripts/
run_paper.py` now populates 3 of the 6 Trade columns milestone 2 added
(decision #44) -- `max_adverse_excursion`, `max_favorable_excursion`,
`holding_time_seconds`, plus `latency_ms` -- via two new `TradeTracker`
methods (`app.portfolio.trades`): `update_excursion(trade_id,
current_price)` and `close_trade`'s new optional `holding_time_seconds`
param.

**Why MAE/MFE are R-multiples of the trade's ORIGINAL risk distance, not
raw price units**: matches the convention `r_multiple` already uses at
close (`_check_and_close_open_positions`) -- a price-unit excursion is
meaningless across different assets/price scales, but an R-multiple is
directly comparable trade-to-trade and asset-to-asset, which is exactly
what milestone 6's rolling per-strategy/per-regime metrics (the reason
this data is being collected at all) will need to aggregate over.

**Why running maximums, updated every pass, rather than computed once at
close**: this is the standard MAE/MFE definition -- the worst/best
unrealized excursion seen AT ANY POINT while the trade was open, which
by construction cannot be reconstructed after the fact from only
entry/exit prices. Paper trading's own poll-loop structure (one pass per
interval, already fetching a fresh price every pass for the exit-check
step) is the only place in this codebase this can be measured honestly;
`BacktestEngine` does not currently compute it at all (no equivalent
per-candle running-max instrumentation exists there yet -- out of scope
here, since the operator's milestone list scoped this to "paper
trading").

**Why `update_excursion` no-ops instead of raising** (unlike
`close_trade`/`update_stop_loss`): this is pure observability metadata,
not a capital-affecting action -- a stale/missing trade id or an
already-closed trade encountered mid-pass (e.g. closed by the exit-check
step earlier in the SAME pass) should not abort the rest of `run_once`'s
pipeline the way a broken stop-loss update legitimately should.

**Why `latency_ms` measures the paper-execution ENGINE's own call
duration, not real exchange order latency**: `PaperBroker.execute()`
never makes a real exchange API round-trip (it's a local fill
simulation), so there is no real network/exchange latency for this
codebase to observe yet. Measuring `time.monotonic()` around the
`ExecutionEngine().execute()` call is an honest, disclosed measurement
of what actually happens (Python call + in-memory fill logic), not a
fabricated stand-in for a number this pipeline has no way to produce --
same "disclosed limitation, not silently assumed" discipline as decision
#45's OKX volume-delta gap. If/when a real exchange order path exists
(`app.execution.live_broker`, currently unused -- see the Milestone-1
safety guard at the top of `run_paper.py`), this measurement point would
need to move to wrap the real API call instead.

**Scope discipline**: `market_regime` and `strategy_name` (the other 2
of milestone 2's 6 new columns) are deliberately NOT populated by this
milestone, even though both would be cheap to add (the regime detector
and `settings.USE_JADE_ENGINE` are both already available at the call
site) -- `docs/ADAPTIVE_ARCHITECTURE.md`'s milestone 5 row names only
"MAE/MFE/latency tracking." Per decision #20's precedent (treating an
explicit operator priority list as the scope boundary, not a floor),
adding those two now would be scope creep against the stated milestone
title, not extra rigor -- they remain natural, low-cost additions for
whichever future milestone actually needs them populated (most likely
milestone 6, or whenever the Strategy Selection Engine, milestone 4,
starts being called instead of `SignalEngine` directly).

**Status**: 6 new tests (`tests/test_portfolio.py`) -- `close_trade`'s
new `holding_time_seconds` param, `record_trade`'s new `latency_ms`
field, `update_excursion`'s running-max behavior (favorable and adverse,
long and short direction, monotonic non-decreasing), and its safe-no-op
contract on a closed/unknown trade id. `scripts/run_paper.py` itself has
no dedicated test file (true before this change too -- it's exercised
via real paper-trading runs, not pytest); its new logic
(`_update_excursion_tracking`, the `holding_time_seconds` computation in
`_check_and_close_open_positions`, the `latency_ms` timing around
`ExecutionEngine().execute()`) was verified via `py_compile` and the
full 416/416 backend suite (all `app.portfolio.trades` call sites
covered). Editing `run_paper.py` does not affect the already-running
paper-trading process (PID 24616, Python has no hot-reload) -- confirmed
still running throughout, untouched, and this change takes effect only
on its next restart (not performed as part of this milestone, per
standing "never restart anything currently running" instruction).
