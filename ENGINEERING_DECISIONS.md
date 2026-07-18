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

## 48. Rolling performance snapshots: R-multiple-based metrics with disclosed finite-value sentinels instead of null/inf, plus a scope reversal on `strategy_name` and two real bugs caught by writing the first real producer for a schema-only table

**Decision** (operator directive, 2026-07-15, adaptive-platform pivot --
`docs/ADAPTIVE_ARCHITECTURE.md` section 7, milestone 6):
`app.portfolio.performance_snapshots` adds `compute_rolling_metrics()` (a
pure function over a list of closed-trade dicts -> `RollingMetrics`) and
`StrategyPerformanceEvaluator` (queries real `TradeTracker.
get_closed_trades()`, filters by `strategy_name`/optional `market_regime`,
takes the most recent `window_trades`, persists one
`StrategyPerformanceSnapshot` row). Wired as a real producer:
`scripts/run_paper.py::_check_and_close_open_positions` now calls
`StrategyPerformanceEvaluator().evaluate_and_snapshot(...)` every time a
trade closes -- the "Continuous Learning" trigger point named in
`docs/ADAPTIVE_ARCHITECTURE.md` section 1's feedback loop.

**Why R-multiples for expectancy/sharpe/sortino, percent-of-account for
max_drawdown**: same reasoning as decision #47's MAE/MFE -- R-multiples
are comparable across different position sizes/assets, raw PnL is not.
`max_drawdown` reuses the established `settings.PLACEHOLDER_ACCOUNT_BALANCE`
percent-of-account convention (decision #3), consistent with every other
percent-of-account figure in this codebase.

**Why finite sentinel caps (`_UNDEFINED_RATIO_CAP = 10.0`) instead of
`None`/`inf` for profit_factor/sortino/recovery_factor's "no losses yet"
case**: `StrategyPerformanceSnapshot`'s ratio columns are all non-nullable
`Float` (decision #44's schema), and neither SQL `NULL` nor Python
`inf`/`NaN` round-trips reliably through SQLite/JSON without special
handling at every reader. A large-but-finite, directionally honest value
("very good, not literally infinite") is a simpler, safer contract for
every future reader of this table, and is disclosed explicitly in the
module docstring/constant rather than left for a reader to discover by
surprise. Auto-disable logic is unaffected either way -- the cap only
applies on the WINNING side (no losses/no drawdown), and disabling only
triggers on the losing side.

**Why auto-disable requires `window_trades >= MIN_TRADES_FOR_CONFIDENCE`
(20, duplicated from `scripts/experiment_runner.py`, decision #41) before
`profit_factor <= 1.0` can trip it**: a strategy's first few trades are
not statistically meaningful (the entire reason this project's backtest
tooling has enforced a 20-trade floor since decision #41) -- disabling a
strategy after e.g. 3 losing trades would be noise-driven, not
evidence-driven, violating this project's core discipline the same way
inventing a regime->strategy rule table with no data would (decision
#46). Verified directly: 5 all-losing trades do NOT disable; the 20th
consecutive losing trade does, in the same test run.

**Scope reversal on `strategy_name`** (decision #47 had deliberately left
it unpopulated as milestone 5 scope creep): milestone 6's entire premise
-- PER-STRATEGY rolling metrics -- is impossible to compute on real data
without knowing which strategy produced each trade. `TradeTracker.
record_trade` now accepts `strategy_name` (still optional, still `None`
by default -- nothing breaks for callers that don't pass it), and
`scripts/run_paper.py` now passes `"jade" if settings.USE_JADE_ENGINE
else "legacy"`, the exact same effective mapping the Strategy Interface
(milestone 1) already establishes, just not yet routed through it (paper
trading still calls `SignalEngine` directly). This is a genuine
dependency this milestone cannot function without, not the same kind of
"cheap but unnecessary" addition decision #47 correctly deferred.
`market_regime` remains unpopulated -- still no real dependency on it
this milestone (`market_regime` stays an optional filter argument,
`None` by default, on `evaluate_and_snapshot`).

**Two real bugs found and fixed while writing this milestone's tests --
both were LATENT, because nothing had ever actually inserted a row into
`strategy_performance_snapshots` before this milestone's evaluator
existed**:
1. The milestone-2 migration (`e3110e6a6b59`) set `computed_at`'s
   `server_default` to `sa.text('now()')` -- valid Postgres syntax, but
   SQLite has no `now()` function (`sqlite3.OperationalError: unknown
   function: now()`), and every OTHER `DateTime` column with a
   server-side default in this codebase's migrations uses
   `sa.text('(CURRENT_TIMESTAMP)')` (verified across all of
   `a0f5ebc23690_initial_schema.py`). Fixed in-place (not via a new
   migration) since this migration was created earlier in this SAME
   session, is still the current head, and -- verified directly via
   `ps -W` before this fix -- had almost certainly never been applied
   against the real paper-trading database (only `app.main`'s FastAPI
   lifespan hook calls `run_migrations()`; no such process has been
   running alongside `scripts/run_paper.py`, PID 24616, since this
   migration was authored).
2. `StrategyPerformanceEvaluator.latest_snapshot()`'s ordering
   (`order_by(computed_at.desc())` alone) is non-deterministic when two
   snapshots are computed within the same SQLite `CURRENT_TIMESTAMP`
   tick (1-second resolution) -- a real, reachable case (consecutive
   trade closes, or this evaluator called back-to-back), caught by a
   test that intentionally computed two snapshots for the same strategy
   in quick succession and got the STALE one back. Fixed by adding `id`
   (monotonically increasing) as a tie-break: `order_by(computed_at.desc(),
   id.desc())`.

**Status**: 14 new tests (`tests/test_performance_snapshots.py`) --
`compute_rolling_metrics`'s win_rate/profit_factor/expectancy/
max_drawdown/sharpe/sortino/recovery_factor correctness plus every
sentinel-cap edge case, and `StrategyPerformanceEvaluator`'s real-DB
round-trip (strategy isolation, regime scoping, window-trades capping to
the most recent N, and the confidence-floor-gated auto-disable behavior
above). 430/430 backend tests passing. `is_disabled` is computed and
persisted but not yet CONSULTED by anything -- `DefaultToLegacySelector`
(milestone 4) still ignores it, same "computation before consumption"
staging this project has used for every new detector/evaluator since
decision #19. Editing `scripts/run_paper.py`/the migration file has no
effect on the already-running paper-trading process (PID 24616) --
confirmed still running throughout, untouched.

## 49. Risk Engine extensions: per-strategy disable hook and volatility-scaled sizing built as caller-computed plain values, keeping `app.risk` free of DB/regime imports; correlated exposure check explicitly deferred

**Decision** (operator directive, 2026-07-15, adaptive-platform pivot --
`docs/ADAPTIVE_ARCHITECTURE.md` section 5.2, milestone 7): of the 3
extensions section 5.2 named, 2 are built this milestone (High and Medium
priority) and 1 is deliberately deferred (Low priority, unchanged from
the doc's own assessment):

1. **Per-strategy disable hook** (High): `RiskManager.evaluate()` gains
   `strategy_disabled: bool = False`. When `True`, rejects with reason
   `"originating strategy is currently auto-disabled..."`.
2. **Volatility-scaled position sizing** (Medium): `calculate_position_size`
   gains `volatility: str | None = None`; `risk_amount` is multiplied by
   `volatility_risk_scalar(volatility)` (`app.risk.position_sizing`),
   0.5 in `high_volatility`, 1.0 otherwise/unset/unrecognized.
3. **Correlated exposure check** (Low): NOT built. Unchanged from the
   architecture doc's own reasoning -- it "only matters once MULTIPLE
   strategies can be concurrently active," which remains untrue today
   (`DefaultToLegacySelector` always returns `legacy`, and
   `scripts/run_paper.py`'s one-trade-open-at-a-time concurrency guard
   already prevents any overlap regardless). Building it now would be
   the exact "speculative machinery for a scenario that doesn't exist
   yet" decision #18 already rejected once for this project.

**Why both new parameters are CALLER-COMPUTED plain values (`bool`/`str
| None`), not lookups performed inside `app.risk`**: verified directly
that no file in `app/risk/` (`risk_manager.py`, `drawdown_guard.py`,
`circuit_breaker.py`) imports anything from `app.database`/`app.portfolio`
-- a deliberate existing layering this project already follows (every
other input to `RiskManager.evaluate()` -- `daily_pnl_percent`,
`weekly_pnl_percent`, `trades_today`, even the duck-typed
`circuit_breaker` object -- is computed/constructed by the CALLER,
`scripts/run_paper.py`, from `TradeJournal`/`TradeTracker`, never queried
inside `risk_manager.py` itself). Adding a real import from `app.risk` to
`app.portfolio.performance_snapshots` (even deferred/inside-the-method)
would have been the first crack in that layering; passing a
pre-computed `bool` instead preserves it exactly. Same reasoning applied
to sizing: `volatility_risk_scalar` accepts a plain string label (a
`MarketRegime.volatility` value), not the `MarketRegime` dataclass
itself, keeping `app.risk` decoupled from `app.regime`'s types the same
way `RiskManager`'s existing `SignalLike` Protocol avoids importing
`TradeSignal` directly.

**Why the 0.5 high-volatility scalar is disclosed-not-tuned**: same
status as `_STOP_BUFFER`/`_RR` before their 2026-07-11 sweep (decision
#18) -- a reasonable, conservative starting value, not backtest-derived.
`low_volatility` intentionally does NOT scale UP (stays 1.0): the
operator's spec calls for scaling risk DOWN as a safety measure only: a
calm reading can precede a breakout, so treating "low volatility" as
license to risk MORE would invert the safety intent.

**Both extensions wired as real producers in `scripts/run_paper.py`,
not left computation-only**: unlike most of this pivot's earlier
milestones (regime detector, selector, snapshots were all built before
being consumed), this milestone's two extensions are consumed the SAME
commit they're built, because their entire purpose is to be consulted
inline in the existing risk-evaluation/sizing call sites that already
run every pass -- there is no meaningful "build it, wire it up later"
staging for a gate that sits directly in the pipeline `run_once()`
already executes. `strategy_disabled` is computed via
`StrategyPerformanceEvaluator.is_strategy_disabled(active_strategy_name)`
(fails open to `False` on error, matching that method's own "no evidence
yet -> not disabled" contract). `current_volatility` is computed via
`detect_market_regime(candles)` reusing the SAME LTF `candles` already
fetched earlier in the same pass (best-effort, fails open to `None` ->
unchanged 1.0 scalar on any error or insufficient history). Both fail
OPEN, never closed -- a broken evidence lookup must degrade to
pre-milestone-7 behavior, never silently block trading or under-size a
position on a data-availability problem, not carry any new risk.

**`market_regime` (Trade's JSON audit column) also gets populated as a
direct byproduct**: since `detect_market_regime(candles)` is now computed
anyway (for sizing), persisting the FULL result as `Trade.market_regime`
(`dataclasses.asdict(regime)`) is nearly free and directly serves this
column's originally-stated purpose (section 6.2: "NOT just a label, the
whole audit-able classification"). This surfaced a real design gap in
milestone 6's `StrategyPerformanceEvaluator.evaluate_and_snapshot`: its
`market_regime` filter previously compared the filter string directly
against `Trade.market_regime` (a dict) -- a comparison that could never
match. Fixed to match against the dict's `trend` key specifically
(`t["market_regime"].get("trend") == market_regime`), since
`StrategyPerformanceSnapshot.market_regime` is a single `String(32)`
grouping key by schema design (section 6.3) and `trend` is the primary
partition among the composite classification's dimensions -- the same
kind of genuinely-ambiguous-prose judgment call decision #21 already
made once for this project, resolved and documented rather than left
implicit. This bug was latent (untested against real dict data) because
nothing had populated `Trade.market_regime` before this milestone.

**Status**: 12 new tests across 3 files (`test_risk_manager.py`:
`strategy_disabled` reject/omit; `test_risk_drawdown_and_sizing.py`:
`volatility_risk_scalar` mapping + `calculate_position_size`'s
volatility-aware scaling, including the "identical when omitted"
backward-compatibility case; `test_performance_snapshots.py`:
`is_strategy_disabled`'s no-snapshot-yet/reflects-latest-snapshot cases
and the trend-label market_regime scoping fix). 441/441 backend tests
passing. `docs/ADAPTIVE_ARCHITECTURE.md` section 5.2's table and the
roadmap table (section 7) both marked BUILT for items 1-2; item 3
explicitly left un-built with its original "Low today" reasoning
preserved verbatim. Legacy signal/exit logic remains completely
untouched -- these extensions changed the RISK ENGINE's sizing/approval
math only, and both default to pre-milestone-7-identical behavior
(`strategy_disabled=False`, `volatility=None` -> scalar 1.0) for any
caller that doesn't pass the new arguments. Editing `scripts/run_paper.py`
has no effect on the already-running paper-trading process (PID 24616,
Python has no hot-reload) -- confirmed still running throughout,
untouched; this changes production paper-trading sizing/rejection
behavior only on a future restart, not performed as part of this
milestone.

## 50. Milestone 7b: Strategy Selection Engine wired into paper trading behind `USE_STRATEGY_SELECTOR`, preserving `USE_JADE_ENGINE` as an explicit override and leaving automatic regime-based switching off

**Decision** (operator directive, 2026-07-16, following up on milestone 4):
`scripts/run_paper.py`'s signal-generation step now branches on a new
`settings.USE_STRATEGY_SELECTOR` flag (default `False`). `False` runs the
EXACT prior code path -- `SignalEngine().generate_signal(..., use_jade_engine=
settings.USE_JADE_ENGINE)` -- byte-for-byte unchanged. `True` routes
through a new `ConfigurableFallbackSelector` (`app.strategy.selector`)
instead. This closes a real gap flagged during a "continue autonomously"
check: milestone 4 built `DefaultToLegacySelector` and the whole
selection-engine machinery, but nothing in the live pipeline ever called
it -- `run_paper.py` still called `SignalEngine` directly. The naive fix
(swap in `DefaultToLegacySelector`) was rejected before being built: it
always returns `legacy` regardless of `settings.USE_JADE_ENGINE`, so
wiring it in would have silently made that documented, operator-facing
toggle ("do not flip this to True without real backtest evidence first",
`app/config.py`) permanently inert for paper trading -- a real regression
in operator capability disguised as a no-op refactor. The operator's
follow-up instruction specified 11 hard requirements resolving this;
each is addressed below.

**1-2. Legacy stays the default; `USE_JADE_ENGINE` stays meaningful.**
`ConfigurableFallbackSelector.__init__(use_jade_engine: bool = False)`
takes the flag as a CALLER-COMPUTED plain value (same "pass a pre-computed
value, don't look it up" pattern decision #49 established for
`app.risk`), read from `settings.USE_JADE_ENGINE` by `run_paper.py` and
passed in. If `True`, the selector selects `jade` -- an explicit operator
override, not automatic switching. Otherwise it ALWAYS selects `legacy`.
Verified directly (`test_configurable_fallback_selector_ignores_regime_for_
the_final_choice`): every trend/volatility combination, and a `None`
regime, produce the identical selected strategy for a fixed
`use_jade_engine` value.

**3. Deterministic fallback to Legacy when no regime-specific strategy has
validated evidence.** There is currently no such strategy AT ALL (no
`RollingPerformanceSelector` exists yet -- section 4.3, still gated on
real regime-tagged performance data), so the fallback path is exercised
on every single call that isn't an explicit override. `fallback_reason`
states this explicitly: `"automatic regime-based strategy switching is
disabled in production (operator instruction, 2026-07-16); no
regime-conditioned strategy has validated rolling-performance evidence
yet even if switching were enabled"` -- both halves of the reason (policy
AND evidence) are true independently, so the reason remains accurate even
after switching is eventually enabled, until real evidence also exists.

**4. Automatic regime-based switching stays OFF.** `regime` is accepted
by `select_with_reason()` and recorded on the returned `SelectionDecision`
(and, via `run_paper.py`'s print statement, in the console log) -- but it
is never read anywhere in the selection logic itself. This is
independently testable and tested
(`test_configurable_fallback_selector_ignores_regime_for_the_final_choice`,
`test_select_with_reason_records_regime_purely_for_observability`): the
same `use_jade_engine` value always produces the same strategy across
every regime, proving regime is observed, not consulted.

**5-6. Observability: logs + performance database.** Every selector-path
pass prints one line: `"Strategy Selection Engine: regime=<trend>/
<volatility> selected=<name> version=<version> selection_reason=<...>
fallback_reason=<...>"`. The same four fields (minus the raw regime,
which is separately captured in full via `Trade.market_regime`, decision
#49) are persisted into `Trade.strategy_config` (`use_strategy_selector`,
`selection_reason`, `fallback_reason`, `strategy_version`) -- reusing the
existing JSON snapshot column rather than a new migration, consistent
with how `use_jade_engine`/`enable_breakeven` are already recorded there.
`market_regime`, computed independently by milestone 7's volatility-scaled
sizing block, already captures "detected regime" on every trade
regardless of whether the selector path ran.

**Why `strategy_version` is a new field on the `Strategy` Protocol, not
computed elsewhere**: `LegacyStrategy.version`/`JadeStrategy.version`
both start at `"1.0"` -- a plain string, disclosed as having no version
history yet (same "the column exists so a real source has somewhere to
write" reasoning as `latency_ms`, decision #47). Adding it as a REQUIRED
Protocol field (not optional) was verified NOT to break
`isinstance(x, Strategy)` runtime-checkable conformance for either
existing adapter (both already define `name`; adding a second class
attribute of the same kind carries the same guarantee) -- confirmed by
the full suite staying green after the change, plus 2 new dedicated
version-presence tests.

**7. Feature flag**: `settings.USE_STRATEGY_SELECTOR: bool = False`
(`app/config.py`), same disclosed-default-off pattern as
`USE_JADE_ENGINE`/`ENABLE_BREAKEVEN`.

**8-9. Default configuration reproduces Legacy exactly, with regression
proof.** The `False` branch is the literal, untouched prior code -- no
new call, no new object construction, nothing. The regression proof
lives one layer up, at the level this codebase's actual test
architecture supports (`scripts/run_paper.py` has no dedicated test file,
true since before this milestone -- confirmed again this round, still
exercised via real paper-trading runs, not pytest):
`test_configurable_fallback_selector_default_config_matches_signal_engine_directly`
proves `ConfigurableFallbackSelector`'s own default output
(`use_jade_engine=False`, matching `Settings().USE_JADE_ENGINE`'s
default, itself asserted by a dedicated test) is byte-identical
(dataclass `==`) to calling `SignalEngine().generate_signal(...,
use_jade_engine=False)` directly -- the same equivalence
`test_strategy_interface.py` already established for `LegacyStrategy`
itself, extended one layer out through the selector. Position sizing
(`calculate_position_size`) and risk evaluation (`RiskManager.evaluate`)
are untouched by this milestone -- neither is called anywhere in
`app.strategy.selector` -- so milestone 7's existing sizing/risk-manager
test coverage remains the regression guard for those, unchanged.

**A real test-isolation bug found and fixed while writing test #9**: the
first version of the regression test imported `SignalEngine` INSIDE the
test function while `AVAILABLE_STRATEGIES` (used to build the selector's
`decision.strategy`) was imported at module level -- per `conftest.py`'s
own documented rule ("app.* modules must be imported inside the test
function body... otherwise they would bind to whatever module instance
happened to be cached first during collection"), this created a real
possibility of the two references binding to DIFFERENT `app.strategy.
signal_engine` module objects if an earlier DB-fixture test in the same
pytest session had purged and reimported `app.*` (via `conftest.py`'s
`_purge_app_modules`). This is exactly what happened: the test passed in
isolation but failed intermittently in the full suite with two
structurally-identical `TradeSignal` reprs comparing unequal (dataclass
`__eq__` checks `other.__class__ is self.__class__` first; two separate
module imports of the same source file produce two distinct classes).
Fixed by moving `SignalEngine` to the same module-level import statement
as `AVAILABLE_STRATEGIES`, matching this file's own established pattern.

**10. Paper trader never interrupted.** All of the above -- the new
`selector.py` additions, the `USE_STRATEGY_SELECTOR` flag, the
`run_paper.py` branching, every test -- was written, tested, and verified
via `py_compile` + the full 454/454 backend suite WITHOUT restarting the
already-running paper-trading process (PID 24616) at any point; `ps -W`
confirmed it running before and after every change in this milestone,
matching the discipline every prior milestone in this pivot has followed.
Since Python has no hot-reload, none of this code runs against the live
process until its next restart (not performed here).

**Status**: 21 new tests across `test_strategy_selector.py` (14: protocol
conformance, override/fallback selection, regime-invariance including the
`None` case, `SelectionDecision` field correctness, `select()`/
`select_with_reason()` equivalence, the `USE_STRATEGY_SELECTOR` default,
and the SignalEngine-equivalence regression proof) and
`test_strategy_interface.py` (2: `version` field presence on both
adapters), plus updates confirming no regressions in the existing 431.
454/454 backend tests passing. `docs/ADAPTIVE_ARCHITECTURE.md` section 4
updated to reflect the live wiring. **Enabling/disabling**: set
`USE_STRATEGY_SELECTOR=True` in the environment (or `.env`) to route
paper trading through the Strategy Selection Engine; unset it (or leave
`False`) to keep the exact pre-existing direct-`SignalEngine` path.
`USE_JADE_ENGINE` continues to control Legacy-vs-Jade under EITHER
setting of `USE_STRATEGY_SELECTOR`. Requires a `scripts/run_paper.py`
restart to take effect (not performed as part of this milestone).

## 51. Milestone 8.1: live paper-DB migration via fingerprint-detect-and-stamp, not DB recreation or hand-written ALTERs -- refuses unrecognized schemas rather than guessing

**Decision** (operator directive, 2026-07-16): `app.database.
migrate_existing.migrate_database()` brings an EXISTING, never-alembic-
stamped SQLite database up to the current migration head by (1)
fingerprinting which of 4 historical schema generations the file's raw
table/column layout matches (`a0f5ebc23690` initial -> `4b8a822a475b`
circuit-breaker columns -> `393afdf7fe67` observability columns ->
`e3110e6a6b59` adaptive platform), (2) stamping that revision as the
alembic baseline (`alembic stamp <rev>`, not a real migration run -- the
schema is already at that shape), then (3) running a normal `upgrade
head`. `scripts/migrate_paper_db.py` is a thin CLI over it, detect-only
by default, `--apply` to mutate.

**Why this exists**: the live paper-trading DB (`backend/
paper_validation.db`) was created by an early bootstrap predating this
project's alembic discipline -- no `alembic_version` table at all -- and
`scripts/run_paper.py` never runs migrations (only `app.main`'s FastAPI
lifespan does, and no FastAPI process runs alongside the paper trader).
Every adaptive-platform milestone since #2 added columns/tables the live
DB never received, so a paper-trader restart on current code would crash
on its first `TradeTracker.record_trade()` INSERT.

**Why fingerprint-detect + stamp + upgrade, not the two obvious
alternatives**:
- **Recreating the DB from scratch** (drop and let the app/alembic build
  a fresh one) was rejected -- the live file's `bot_state` row IS the
  real, currently-tracked circuit-breaker/drawdown state, and any trades/
  signals already recorded would be destroyed. A migration tool that
  loses live data to "fix" a schema gap is not actually a fix.
- **Hand-written `ALTER TABLE`/`CREATE TABLE` statements** replicating
  what the missing migrations already do were rejected -- the exact DDL
  for every intermediate schema step already exists and is tested inside
  `app/database/migrations/versions/`; re-deriving it by hand in a
  separate script would create a second, driftable source of truth for
  the same schema history, with no guarantee the hand-written version
  matches what `alembic upgrade` actually produces. Stamping a detected
  baseline and then running the REAL migration chain guarantees the
  result is byte-identical to any other DB that reached head the normal
  way.

**Why refuse (raise `ValueError`) rather than guess on an unrecognized
schema**: `detect_schema_generation()` returns `None` (not a best-effort
guess) whenever a file's tables/columns don't match any known
fingerprint or a stamped `alembic_version` table -- `migrate_database()`
then refuses to touch it. Stamping the wrong baseline would silently skip
real migrations (columns the app expects would still be missing) or
attempt to re-apply migrations against a schema that doesn't match their
assumptions (`ADD COLUMN` on a column that already exists, a hard
failure, or worse, a silent partial state). Matches this project's
long-standing "return `None`/refuse rather than fabricate an answer"
discipline already established for `calculate_premium_discount` (decision
#19) and every other structural detector in `app/strategy/`.

**`env.py` guard pattern**: `app/database/migrations/env.py` previously
unconditionally injected `settings.DATABASE_URL` into the alembic config.
`migrate_existing.build_alembic_config()` needs to target an ARBITRARY
file path (the live DB, or a test's `tmp_path` fixture), not whatever
`settings.DATABASE_URL` happens to point at. The guard added is a single
`if not config.get_main_option("sqlalchemy.url"):` before the injection --
only fills in `settings.DATABASE_URL` when the caller hasn't already set
one programmatically. This is backward-compatible by construction:
`alembic.ini` commits an EMPTY `sqlalchemy.url`, so every pre-existing
caller (`app.main`'s `run_migrations` on FastAPI startup, `conftest.py`'s
test-DB fixtures, a bare `alembic upgrade head` from the CLI) never sets
the option beforehand and therefore still falls through to `settings`
exactly as before -- verified by the full 465/465 suite passing unchanged
alongside the 11 new migration tests.

**Test fixtures built from the real migration chain via RENAME, not
hand-built or DROP**: `test_migrate_existing.py`'s old-generation
fixtures are produced by running alembic ITSELF (`command.upgrade(cfg,
<old_revision>)`) and then `ALTER TABLE alembic_version RENAME TO
not_a_stamp_fixture` to hide the stamp -- simulating the live DB's real
condition (a schema that matches an old generation but carries no
`alembic_version` table) using the REAL migration-produced schema, not a
hand-built imitation that could silently drift from what the actual
migrations produce. RENAME rather than DROP specifically because this
repo's tooling gates destructive SQL keywords even inside test fixtures --
a rename hides the table from `detect_schema_generation()` (which checks
table existence by exact name) exactly as effectively as a drop would,
without using a blocked statement.

**Verified this session**: full backend suite 465/465 passing (454 + 11
new). Detection-only run against the live DB matched generation
`4b8a822a475b`, un-stamped -- exactly the predicted real-world condition.
`--apply` backed up to `backend/paper_validation.db.backup-20260715T174615Z`,
stamped `4b8a822a475b`, upgraded `4b8a822a475b` -> `393afdf7fe67` ->
`e3110e6a6b59` (head), verification passed. Post-migration check: the
existing `bot_state` row (1 row) survived intact; `trades`/`signals`/
`strategy_performance_snapshots` all had 0 rows both before and after (the
paper trader had recorded no trades yet on this DB, so nothing was at
risk of being lost). The paper trader process was not running at
migration time (confirmed no python process, same sandbox-persistence
caveat already documented elsewhere in this project's history), so there
was no open-file contention to reason about for this particular run --
the additive-migrations-are-safe-against-a-concurrently-open-file
argument in the module's own docstring remains a design property for the
next time this runs against a live process, not something this session
exercised directly.

## 52. Milestone 9: four new strategy-CONTENT modules ship quarantined in a separate `EXPERIMENTAL_STRATEGIES` registry, evidenced through `BacktestEngine` via signal-source-only injection

**Decision** (2026-07-16): `app.strategy.trend_following.TrendFollowingStrategy`,
`range_trading.RangeTradingStrategy`, `breakout.BreakoutStrategy`, and
`volatility_expansion.VolatilityExpansionStrategy` are the platform's
first `Strategy`-Protocol modules that are NOT `SignalEngine` wrappers --
each implements its own detection ruleset directly (HTF/LTF trend
agreement + pullback resumption; ADX-gated range fade; Donchian-channel
breakout with body/volume confirmation; volatility-squeeze-then-expansion
entry), reusing existing indicator helpers
(`regime_detector`/`market_structure`/`utils`) rather than reimplementing
any of them. All four are detection-only (never place orders) and return
`None` generously on insufficient/ambiguous input, matching every
existing detector's discipline in this package. This is Milestone 8 on
`docs/ADAPTIVE_ARCHITECTURE.md`'s section 7 roadmap -- deliberately the
LAST item, since strategy CONTENT was always secondary to finishing the
system that can host/select/evaluate/retire strategies (milestones 1-8.1,
all already built).

**(a) A separate quarantine registry, not registration into
`AVAILABLE_STRATEGIES`**: `app.strategy.experimental.EXPERIMENTAL_STRATEGIES`
holds all four new modules; `all_strategies()` returns a FRESH merged dict
(`{**AVAILABLE_STRATEGIES, **EXPERIMENTAL_STRATEGIES}`) for tooling that
needs to see everything. `AVAILABLE_STRATEGIES` itself
(`app.strategy.strategy_interface`) is untouched -- still exactly
`{legacy, jade}`. This matters because every real selector in this
codebase (`DefaultToLegacySelector`, `ConfigurableFallbackSelector`)
consults `AVAILABLE_STRATEGIES` directly, never `all_strategies()` -- so
"registered somewhere in the codebase" must never be allowed to creep
into "selectable by production/paper trading" without a deliberate,
evidence-gated promotion step. Verified directly: `test_experimental_
registry.py` asserts both selectors return only `legacy`/`jade` even when
handed the full 6-strategy merged registry as their `available` argument.
Promotion into `AVAILABLE_STRATEGIES` requires real backtest/walk-forward
evidence, the same "implemented != evidenced" discipline this project has
applied to every opt-in flag since decision #10.

**(b) `Strategy` injection into `BacktestEngine` at the signal source
only, so experimental strategies are evidenced through the SAME pipeline
as production**: `BacktestEngine.run()` gained an additive `strategy:
Strategy | None = None` parameter (import guarded behind `TYPE_CHECKING`
-- the engine has never had a real dependency on `strategy_interface`,
matching how it has always accepted any object with a matching
`generate_signal` method). `None` (the default) is byte-identical to
every existing caller's behavior -- proven by a test using a
`SignalEngine` fake that raises if called, confirming the bypass is
total. When a `Strategy` is given, ONLY the signal source changes (each
step calls `strategy.generate_signal(symbol, ltf_candles, htf_candles)`
instead of `signal_engine.generate_signal(...)`); every downstream stage
-- risk gating, position sizing, fills, fees, slippage, break-even/
partial-TP management, PnL, reporting -- is unchanged. `scripts/
run_backtest.py --strategy NAME` resolves the name via `all_strategies()`
BEFORE any candle fetch (fails fast on an unknown name, listing the
available names, rather than after a slow network round-trip), and
prints a `NOTE` listing any SignalEngine-only flags (`--breaker-block`,
`--strict-confluence`, etc.) that were set alongside `--strategy` and are
therefore ignored -- the same "warn, don't silently drop" precedent
`--jade-engine` already established for its own flag interactions.

**Why this is the correct "evidence pipeline" design**: this repo's
entire evidentiary standard (decisions #8, #14, #15, #18) rests on
`BacktestEngine`'s fee/slippage/walk-forward/out-of-sample machinery
being the thing that turns a claim into evidence. Injecting a new
strategy at any OTHER layer (e.g. a parallel mini-backtester, or
hand-rolled PnL math specific to the new modules) would produce numbers
that are not directly comparable to every existing finding in this
project's history. Signal-source-only injection guarantees an
experimental strategy's eventual backtest numbers are apples-to-apples
with Legacy's own historical results, computed by literally the same
code.

**(c) Shipping four disclosed-not-tuned textbook rulesets does NOT
violate this project's evidence-over-assumption discipline**: each
module's docstring explicitly states its thresholds (ADX floors, ATR
multipliers, fixed 2.5R targets, percentile ceilings) are standard
textbook values, "disclosed, not tuned... ZERO backtest evidence yet" --
the same posture `entry_model._RR`/`_STOP_BUFFER` held before their
2026-07-11 sweep (decision #18) and `regime_detector.py`'s own ADX/
volatility thresholds still hold today. The discipline this project
enforces is never "don't ship untuned code" -- untested textbook rules
have shipped before, always behind a flag or a registry that keeps them
inert (decision #10). It is "don't let an untuned/unevidenced ruleset
influence real trading." These four modules satisfy that: they are
quarantined test subjects sitting in `EXPERIMENTAL_STRATEGIES`, reachable
only via `--strategy` on `run_backtest.py`'s research tooling, invisible
to both configured selectors and therefore to paper/live trading
entirely.

**(d) `range_trading`'s rr-floor finding**: `RangeTradingStrategy` only
emits a signal when its own computed `rr >= 2.0` (this platform's
`RiskManager.MIN_RR`), guarding against emitting a signal the Risk Engine
would reject anyway. Working through the module's own formulas
algebraically (given the range-width gate `width >= 2.0 * atr` and the
edge-fade zone `_EDGE_PERCENTILE = 0.15`) shows the achievable rr floor
is approximately 2.125 whenever the width and edge gates already pass --
i.e. the `rr < 2.0` guard in the code is, for this exact parameter
combination, defensive rather than independently reachable in practice.
Documented rather than silently removed: the guard costs nothing, keeps
the invariant explicit and self-checking if any of the surrounding
constants (`_MIN_RANGE_WIDTH_ATR_MULTIPLE`, `_STOP_ATR_MULTIPLE`,
`_EDGE_PERCENTILE`) ever change independently, and matches this
project's "return None generously rather than trust an upstream
invariant silently" discipline used throughout `app/strategy/`.

**Status**: 38 new strategy/registry tests (7 trend_following + 9
range_trading + 6 breakout + 8 volatility_expansion + 8 experimental
registry) + 2 new `BacktestEngine` injection tests = 40 new tests. Full
suite 505/505 passing (was 465 after milestone 8.1). Production behavior
unchanged: `AVAILABLE_STRATEGIES` still exactly `{legacy, jade}`, the
paper trader (Legacy engine) untouched and running throughout. Smoke
check: `all_strategies()` -> `['breakout', 'jade', 'legacy',
'range_trading', 'trend_following', 'volatility_expansion']`.

---

## 53. Milestone 11: shadow-mode observability -- per-pass `RegimeSnapshot` table plus non-active-strategy `ShadowSignal` recording, default-off

**Decision** (2026-07-16): new tables `regime_snapshots` and
`shadow_signals` (migration `36cb62e9e2ac`, down_revision
`e3110e6a6b59`), new ORM models `RegimeSnapshot`/`ShadowSignal`
(`app/database/models.py`), a new `app.portfolio.shadow_recorder.
record_shadow_pass()`, and a new settings flag
`ENABLE_SHADOW_STRATEGY_SIGNALS: bool = False` wired into `scripts/
run_paper.py` at exactly two settled points of `run_once` -- the
no-signal early return and the end of the full trade path (reusing the
regime already computed there in both cases).

**Motivation**: before this, regime data persisted ONLY on trade rows
(`Trade.market_regime`), and Strategy Selection decisions only ever
existed in stdout. A "no signal" pass -- the overwhelming majority of
passes -- persisted nothing at all, so the regime-tagged dataset that
`docs/ADAPTIVE_ARCHITECTURE.md` section 4.3's future
`RollingPerformanceSelector` needs was only ever accumulating at TRADE
speed, i.e. effectively zero rows to date.

**(a) A per-pass `RegimeSnapshot` table instead of re-deriving regimes
later from stored candles**: every enabled pass writes one row
(`captured_at`/`symbol`/`timeframe`/`trend`/`volatility`/`breakout`/
`mean_reversion`/`liquidity_sweep_environment`/`metrics` JSON). Rejected
re-deriving regimes retroactively from historical candles -- this
project's own precedent (`Trade.market_regime`) is to store the whole
classification at the moment it was computed, not reconstruct it later
from raw inputs that may not even be retained at the same resolution;
the pass cadence itself is the honest sampling unit for this data.

**(b) `shadow_signals` stores only actual would-be signals; `regime_
snapshots` is the per-pass heartbeat**: row-volume discipline -- most
passes produce no signal from any given strategy, and recording a row
per (pass x strategy) regardless of outcome would bloat the table with
no analytical value the regime snapshot doesn't already provide.

**(c) The ACTIVE strategy is excluded from shadow evaluation**:
`record_shadow_pass()` runs `all_strategies()` MINUS whichever strategy
the Strategy Selection Engine actually selected for that pass -- its
real signals/trades are already persisted via the existing trade/signal
path, so including it in shadow evaluation would double-count. Each
non-active strategy is evaluated in its own try/except so one broken
strategy's exception never blocks recording for the others (errors are
counted and returned, not raised).

**(d) Wiring at two settled points of `run_once`, not every early-return
branch**: the no-signal return and the end of the full trade path are
the only two points where a regime has already been computed and the
pass is about to conclude either way -- matching this project's existing
"reuse what's already computed, don't recompute" discipline elsewhere in
`run_paper.py`.

**(e) Default-off (`ENABLE_SHADOW_STRATEGY_SIGNALS = False`)**: same
opt-in-before-default-change discipline as decision #10. Flipping it in
the live process is explicitly an OPERATOR decision, and takes effect
only on the next trader restart -- the currently running paper-trading
process keeps executing whatever code it already loaded, unaffected by
a config-file edit alone (same caveat already documented for prior
flags in this project's history).

**Quarantine intact under every flag combination**: shadow mode only
ASKS non-active strategies what they would have signaled; it never
places an order, never influences risk gating or sizing, and never
feeds back into `AVAILABLE_STRATEGIES` or either configured selector.
`AVAILABLE_STRATEGIES`, `DefaultToLegacySelector`,
`ConfigurableFallbackSelector`, and what actually trades are untouched
regardless of whether `ENABLE_SHADOW_STRATEGY_SIGNALS` is on or off.

**Status**: 16 new tests (13 in `test_shadow_observability_schema.py`, 3
in `test_shadow_recorder.py`). `backend/tests/test_db_bootstrap.py`'s
pinned migration head updated `e3110e6a6b59` -> `36cb62e9e2ac` per its
own comment's mandate. Full suite 518/518 passing (was 505 after
milestone 9). Verified with a real-temp-DB smoke script: flag ON writes
rows and adds a `"shadow"` summary key; flag OFF writes zero rows, adds
no key, and the rest of the summary is identical -- confirming the
flag-off path is byte-identical to pre-milestone behavior.

## 54. Milestone 12: regime-tagged backtesting + per-regime performance analytics + evidence round 2 -- post-risk-approval tagging point, key-absence over `None`, pure-function analytics, and a real Windows console encoding bug caught before it could silently discard a completed run

**Decision** (2026-07-16): `BacktestEngine.run()` gained a new final
parameter `tag_regimes: bool = False`. When `True`, every
accepted/simulated trade dict gets a `"market_regime"` key holding the
full `detect_market_regime` classification computed at the signal's OWN
candle index; when `False` the key is absent entirely, and every other
byte of behavior is unchanged. New pure-function module
`backend/app/backtesting/regime_analysis.py`
(`regime_bucket`/`aggregate_by_regime`/`comparison_table`) and new CLI
`scripts/analyze_regime_performance.py`.

**(a) Tagging point is post-risk-approval, at the signal's own candle
index**: this mirrors exactly where `scripts/run_paper.py` tags
`Trade.market_regime` -- the regime is computed once risk has already
approved the trade, not at signal-generation time and not at exit. Only
real (accepted, simulated) trades are tagged, matching what "a trade's
regime" already means everywhere else in this codebase. The computation
is wrapped in try/except and degrades to `None` on failure, so a regime
detector edge case can never fail an otherwise-valid backtest trade.
Both signal paths -- the default `SignalEngine` path and the milestone-9
`strategy=` injection path -- go through the same tagging call, so
regime data is available identically regardless of which strategy
produced the trade.

**(b) Key-absence, not `None`, distinguishes untagged runs**: when
`tag_regimes=False`, `"market_regime"` is not merely set to `None` --
the key does not exist in the trade dict at all, so the result is
byte-identical to every pre-milestone-12 trade dict (no new key for old
callers to accidentally serialize, diff, or iterate over). `None` is
reserved for the genuinely different case of "tagging was requested but
classification failed for this trade."

**(c) Analytics as pure functions, separate from I/O**:
`regime_analysis.py` takes trade lists in and returns
rows/strings out -- no DB access, no file writes, no network calls --
so it is independently unit-testable against hand-computed fixtures and
reusable from any future caller (CLI, future dashboard, tests) without
dragging in I/O concerns. `win_rate`/`profit_factor` are reused from
`app.backtesting.performance` rather than reimplemented; `expectancy` is
defined locally in `regime_analysis.py` because `scripts/` (where the
project's other `expectancy` lives, in `experiment_runner.py`) is not
importable from `app` code -- a one-way dependency boundary this project
has kept consistently. Bucketing is `"{trend}/{volatility}"` with an
explicit `"untagged"` fallback for trades carrying `None`, and
`MIN_TRADES_FOR_CONFIDENCE=20` reuses this project's own established
evidence floor (`experiment_runner.MIN_TRADES_FOR_CONFIDENCE`) rather
than inventing a new threshold.

**(d) A real bug, caught by evidence round 2 itself, before it could
silently discard a completed multi-minute run**: the first real run of
`analyze_regime_performance.py` crashed with `UnicodeEncodeError` on the
'⚠' (U+26A0) insufficient-sample marker inside `print(table)`, because
the Windows console default encoding is cp1252, which cannot represent
that character. The crash happened AFTER the (slow, multi-minute) run
had already fetched candles and backtested five strategies across the
full periods -- and BEFORE the results were written to a file, so the
completed run's output was entirely lost to a print-time encoding
error. Two changes: (1) `comparison_table()` now marks insufficient-
sample rows with the ASCII string `"(! n<20)"` instead of a Unicode
glyph -- console-safe on any platform's default encoding, not just
UTF-8 terminals; (2) `analyze_regime_performance.py` now writes the
report to its output file BEFORE printing it to the console, so a
console-encoding failure can no longer take completed results down with
it. Verified by an explicit cp1252 round-trip encode of the new marker
string. Recorded as its own lettered point because it is a real
lesson, not a cosmetic tweak: **user-facing tool output in this
codebase must be ASCII-safe by default, and any script that both writes
a file and prints to console must write the file first** -- the print
is allowed to fail; the results are not allowed to be lost when it
does.

**Status**: 4 new tests in `test_backtest_engine.py` (real-classification
tagging on both signal paths, key-absence as the untagged default,
explicit `tag_regimes=False` producing an identical result to the
implicit default -- one fixture bug caught along the way, the regime-
detection fixture was missing the `volume` key needed for classification
to run at all) + 17 new tests in `test_regime_analysis.py`
(hand-computed arithmetic fixtures, the 19-vs-20 sample-size boundary,
markdown marker rendering, empty-input handling). Full suite **539
passed / 0 failed** (was 518 after milestone 11).

**Evidence round 2 result** (full report:
`docs/REGIME_PERFORMANCE_ANALYSIS.md`, final): same anchor as round 1
(BTCUSDT 15m, `--candles 3000 --periods 6 --end-date 2026-07-10`), pooled
totals reproduced round 1 exactly, confirming the tagging machinery
changes nothing about what was already evidenced. No bucket shows an
experimental strategy credibly beating Legacy -- the only bucket with
n>=20 on both sides (`weak_trend/normal_volatility`, BTC's dominant
regime) has Legacy at +$26.28 expectancy / PF 3.30 (n=28) versus the
best experimental strategy, `volatility_expansion`, at +$4.29 / PF 1.23
(n=56). Legacy is positive in all 9 regime buckets but 8 of 9 are
n<20 -- it trades too selectively (111 trades/6mo) for per-regime
evidence to accumulate fast on this asset/window alone. A correctly
built `RollingPerformanceSelector` run against this exact dataset would
therefore route Legacy in 9/9 buckets today (8 by insufficient-data
fallback, 1 by argmax) -- confirming shadow-mode recording (milestone
11) is the right lever for filling the sparse buckets, not a further
backtesting round on this same single asset/window.

---

## 55. Milestones 13-15: shadow-data status tooling, shadow outcome resolution, and a rolling per-regime evidence layer -- read-only-by-construction tooling, SL-first mirroring of the backtester's own convention, source-never-blended evidence, and a JSON-serialization bug the first live shadow signal would have hit

**Decision** (2026-07-16): three additive milestones, all extending the
milestone-11 shadow-observability track toward a real evidence base for
`RollingPerformanceSelector` (section 4.3, `docs/ADAPTIVE_ARCHITECTURE.md`),
plus one production bugfix found along the way.

**(a) Milestone 13 -- shadow-data status tool.** New
`scripts/shadow_status.py` (CLI) + `app/portfolio/shadow_status.py` (pure
helpers: reuses milestone-12's `regime_bucket` convention, snapshot
stats, per-(strategy, bucket) signal counts, and a "distance to the
20-sample routability floor" report). The CLI opens its SQLite connection
with a `mode=ro` URI, not merely "doesn't happen to write" -- a write
attempt is provably refused by SQLite itself, not by the script's own
discipline, which matters for a tool operators will run against the live
DB while the paper trader has it open. Console output is ASCII-only,
applying decision #54's cp1252 lesson pre-emptively rather than waiting
to hit the same crash again. The report carries an explicit honesty
note: raw signal counts are NECESSARY but not SUFFICIENT for
routability -- what `RollingPerformanceSelector` actually needs is
performance-EVALUATED samples (an outcome, not just a captured signal),
which is exactly the gap milestone 14 closes. 18 tests. Live smoke the
same day: 3 regime snapshots already accumulating, 0 shadow signals yet
(shadow mode had only just been operator-enabled).

**(b) Milestone 14a -- outcome-resolution schema.** New migration
`65aba13281ad` (chained on `36cb62e9e2ac`): `ShadowSignal` gains
`outcome` (nullable indexed String, `"tp"`/`"sl"`/`"expired"`, `NULL`
means still open -- same key-absence-over-sentinel discipline as decision
#54(b), applied to a column instead of a dict key), `resolved_at`, and
`resolved_r` (`+rr` for a `"tp"` outcome, `-1.0` for `"sl"`, `NULL` for
`"expired"` -- an expired signal has no realized R because nothing was
simulated to conclusion). 8 tests, including the old-generation
`migrate_existing` upgrade paths -- `test_db_bootstrap.py` and
`test_shadow_observability_schema.py` both have their own maintenance
comments requiring their pinned head revision / column-set assertions to
move in lockstep with new migrations, and both were updated accordingly.

**(c) Milestone 14b -- the resolver.** New
`app/portfolio/shadow_resolver.py`:
`resolve_open_shadow_signals(symbol, ltf_candles, now)` walks candles
STRICTLY AFTER a signal's `captured_at`, and within any candle that
touches both the stop and the target, resolves SL before TP -- this
mirrors `BacktestEngine._simulate_trade`'s own documented conservative
convention (cited directly in the resolver's docstring, not
reinvented), so a shadow signal's simulated fill logic is not a second,
divergent definition of "what happened" from the one this project
already trusts for backtesting. `EXPIRY_HOURS = 168` (7 days) is
disclosed as a chosen-not-tuned value, same discipline as every other
new threshold in this project, and expires a signal to `"expired"` if
neither SL nor TP is touched within that window. Wired into
`run_paper.py`'s existing shadow block, behind the SAME
`ENABLE_SHADOW_STRATEGY_SIGNALS` flag milestone 11 already gated (no new
flag), fault-isolated (a resolution error cannot abort the paper pass),
and ordered to run resolution BEFORE recording new signals in the same
pass -- so a signal is never resolved in the same pass it was captured,
which would otherwise let a same-candle TP/SL touch resolve against
information the live system did not actually have "one pass ago." Summary
surfaces under `summary["shadow"]["resolution"]`. 9 tests plus a
real-temp-DB smoke test (an end-to-end `run_once` resolved a
pre-inserted signal to `tp`/+2.0R). Disclosed caveat, carried in both the
resolver's docstring and this record: shadow outcomes are simulated
fills with no fees or slippage applied -- they are an OPTIMISTIC UPPER
BOUND on what a live version of that strategy would have realized, not
an unbiased estimate.

**(d) The SQLite naive-datetime lesson** (documented here because both
(c) and milestone 15 independently hit it): SQLAlchemy's `DateTime(timezone=True)`
round-trips through SQLite as a NAIVE datetime on read -- SQLite has no
native timezone-aware storage, so SQLAlchemy silently strips `tzinfo`
coming back out, even though the value that went in was tz-aware. Candle
timestamps (sourced from OKX, via `app.data`) stay tz-aware throughout.
Comparing a naive `resolved_at`/`captured_at` against a tz-aware candle
timestamp raises `TypeError: can't compare offset-naive and
offset-aware datetimes`, not a silently wrong answer -- but both new
modules needed their own explicit naive-UTC normalization helper to
avoid hitting it at all. Recorded so a fourth module doesn't rediscover
this by crashing.

**(e) Milestone 15 -- rolling per-regime evidence layer.** New
`app/portfolio/rolling_regime_performance.py`: `RegimeCellEvidence`
dataclass + `collect_regime_evidence(session, window_days=30,
min_samples=20)`, returning a dict keyed by `(strategy, bucket, source)`
where `source` is `"shadow"` or `"live"`. **The two sources are
deliberately never averaged together** -- this is the key design
decision this milestone contributes: a shadow fill (simulated, fee-free,
using candle data the strategy never had to survive slippage or partial
fills against) and a live fill (real, fee-paying, actually executed) are
different measurement instruments, not two samples of the same
quantity, and pooling them would launder a systematically optimistic
number into what looks like a single unbiased one. This layer reports
both, separately, and leaves the SELECTOR (milestone 16) to decide
precedence explicitly and visibly, rather than deciding it implicitly
here where the choice would be invisible to anyone reading selection
output. Shadow-side counts only RESOLVED `tp`/`sl` outcomes toward `n`
(an `expired` or still-open signal is tallied separately as
`n_excluded`, not silently dropped and not silently counted as if it
were evidence). Live-side counts only closed trades that both carry a
non-`NULL` `market_regime` AND a non-`NULL` `r_multiple` -- trades from
before this platform's regime-tagging existed are skipped entirely, not
folded into an `"untagged"` bucket the way milestone-12's backtest
analytics do, since conflating "we don't know this trade's regime" with
"this trade happened in some regime we're choosing not to distinguish"
would understate the real per-regime sample sizes. 14 tests, all against
hand-computed arithmetic fixtures (not assertions on the function's own
output).

**Status**: 18 (M13) + 8 (M14a) + 9 (M14b) + 14 (M15) tests, plus the
bugfix regression test in (below) = roughly 50 new tests across this
group. Full suite reached **602 passed / 0 failed** counting milestone
16 (#56) together with this group (was 539 after milestone 12). Live
paper trader ran untouched throughout; `AVAILABLE_STRATEGIES` and both
production selectors are untouched by any of milestones 13-15.

**Bugfix, found by milestone 14b's own smoke test, fixed the same day**:
`shadow_recorder.record_shadow_pass()` wrote `dataclasses.asdict(signal)`
straight into a JSON column. `TradeSignal.timestamp` is typed `str` in
the dataclass definition but in production carries a real `datetime`
object (the type hint has been aspirational, not enforced, since before
this milestone) -- `json.dumps` cannot serialize a `datetime` and raises
`TypeError` at flush time. **This was worse than an isolated recording
failure**: the `raise` propagated from OUTSIDE the per-strategy
try/except guard milestone 11 built specifically so one broken strategy
couldn't take down shadow recording for the others -- so this bug
aborted the ENTIRE shadow-recording pass, for every strategy, every
time. **Latent-live severity**: `ENABLE_SHADOW_STRATEGY_SIGNALS` had
been operator-enabled that same day (the milestone-13 smoke test found
it already on), which means the very FIRST real shadow signal generated
by the live paper trader would have hit this exact `TypeError` and been
silently lost -- "silently" because the surrounding pass still completed
normally from the trader's own perspective; only the shadow side would
have gone dark. Fix: a recursive `_json_safe` sanitizer (datetime ->
`isoformat()`, applied structurally so nested dict/list values are
covered too) wraps both `signal_payload` and `market_regime` before they
reach the JSON column. Verified by a regression test that reproduces the
original crash (observed failing pre-fix against an unpatched copy of
the function) and confirms it passes post-fix.

---

## 56. Milestone 16: `RollingPerformanceSelector` -- built and tested, deliberately NOT wired -- conservative gates on top of milestone 15's evidence layer, and why an unwired selector is still worth shipping

**Decision** (2026-07-16): `app/strategy/selector.py` gains a
module-level seam `select_for_bucket(bucket, evidence, available,
min_samples)` plus a class `RollingPerformanceSelector` (conforms to the
existing `StrategySelector` Protocol, implements `select_with_reason()`
the same way `ConfigurableFallbackSelector` does) -- appended to the
file; every existing class in it (`DefaultToLegacySelector`,
`ConfigurableFallbackSelector`) is untouched. This is the
`RollingPerformanceSelector` section 4.3 of
`docs/ADAPTIVE_ARCHITECTURE.md` has described as "not built yet" since
milestone 4 -- it is now built, consuming milestone 15's evidence layer
directly, but it is **not** wired into `scripts/run_paper.py`; production
selection is still `ConfigurableFallbackSelector`, unchanged.

**The selection rule, each step a deliberate, disclosed gate** (documented
in the class's own docstring, restated here for the record):

1. `regime is None` -> `legacy`. No evidence layer has an opinion about
   "no regime," so there is nothing to select against.
2. Legacy's OWN live cell for this bucket must itself be sufficient
   (`n >= min_samples`, default 20, milestone-15's own floor) before any
   challenger is even considered. If it is not, the result is `legacy`
   with reason `"fallback_legacy_baseline_unmeasured"` -- **a challenger
   cannot beat a baseline that hasn't itself been measured yet**; "we
   don't know if Legacy is good here" is not evidence that something
   else is better, it is an absence of evidence in both directions.
3. Each challenger strategy's cell is read with **live precedence**: use
   its live cell if that cell is sufficient, otherwise fall back to its
   shadow cell. A challenger is never allowed to cherry-pick shadow data
   when live data already exists and disagrees with it -- live is always
   preferred when both are available, per milestone 15's "different
   measurement instruments" framing in decision #55(e).
4. A challenger qualifies only if its expectancy_r is **strictly greater
   than 0 AND strictly greater than Legacy's own expectancy_r** in this
   bucket -- both conditions, not either. A challenger with positive but
   sub-Legacy expectancy is not "good enough to diversify into," it is
   simply worse.
5. Among qualifying challengers, argmax by expectancy_r wins. A tie, or
   no qualifying challenger, falls back to `legacy`.
6. Any winning selection whose evidence came from a challenger's SHADOW
   cell (not live) carries an explicit `"_shadow_evidence_optimistic"`
   marker in its reason string -- so a caller inspecting selection
   output is never left to assume shadow-sourced wins carry the same
   confidence as a live-measured one; decision #55(e)'s fee-free-fills
   caveat travels with the decision, not just with the evidence layer's
   own documentation.

**Disclosed limitation, not silently assumed away**: the floor-plus-
strict-inequality rule above is explicitly NOT a statistical
significance test (no confidence interval, no p-value, no correction for
multiple comparisons across 9+ buckets) -- it is a minimum-sample
tripwire plus a simple comparison, deferred exactly the way every other
not-yet-built refinement in this project has been deferred: named
honestly rather than either building it prematurely or pretending the
simpler rule is equivalent to it.

**Read-only verification tool**: new `scripts/selector_dry_run.py`
(mirrors milestone 13's `mode=ro` discipline) evaluates all 9 regime
buckets plus `"untagged"` against a real database and prints what
`RollingPerformanceSelector` would choose without selecting anything
live. Run against a scratch, head-migrated database, it reproduced the
expected result -- `legacy` in all 10 buckets, each for the
insufficient-live-baseline reason -- matching
`docs/REGIME_PERFORMANCE_ANALYSIS.md`'s own prediction (decision #54)
that a correctly built selector would route Legacy in 9/9 buckets on
today's evidence. This is a real, running verification of that
prediction, not a re-assertion of it.

**Why it ships unwired**: nothing in milestones 13-16 changes what
selector `scripts/run_paper.py` actually calls -- `AVAILABLE_STRATEGIES`
and both production selectors (`DefaultToLegacySelector`,
`ConfigurableFallbackSelector`) are byte-for-byte untouched. Wiring
`RollingPerformanceSelector` into the live path is a future, explicit
OPERATOR decision, gated on sufficient accumulated evidence (which does
not yet exist in quantity -- this dry run's own result confirms that: 10
of 10 buckets are still baseline-unmeasured) -- not a decision this
documentation round or any single milestone is authorized to make
unilaterally.

**Status**: 14 new tests (rule-table coverage: each of the 6 steps
above, argmax ties, the shadow-marker, the min_samples parameter).
Combined with milestones 13-15 (decision #55) and the bugfix: full suite
**602 passed / 0 failed** (was 539 after milestone 12). Live paper
trader ran untouched throughout this entire round; production selection
behavior is unchanged.

## 57. Operating-model shift to continuous CTO-driven improvement, plus Milestone 17: multi-symbol shadow collection (17a) and daily CTO reporting (17b)

**Decision** (2026-07-16, operator directive): with adaptive-platform
milestones 1-16 complete, the mandate shifts from feature implementation
to continuous CTO-driven improvement. Specialist-agent roles (CTO /
Research / Strategy / Backtest / Risk / Monitoring / QA / Performance)
now operate without asking what to build next -- prioritization is by
bottleneck analysis (highest ROI given the current evidence gap), not by
a fixed roadmap queue. The CTO stops and asks only for: architectural
decisions, credentials, production deployment, or destructive actions.
**Promotion gates are unchanged and never bypassed** -- significant
edge, positive expectancy, lower drawdown, sufficient sample size,
multi-market confirmation, and regime validation, exactly as milestone
12's evidence rounds already established; Legacy stays the only
production engine under this new operating model just as it was under
the old one. Every milestone under this model still follows the same
discipline as every milestone before it: implementation + tests + docs +
changelog + architecture update + benchmark + commit + push, followed
automatically by an architecture review -> bottleneck analysis -> next
milestone. A daily morning CTO report (milestone 17b, below) is now
standing practice, not a one-off.

**Milestone 17a: multi-symbol shadow collection.** Bottleneck-driven --
`docs/REGIME_PERFORMANCE_ANALYSIS.md` found 8 of 9 regime buckets
evidence-starved, and the root cause was single-symbol (BTCUSDT-only)
collection. New `settings.SHADOW_SYMBOLS` (comma-separated, default `""`
-- byte-identical off): when shadow mode is on and this is set, the
existing shadow block in `run_paper.py` additionally fetches candles and
runs resolve+record for each extra symbol (ETH/SOL/XRP intended),
per-symbol fault-isolated so one symbol's fetch/resolve failure does not
take down the others. Results surface under
`summary["shadow"]["extra_symbols"]`, kept separate from the primary
symbol's own shadow summary.

**The exclude-nobody design point, worth recording deliberately**: on
extra symbols, no strategy is the ACTIVE strategy -- nothing trades
them, so `active_strategy_name=None` is passed into the shadow
evaluation, which excludes nobody. This means ALL six registered
strategies, INCLUDING `legacy` and `jade`, get shadow-evaluated on the
extra symbols, not just the four quarantined experimental ones. That is
intentional, not an oversight: it multiplies evidence for the single
scarcest resource identified by milestone 12/16 -- Legacy's OWN
per-bucket live sample count, which milestone 16's dry run showed
insufficient in 10 of 10 buckets. Trading logic never touches the extra
symbols at any point; only shadow observation runs there. 9 new tests
plus a real-temp-DB smoke test (rows written for both symbols compared
against active-only rows; the live DB was untouched by the smoke test).

**Milestone 17b: daily CTO report generator.** New `scripts/cto_report.py`
plus pure helpers in `app/portfolio/cto_report.py`, producing 8 fixed
sections: completed work (via `git log --since`), evidence accumulated
(via the shadow_status helpers), strategy rankings plus shadow
performance (via `collect_regime_evidence`, carrying forward decision
#55(e)'s shadow-optimism caveat), a `RollingPerformanceSelector` dry-run
bucket count, a mechanical disclosed bottleneck rule (fewer than 1
sufficient-evidence cell -> bottleneck is reported as "evidence
accumulation"), live risk checks (is the trader process running, is the
DB at migration head), a suggested next milestone quoted verbatim from
`ROADMAP.md`, and a completion percentage parsed from
`docs/ADAPTIVE_ARCHITECTURE.md` section 7 (labeled explicitly "of
currently-scoped milestones," never presented as the long-term vision's
completion). **Every section carries an explicit "unavailable: <reason>"
fallback and never fabricates a number it cannot derive from a live
source.** The DB is opened read-only (`mode=ro`, mirroring milestone
13's own discipline), output is ASCII-only, and the script writes its
report to a file before printing to console -- both conventions lifted
directly from decision #54's post-mortem. 22 new tests.

**A real bug, found and fixed during the build.** `subprocess.run(...,
text=True)` on Windows decodes captured `git log` output using the
process's default codepage (cp1252), not UTF-8 -- so any UTF-8
multi-byte commit-message character was already mangled by the time it
reached the report's own sanitizer; the sanitizer had nothing left to
sanitize correctly. Fixed with an explicit UTF-8 decode
(`errors="replace"`) ahead of any further processing. **This is the
SECOND cp1252-decoding lesson on this platform, after decision #54's
console-print crash** -- the pattern worth naming explicitly: every
user-facing or subprocess-facing text path on this Windows deployment
needs explicit encoding discipline; the platform default is never safe
to assume.

**First real run against the live DB**: 28 regime snapshots across 3
buckets, 0 shadow signals yet, 0 sufficient-evidence cells -> reported
bottleneck = evidence accumulation; trader process confirmed running; DB
confirmed at migration head `65aba13281ad`; completion 100.0% of the 16
currently-scoped section-7 milestones (explicitly not the long-term
vision, which the report does not claim to measure).

**Status**: full suite **602 -> 633 passed / 0 failed** (+31: 9 from
milestone 17a, 22 from milestone 17b). Live trader ran untouched during
the entire build; a restart with `SHADOW_SYMBOLS` set is a pending,
orchestrator-handled operational step that comes after commit, not part
of this code change (see `HANDOFF.md`).

---

## 58. Milestone 18: `docs/RESEARCH_ROUND_1.md`'s top-3 recommendations adopted -- delay-check promotion gate (18a), RiskManager ATR stop-distance floor (18b), realistic shadow-fill resolution v2 (18c)

**Decision** (2026-07-16): the Research department was tasked with
surveying established quant-trading technique against this platform's
four actual open problems, not a wishlist -- see `docs/RESEARCH_ROUND_1.md`
(committed, final). All top-3 recommendations were adopted and
implemented this milestone; each traces to a PROVEN failure mode already
observed on this platform, not a hypothetical one. **The research
discipline itself is worth recording**: the same round explicitly
REJECTED HMM/Markov-switching regime detection (real literature support,
but this platform's own `docs/REGIME_PERFORMANCE_ANALYSIS.md` already
diagnosed the bottleneck as trade-rate scarcity, not classifier noise --
a more persistent classifier would not increase Legacy's trade rate) and
DEFERRED the heavyweight statistical-comparison machinery (Deflated
Sharpe Ratio, Probability of Backtest Overfitting/CSCV, White's Reality
Check, Hansen's SPA test) as premature -- at this platform's actual
n=20-60 sample sizes, those techniques mostly agree with the existing
simple n>=20-floor-plus-strict-inequality rule, so building them now
would add real complexity for a bar the platform hasn't approached yet.
Evidence-over-hype working as designed: real citations, real constraints,
real "no" answers where the evidence didn't support a "yes."

**18a: `scripts/run_backtest.py --delay-check` -- execution-delay
robustness as a standard, repeatable promotion-gate check.** New
`delay_robustness_report(baseline_result, delayed_result,
max_pf_degradation=0.5)`: runs the SAME candles/config twice --
zero-delay and `entry_delay_candles=1` -- and compares. Passes only if
BOTH hold: `pf_retention >= 0.5` (disclosed-not-tuned -- chosen only as
"materially more forgiving than what the known failure case actually
produced"; the reference failure, `docs/ROBUSTNESS_REPORT.md` test 2,
retained only ~0.03, i.e. kept 3% of its baseline profit factor) AND no
profitable-to-unprofitable sign flip (checked independently, so a run
that exactly meets the retention threshold but flips sign still fails --
proven by a dedicated test that isolates sign-flip as the sole failure
cause). **Honest-edges discipline**: zero trades on either side, or an
undefined baseline PF (every baseline trade broke exactly even, a 0/0
ratio), yields `passed=None` with `insufficient_data=True` -- never a
fake pass, never a crash. Composable with `--strategy`/`--walk-forward`:
when both flags are set, a combined promotion-gate summary reports
walk-forward and delay-check as two independent gates plus one overall
verdict. 12 new tests.

**18b: `RiskManager.evaluate()` gains a minimum stop-distance-as-ATR-
multiple floor.** New optional parameters `stop_distance_atr_mult: float
| None = None` / `min_stop_atr_mult: float = 0.0`, following decision
#49's established pattern exactly: `RiskManager` never reads `settings`
for this threshold and never computes ATR itself -- the CALLER computes
`abs(entry - stop) / atr` and passes it in, plus its own chosen floor
(typically `settings.MIN_STOP_ATR_MULT`). Rejection reason
`"stop_distance_below_atr_floor"`. **Boundary convention deliberately
mirrors the existing `MIN_RR` gate**: exactly at the floor PASSES,
strictly below REJECTS -- one consistent boundary rule across both risk
gates rather than two different conventions a future reader would have
to remember separately. **Missing measurement never rejects**: if
`min_stop_atr_mult > 0.0` but the caller could not compute ATR (e.g.
insufficient candle history), the gate WARNS-and-allows rather than
rejecting -- missing data is not evidence of a tight stop, the same
best-effort-observability discipline already used elsewhere in this
codebase (e.g. shadow-mode signal recording). `settings.MIN_STOP_ATR_MULT`
defaults to `0.0`, which DISABLES the gate and preserves prior
`evaluate()` behavior exactly, including for signals with very tight
stops. **Enabling this gate changes trade acceptance and requires its own
A/B backtest evidence before flipping above 0.0 in paper trading** --
same "implemented is not evidenced" discipline as `USE_JADE_ENGINE`/
`ENABLE_BREAKEVEN`. **Root cause addressed, not just the symptom**: this
directly targets what `docs/ROBUSTNESS_REPORT.md` mechanistically traced
the platform's only fully cross-asset/cross-year-validated candidate's
execution-delay failure to -- an average stop distance of only
0.17-0.23% of entry price, tighter than routine single-candle price
movement, versus the Wilder-convention literature's standard practice of
sizing stops at 1.5-3.0x ATR. 6 new tests.

**18c: realistic shadow-fill resolution (v2), closing the fee-free/
zero-delay optimism gap in shadow evidence.** New migration
`6b085b904777` (down-revision `65aba13281ad`) adds
`shadow_signals.resolution_model` (nullable `String(32)`, purely
additive). `NULL` is the PERMANENT, honest label for every row resolved
under the old (milestone 14b) optimistic instant-fill model -- it is
never backfilled, because doing so would misrepresent one measurement
regime as another. Non-NULL rows carry the resolver's
`RESOLUTION_MODEL` constant (`"v2_realistic_fills"`) at the moment they
were resolved, leaving room for a future `"v3_..."` value the same
additive way. **The v2 resolver** (`app.portfolio.shadow_resolver`) now:
entry fills at the NEXT candle's open after `captured_at` (a 1-candle
delay, mirroring `docs/ROBUSTNESS_REPORT.md` test 2's own methodology),
adjusted by adverse-direction slippage; both entry and exit legs pay fees
using `paper_broker.py`'s real, already-in-use constants (not new
invented values); `resolved_r` is recomputed from the ACTUAL fill rather
than the originally recorded signal price. Concretely: on a stop hit,
`fee_cost = FEE_RATE * (fill_entry + stop_loss)`,
`resolved_r = -(risk + fee_cost) / risk` -- always strictly worse than
-1.0R since `fee_cost > 0`, whether an ordinary intra-candle stop touch
or an entry-candle gap-through (a gap-through-stop is resolved honestly
as worse than -1R, never floored at exactly -1R). On a TP hit,
`fee_cost = FEE_RATE * (fill_entry + take_profit)`,
`resolved_r = (abs(take_profit - fill_entry) - fee_cost) / risk`. A
gap-past-TP-before-fill case is excluded as a missed entry
(`outcome="expired"`, `resolved_r=None`) rather than optimistically
credited as a win the platform was never actually filled into -- counted
separately in the resolver's summary (`missed_entries`, a subset of
`expired`) so it's distinguishable from an ordinary time-based expiry.
**`collect_regime_evidence()` (milestone 15) now counts ONLY rows with
`resolution_model == "v2_realistic_fills"` toward `n`** -- old
(`NULL`) rows and rows resolved under any other model are excluded from
`n` and counted in `n_excluded` instead, so the two measurement regimes
(optimistic upper bound vs. fee/slippage/delay-adjusted) are never
silently blended into one evidence pool, the same pooling-discipline
principle that module's own docstring already established for
shadow-vs-live blending. The disclosed shadow-optimism caveat itself
softens accordingly, from "simulated fee-free instant fills" to
"simulated but fee/slippage/delay-adjusted fills" for every v2-resolved
row going forward.

**Status**: full suite **652/652 passed / 0 failed** at commit time
(18a 12 tests + 18b 6 tests + 18c's migration/resolver/evidence-layer
tests). Committed as `4fe7496` WITHOUT this documentation round -- a
session-limit boundary forced securing the verified code first (two
sub-agents were killed mid-flight by the limit; the orchestrator ran the
full QA gate itself and committed to avoid losing the work). This entry
closes that docs debt. **Same-day ops** (tracked in `HANDOFF.md`/
`ROADMAP.md`, not part of this code change): the live paper-trading DB
was migrated to head `6b085b904777`, and the trader was restarted with
the v2 resolution model active plus 4-symbol shadow collection
(milestone 17a's `SHADOW_SYMBOLS`) running.

## 59. Milestone 19: backtester quadratic-scan fix in `detect_order_block` -- reverse-scan early-exit, a declined rolling-sum micro-optimization, and a three-namespace monkeypatch lesson

**Decision** (2026-07-16): a profiling round (measurement-only, prior
session, interrupted by the session usage limit and flagged as a pending
item in milestone 18's own writeup) diagnosed the backtest engine's
scaling as effectively quadratic -- a log-log exponent of ~2.26 measured
across 500/1000/2000/3000-candle runs on real BTCUSDT data, not a
synthetic worst case. `detect_order_block()` accounted for 62.6% of
total runtime; `is_zone_mitigated()` was a distant #2 at 22.2% (O(n) FVG
zones times per-step scans); the `cf()` OHLCV accessor contributed a
large constant factor to self-time (~40%, 220M calls at n=3000) without
being asymptotically responsible for the quadratic shape itself.
Slicing (`ltf_candles[:i+1]`, the thing most likely to be blamed on
sight) was measured and ruled out as the cause -- under 0.2% of runtime.
`order_block.py::detect_order_block()` was rewritten to scan
newest-to-oldest and return the FIRST qualifying match (an impulse
candle with an opposite-color prior candle), replacing the old
oldest-to-newest forward scan that recomputed a fresh 15-candle
average-range window at every history position on every walk-forward
step while only the LAST qualifying match it found ever survived to be
returned.

**Why the reverse scan is provably the same answer, not just a faster
one**: the old forward scan's "keep overwriting the result on each new
qualifying match" behavior means it always returned the newest
qualifying match in the scanned range -- exactly what a newest-to-oldest
scan finds on its FIRST hit. The two loops therefore terminate at the
identical candle by construction; the reverse scan just stops looking
the moment it finds it instead of continuing to re-examine (and
re-average) every older candidate that could never have won anyway. Both
of the forward loop's existing traps were deliberately preserved rather
than "cleaned up" during the rewrite: a candle whose impulse fails to
qualify must continue the scan toward older candidates (not treated as a
stopping condition), and a doji candle must do the same -- changing
either would silently change which candle gets returned, not just how
fast the answer arrives.

**Two things this round considered and did NOT do**:
- **Window-capping history** (limiting how far back any detector scans)
  was explicitly REJECTED as behavior-unsafe, not just out of scope.
  Sweeps, FVGs, and CHoCH legitimately reference arbitrarily old
  structure in this strategy's own logic (see `docs/strategy_spec.md`);
  capping the lookback would change what trades get generated, not just
  how fast they're computed -- exactly the kind of silent behavior change
  this project's "measure before changing, verify bit-identical after"
  discipline exists to prevent.
- **A rolling-window sum for the 15-candle average-range computation**
  (maintaining a running total by adding the newest candle's range and
  subtracting the oldest, instead of recomputing `sum()` fresh every
  step) was implemented and tested, then DROPPED. Floating-point
  addition/subtraction is not associativity-safe -- a rolling sum that
  adds then subtracts accumulates rounding error along a different path
  than a fresh sum every time, and this round's own verification bar
  (below) was BIT-IDENTICAL output, not "close enough." The rolling-sum
  variant failed that bar on real data. Rather than relax the bar to let
  a small extra speedup in, the bar was kept and the optimization was
  declined -- correctness-under-the-established-standard over marginal
  additional speed.

**Verification (the part of this round worth recording as a pattern for
future performance work)**: two independent checks, not one. First, a
property test built against a VERBATIM reference copy of the old
forward-scan implementation (kept in the test file specifically so the
comparison isn't "new code vs. its own memory of the old behavior") run
over 5,200 seeded synthetic candle series, including adversarial modes
designed to stress the forward loop's two traps -- 0 mismatches. This
property test is now a permanent regression test, not a one-time check
discarded after the round. Second, a golden run on real, anchored data
(BTCUSDT 15m, 2000 candles, `end_time_ms` fixed at 2026-06-27 so the
fetch is reproducible) across all 4 meaningfully different flag
combinations this codebase supports (default / `use_breaker_block` /
`use_structure_tp` / `use_jade_engine`) -- old-vs-new trade lists
compared deep-equal at exact float precision, not a tolerance-based
comparison. **A genuine subtlety surfaced by the golden run**: three
separate modules (`signal_engine.py`, `entry_point_engine.py`,
`htf_ltf_confluence.py`) each bind `detect_order_block` into their own
module namespace at import time (`from ... import detect_order_block`),
so patching only `order_block.py`'s own module attribute during the
old-vs-new comparison silently left two of the three call sites still
calling the NEW code under a false "old" label. The golden-run harness
had to patch all three namespaces explicitly for the comparison to be
valid -- a reusable lesson for any future change to a widely-imported
detector in this codebase, not specific to this optimization.

**Measured speedup** (unprofiled, real wall-clock timing, not a
profiler's self-reported number): 1000 candles 4.32s -> 1.81s (2.39x),
2000 candles 16.15s -> 7.09s (2.28x). Practical consequence:
Milestone-10-style evidence rounds (`--candles 3000 --periods 6`, this
project's standard scale) drop from roughly 40 minutes to roughly 17.

**Deferred, not scheduled**: Fix B (incremental zone-mitigation caching
for `is_zone_mitigated()`, the remaining ~22% of runtime) was
deliberately NOT attempted this round -- it requires maintaining
cross-walk-forward-step state inside a `SignalEngine` that is currently
stateless by design, a materially higher-risk change than a pure
algorithmic rewrite of one detector's internal scan direction. Revisit
only if the 2.3x speedup already delivered proves insufficient for a
future evidence round's actual needs -- not on a fixed schedule and not
because 22% is a round number worth chasing on its own.

**Status**: full suite **653/653 passed / 0 failed** (652 baseline from
milestone 18, +1 permanent property test). Code complete in the working
tree as of this entry; not yet committed (tracked in `HANDOFF.md`).

---

## 60. Milestone 20: the ATR stop-distance floor A/B-tested and REJECTED -- the A/B-first discipline vindicated, and the Legacy production baseline itself found delay-fragile

**Decision** (2026-07-16/17): milestone 18b built `RiskManager.evaluate()`'s
`min_stop_atr_mult` gate but shipped it default-`0.0` (disabled),
explicitly deferring enablement until A/B backtest evidence existed --
"implemented is not evidenced" (decision precedent already established
for `use_breakeven`/`use_partial_tp`/`use_breaker_block`). **20a** made
that gate A/B-testable: `BacktestEngine.run()` gained a
`min_stop_atr_mult` parameter and `scripts/run_backtest.py` gained
`--min-stop-atr`, computing ATR from the signal's own no-lookahead
slice (never a forward-looking window) and threading it into the same
caller-computed `RiskManager.evaluate()` contract milestone 18b built.
The disabled path (no flag passed) was proven byte-identical, not just
assumed: a test using a fake `RiskManager` that raises `TypeError` on
unexpected kwargs was run through the unflagged path, so the new
kwargs leaking into the disabled path would have failed the suite, not
just silently changed behavior. 7 new tests, full suite **669/669**.

**20b ran the A/B evidence round the gate was built for, and the floor
FAILED.** Methodology and full numbers: `docs/ATR_FLOOR_EVALUATION.md`
(final; cite, do not duplicate here). Identical BTCUSDT 15m anchor
(6x3000 candles, `--end-date 2026-07-10`, walk-forward + delay-check on
every config). **Baseline** (floor off, i.e. current production
behavior): 111 trades, +$3,400.62, 6/6 profitable periods, walk-forward
PASSED -- but delay-check FAILED (PF 5.024 -> 0.117 under one candle of
delay, retention 0.023, profit-to-loss sign flip). **1.5x floor**
(`docs/RESEARCH_ROUND_1.md` section 4a's literature-convention range,
pre-declared before any run): 60 trades (-46%), +$1,113.35 (-67%), only
3/6 profitable periods, walk-forward now FAILED, delay retention only
moved to 0.079 (still 6x below the 0.5 pass criterion), sign flip
remained. **2.0x was deliberately NOT run** -- an early stop, made by
the CTO after 1.5x's result was in, per this project's established
"don't burn compute on clearly-dead configs" discipline (same discipline
`docs/EXPERIMENTAL_STRATEGY_EVALUATION.md` section 4 already used
once). Reasoning for the stop: 1.5x moved retention 0.023 -> 0.079 while
simultaneously destroying walk-forward consistency and cutting net
profit by two-thirds; a strictly stricter 2.0x floor rejects strictly
more signals via the same mechanism, and there is no plausible path
from 0.079 to the 0.5 criterion that doesn't first explain why more of
a mechanism that is already making things worse would reverse rather
than deepen the result. The stop is recorded explicitly, including its
consequence (2.0x remains formally untested), rather than smoothed over.

**Verdict: ATR stop-distance floor REJECTED as a delay-robustness fix.
`settings.MIN_STOP_ATR_MULT` stays `0.0` (disabled) everywhere -- not
enabled in paper trading, not recommended for promotion.** Measured
against this project's keep-rule (must materially improve delay
retention / remove the sign flip AND not materially degrade net
profit/PF/drawdown), the floor failed both halves at once: delay
retention stayed 6x below the pass bar with the sign flip intact, while
net profit fell 67%, PF fell 53%, and walk-forward flipped PASS ->
FAIL. The floor's only observable effect was rejecting ~46% of signals
-- it thinned the trade population rather than selecting for
delay-robust entries; the ATR-scaled-stops-survive-one-candle
hypothesis from `docs/RESEARCH_ROUND_1.md` #2 is falsified on this
evidence. This is exactly the negative result section 4c of that
document pre-committed to recording honestly rather than quietly
adjusting the threshold to force a pass -- **the A/B-first discipline
built into 18b is vindicated**: a literature-backed, plausible-sounding
fix was rejected by its own pre-declared evidence before it ever touched
production, exactly what deferring enablement behind evidence is for.

**The headline finding is not about the ATR floor at all: production
Legacy itself fails the delay gate on this window.** The baseline row
above -- 6/6 profitable, walk-forward PASSED, the platform's only
production engine -- collapses under a single candle of execution delay
(PF 5.024 -> 0.117, sign flip, delay-check FAILED). This was previously
unknown: `docs/ROBUSTNESS_REPORT.md` test 2 delay-tested only the
(already-killed) `structure_tp` candidate; this is the first time the
Milestone 18a delay gate has been run against Legacy itself. Delay
fragility is therefore a property of the shared entry pipeline on this
window, not a defect isolated to one candidate. **Severity caveat,
stated plainly and not softened**: this anchor is 15m, so 1 candle of
delay = 15 minutes -- three times harsher than the 5-minute delay that
killed `structure_tp`. This does NOT show Legacy loses money at
realistic (seconds-scale) execution latency; what it does show is that
Legacy's backtested edge on this window lives entirely inside a
sub-15-minute execution window. Consequence for `docs/live_trading_checklist.md`
gate #4 (small live validation): verified low-latency execution
infrastructure -- measured signal-to-fill latency, not assumed -- is now
an explicit hard prerequisite, not an implicit assumption.

**Ops/process notes worth recording**: (1) an instrumentation gap --
`run_backtest.py`'s current output does not print how many signals the
floor rejected; the 111->60 trade-count drop is the observable proxy,
not a direct count, noted rather than inferred. (2) Wall-clock timing is
new evidence for the Fix B performance backlog (milestone 19's
deferred item): baseline run ~3h05m, 1.5x run ~1h17m, both far over the
~5-15 min/config estimate -- `--delay-check` triples engine passes
(three full runs per config), and 1.5x's ~2.4x faster wall time despite
identical candle counts suggests runtime scales with trade-management
volume, not just candle count. (3) One background-task harness kill
(a first baseline attempt, launched as a harness background task, was
killed by the task runner after ~1h with no output) was worked around by
launching the successful runs as detached OS processes. (4) The live
paper trader was killed once by that same harness cleanup and was
relaunched immediately on latest source (including Milestone 21
alerting) -- unrelated to the evaluation itself, noted for continuity.

**Status**: 20a code-complete in the working tree, full suite
**669/669 passed / 0 failed**. 20b is a read-only evidence round --
no orders placed, no writes to `backend/paper_validation.db`. Full
evidence: `docs/ATR_FLOOR_EVALUATION.md` (final).

---

## 61. Milestone 22: Fix B's deferral assumption corrected by consumer-semantics analysis (FVG mitigation-scan quadratic term eliminated); Milestone 23: risk-rejection observability, purely additive

**(a) Milestone 22 (2026-07-17).** Decision #59 deferred "Fix B"
(incremental zone-mitigation caching for `is_zone_mitigated()`, the
~22% of runtime `is_zone_mitigated` accounted for after #59's own fix)
on the stated assumption that closing it required maintaining
cross-walk-forward-step STATE inside a `SignalEngine` that is currently
stateless by design -- judged materially higher-risk than #59's own
pure algorithmic rewrite of one detector's scan direction. This round
found that assumption **wrong, not just outdated**: no stateful caching
was needed at all. The round-1 reasoning was an honest architectural
guess made without inspecting the actual consumer (#59's own scope was
`order_block.py`, not the FVG call site) -- not a mistake in judgment
given what was known at the time, but a gap that closer reading of the
consumer closed.

**The discovery**: `entry_model.build_entry_model` only ever extracts
ONE fact from the FVG zone list `SignalEngine` hands it --
`matching_fvgs = [z for z in fvg if z["type"] == wanted_type];
fvg_zone = max(matching_fvgs, key=lambda z: z["index"])`, the
highest-index zone whose `type` matches `wanted_type`. `wanted_type` is
provably identical to `bias` itself: `build_entry_model` returns `None`
before `wanted_type` is ever derived unless `bias in ("bullish",
"bearish")`, and for those two surviving values `wanted_type` collapses
to exactly `bias` (`direction == "long"` iff `bias == "bullish"`). The
OLD code in `signal_engine.py`, unaware of this, eagerly ran
`is_zone_mitigated` on EVERY historical FVG zone of BOTH types, every
walk-forward step -- 965,864 calls in the round-1 profiling run, 22.2%
of total runtime -- just to build a list `build_entry_model` would
immediately collapse to a single argmax pick.

**The transform**: new `app.strategy.signal_engine.
_select_unmitigated_fvg_zones(ltf_candles, bias)` short-circuits neutral
bias to `[]` immediately (`build_entry_model` returns `None` on that
path before ever touching its `fvg` parameter, so the skipped zones are
provably unobservable), and for `"bullish"`/`"bearish"` delegates to new
`app.strategy.fvg.find_latest_unmitigated_fvg_zone(candles,
wanted_type)` -- a single reverse scan (newest candle first) that fuses
gap detection, type filtering, and mitigation checking with an early
exit at the first match. This is the identical deferral-inversion
pattern #59 established for `detect_order_block`, applied one function
deeper in the call graph: `detect_fair_value_gap`'s loop body at a given
`i` reads only `candles[i-1]`/`[i]`/`[i+1]` -- no running total, no
cross-iteration state -- so the SET of qualifying `i` values and each
one's `type`/`top`/`bottom` is independent of scan direction. Visiting
`i` newest-to-oldest therefore finds the exact same zones
`detect_fair_value_gap` would, merely in reverse discovery order, so the
first hit that matches `wanted_type` and passes `is_zone_mitigated` is,
by construction, the same zone the old eager-detect-then-filter-then-
argmax pipeline would have selected. `detect_fair_value_gap` itself is
left completely UNTOUCHED -- its other two consumers
(`entry_point_engine.py`, `htf_ltf_confluence.py`) need the full ordered
zone list for their own different consumption patterns; every call site
was grepped to confirm neither is affected.

**Why the M19 playbook generalized rather than needing a new one**: the
lesson decision #59 left behind ("verify what a caller actually
consumes from an eagerly-computed result before assuming a hot path
needs new state or a fancier algorithm") applied here without
modification -- the only new step was reading `build_entry_model`'s own
consumption of the FVG list closely enough to notice the argmax
collapse, the same category of work that made #59's own reverse-scan
possible for `order_block.py`.

**Verification, the same bar #59 set**: two independent property tests
(5,200 seeded synthetic candle series each) -- `test_strategy_fvg.py`
checks `find_latest_unmitigated_fvg_zone` against a verbatim reference
of `detect_fair_value_gap` + eager `is_zone_mitigated` filtering;
`test_strategy_signal_engine.py` checks `_select_unmitigated_fvg_zones`
against a verbatim reference of the old inline `signal_engine.py`
logic -- 0 mismatches on both, now permanent regression tests. A golden
run on anchored real BTC data across the same 4 flag combinations #59
used (default / `use_breaker_block` / `use_structure_tp` /
`use_jade_engine`) -- old-vs-new trade lists deep-equal 4/4. The
namespace-binding trap that caught out #59's golden run (three modules
binding `detect_order_block` at import) was checked here too and found
NOT to recur: grepping every importer of the touched functions shows
only `signal_engine.py` binds `_select_unmitigated_fvg_zones`/
`find_latest_unmitigated_fvg_zone` -- a strictly simpler namespace
picture than #59's three-way monkeypatch requirement, not assumed
identical just because the shape of the fix rhymed.

**Measured**: n=1000 1.693s -> 0.933s (1.81x), n=2000 7.484s -> 3.172s
(2.36x); `is_zone_mitigated` call count 965,864 -> 11,141 (~87x fewer
calls); the FVG-mitigation chain is now 1.68% of total runtime (down
from 22.2%), and `detect_fair_value_gap`'s own forward scan no longer
appears anywhere in this path's hot loop. **New dominant costs**:
`find_swing_highs`/`find_swing_lows` and the `cf()` OHLCV accessor --
out of this round's scope, recorded here as the natural next-round
candidate rather than chased opportunistically. Combined with #59's
2.3x, full-scale evidence rounds (`--candles 3000 --periods 6`) are now
roughly **5x faster than the pre-M19 baseline**.

**Status**: full suite **692/692 passed / 0 failed**. Code complete in
the working tree as of this entry; not yet committed (tracked in
`HANDOFF.md`). Full report: `docs/PERFORMANCE_M22.md`.

**(b) Milestone 23 (2026-07-17, committed `3e508d8`).**
`BacktestResult` gains `risk_rejections: dict =
field(default_factory=_empty_risk_rejections)`, shape
`{total_signals, approved, rejected, by_reason}`. **Purely
observational**: `BacktestEngine.run()` already computes and branches on
a `risk_decision` from `RiskManager.evaluate()` for every non-`None`
signal; this milestone only counts what that call already decided -- it
never changes control flow, which trades happen, or any existing field.
`total_signals` increments on every non-`None` signal that reaches a
risk-evaluation call (`== approved + rejected`, since each such signal
is evaluated exactly once); a rejected decision's `reasons` (verbatim
`RiskDecision.reasons` strings) each increment their own `by_reason`
key.

**Why `sum(by_reason.values()) >= rejected` is the correct invariant,
not `==`, by design**: `RiskManager.evaluate()` deliberately does not
short-circuit on the first failing check (documented in its own
docstring) -- a single rejected signal can fail multiple independent
gates at once (e.g. RR-below-floor AND a loss-limit breach in the same
evaluation), and every reason it returns is tallied. A multi-reason
rejection therefore legitimately increments more than one `by_reason`
key for one `rejected` increment. `aggregate_risk_rejections()` (which
sums `risk_rejections` across `--periods` runs) preserves this same
relationship rather than forcing equality.

**Why default-populated on every path, including the below-`MIN_CANDLES`
early return**: `_empty_risk_rejections()` is both the dataclass field's
`default_factory` and `run()`'s own starting accumulator, so every
`BacktestResult` -- including ones that never reach the walk-forward
loop at all -- carries the identical zero-populated shape. A consumer
can always read `result.risk_rejections["total_signals"]` without a
`getattr`/`None` guard, the same "always audit-able, never a missing
key" discipline this project already applies to `MarketRegime.metrics`
and other structured outputs.

**Why this milestone, and why now**: closes the instrumentation gap
decision #60 named explicitly -- during the ATR-floor evidence round
(milestone 20b), the runner could observe the 111->60 trade-count drop
under `--min-stop-atr 1.5` but could not report how many signals the
risk gate itself rejected or why, forcing that round to treat the
trade-count delta as an inferred proxy rather than a direct count.
Every future evidence round now reports a direct, itemized count.

**Runner behavior** (`scripts/run_backtest.py`):
`format_risk_rejection_line()` renders a compact "signals X, approved Y,
rejected Z, top reasons: ..." line (top 3 reasons by count, ties broken
by first-seen order, "top reasons: none" when `by_reason` is empty --
never a crash, never a misleading empty string). Per-period lines print
only when that period's `rejected > 0` (quiet runs stay quiet); the
aggregate line across `--periods` always prints regardless of whether
any rejections occurred, giving the reader one guaranteed place to see
the whole sample's risk-gate picture in a single line.

**Status**: full suite **690/690 passed / 0 failed** at commit time.
Purely additive -- no behavior change to which trades happen, in
backtest or anywhere else.

---

## 62. Milestone 24: the cross-year discipline applied to the platform's own headline finding -- Legacy's delay fragility is STRUCTURAL, plus the MAX_TRADES_PER_DAY discovery

**Decision context**: milestone 20b found that production Legacy itself
fails the 1-candle (15-minute) execution-delay gate on the standard 2026
window (PF 5.024 -> 0.117, retention 0.023, sign flip) -- a genuinely
uncomfortable finding about the project's ONLY production engine. Every
other finding this project has elevated to "settled" status (break-even's
cross-asset-then-cross-time coin flip, partial TP's -32.6%/-32.1%
reproduction, the tuned defaults' BTC-2025 spot-check) was required to
clear a cross-year check before being trusted as more than a
single-window artifact. This decision record is about applying that same
bar to the platform's own headline finding, not exempting it because the
alternative -- running the check and risking a WORSE number -- would be
more comfortable to skip. The discipline was applied uniformly.

**Method**: one pre-declared run, the identical standard 2025 BTC anchor
every prior cross-year round in this project has used, one config, no
parameters tuned, no code touched (`docs/LEGACY_DELAY_ROBUSTNESS.md` has
the full methodology and every number; cited, not duplicated here). The
run first reproduced the known BTC-2025 baseline profile to the cent
($1,714.56, 6/6 profitable periods, 35.4% second-half walk-forward
retention) before the delay numbers were trusted -- comparability
verified, not assumed. That walk-forward FAIL is the pre-existing,
already-documented BTC-2025 degradation, correctly attributed as known
context and not a new finding of this round.

**Result and verdict**: 2025 baseline PF 4.593 -> delayed PF 0.068,
retention 0.015 (WORSE than 2026's 0.023), sign flip, delay gate FAILED.
**STRUCTURAL** -- fails both tested years, and fails slightly worse in
the year with a materially different regime (65 trades, degrading
walk-forward vs. 111 trades, passing walk-forward in 2026). The
regime-dependent hypothesis -- that the 2026 collapse was an artifact of
that window's specific conditions -- is falsified: a regime this
different moved retention the WRONG direction (0.023 -> 0.015) if the
hypothesis were true. `docs/ADAPTIVE_ARCHITECTURE.md` gate #4's
requirement note is updated from "observed in the 2026 window" to
"structural property of the Legacy strategy family, confirmed across two
independent years (2025, 2026) on BTCUSDT" -- the requirement itself
(verified low-latency execution as a hard prerequisite) does not change;
only its justification strengthens from single-window to cross-year.
Caveats carried forward honestly: one asset (BTCUSDT only, no ETH/SOL/XRP
delay evidence exists), 15-minute delay granularity (cannot resolve
sub-15-minute failure points), and 2024 remains untested -- "structural"
here means "not explained by the 2026 regime," not "proven in all
possible regimes."

**Second finding, and why it is recorded but not acted on**: milestone
23's risk-rejection instrumentation (decision #61(b)) got its first real
use in an evidence round here, and it changed the read on 2025's low
trade count. Of 869 raw signals generated in the 2025 window, 804
(92.5%) were rejected, and every rejection reason that fired anywhere in
the log was the same one: `trades_today 2 reached MAX_TRADES_PER_DAY 2`.
2025's thin trade count (65 vs. 2026's 111) is therefore not evidence of
a quiet signal regime -- the entry pipeline generates signals far faster
than the daily cap lets them through. This has a direct implication for
`docs/REGIME_PERFORMANCE_ANALYSIS.md`'s prior framing of "Legacy trades
too selectively" as the cause of 8/9 evidence-starved regime buckets:
that framing is now known to be substantially a `MAX_TRADES_PER_DAY=2`
effect rather than a property of the signal-generation logic itself.
**Why this is recorded as an insight and NOT a recommendation to raise
the cap**: `MAX_TRADES_PER_DAY` is a risk-limit constant, not a
signal-quality parameter -- changing it changes real trading behavior
(position frequency, aggregate risk exposure) in a way that would need
the same A/B-evidence-before-enabling discipline this project applies to
every other risk-affecting change (`MIN_STOP_ATR_MULT`, `ENABLE_BREAKEVEN`,
etc.), and it is explicitly an operator-gated decision since it trades
off evidence throughput against a deliberately chosen risk ceiling. This
round observes and discloses the effect; it does not propose touching
the cap.

**Operational validation, worth recording on its own**: the full 2025
round (fetch + baseline + delayed + walk-forward passes) completed in
~11 minutes, against ~3h05m for the equivalent pre-milestone-22 2026 run
-- the milestone 19 (`detect_order_block` reverse-scan) and milestone 22
(FVG mitigation-scan) performance work is now validated by a real
production-scale evidence round completing at the expected fast speed,
not just isolated micro-benchmarks.

**Status**: evidence collection only, read-only, no orders, no writes to
`backend/paper_validation.db`, no code touched. Full report and every
number: `docs/LEGACY_DELAY_ROBUSTNESS.md`.

---

## 63. Milestone 25: the Hypothesis Agent and pre-registration discipline's first real exercise -- H4 verdict applied literally, reported MIXED, no clean branch forced

**Decision context**: operator directive (2026-07-17) formally expanded the
operating model to a research-company loop with named agent roles --
Research, **Hypothesis (NEW)**, Experiment, Evaluation, Ranking,
Promotion, Shadow, Regime, Risk, Monitoring, QA, Performance,
Documentation, CTO. The Hypothesis role's job is to generate falsifiable,
mechanism-grounded, pre-registered strategy hypotheses -- not backtest
results, not new strategy code, but a declared mechanism + external
citation + exact experiment invocation + exact keep-rule, all written down
BEFORE any run happens. `docs/HYPOTHESES_ROUND_1.md` is the first
deliverable of this new role: 5 hypotheses (H1-H5), ranked by
(evidence-grounding x testability) / cost, each with its keep-rule
declared in the document itself, plus 7 explicitly rejected directions
with citations for why. This is the same "pre-register before you look at
results" discipline this project has always applied to A/B evidence
rounds (decision #14/#15's "reproduced must specify what varied," the
walk-forward/delay-gate PASS criteria fixed before any run) -- Milestone
25 is the first time it was applied one level up, to hypothesis
*generation* itself, not just to a single experiment's pass/fail bar.

**Why H4 ran first, and what it actually was**: the ranking table put H4
(closing the backtest/live position-sizing gap) at rank 1 despite it not
being a search for new edge -- it is a verified, present-tense code fact.
Milestone 7 (decision #49, 2026-07-15) shipped volatility-scaled position
sizing (0.5x scalar in `high_volatility` regimes) live into paper trading
(`scripts/run_paper.py`). `BacktestEngine.run()` never passed the
`volatility` argument to `calculate_position_size(...)`. The consequence:
every backtest number in this platform's entire evidence base
(`docs/REGIME_PERFORMANCE_ANALYSIS.md`, `docs/LEGACY_DELAY_ROBUSTNESS.md`,
`docs/ATR_FLOOR_EVALUATION.md`, `docs/PROFITABILITY_EXPERIMENT_REPORT.md`)
was computed at a uniform 1.0x scalar that live trading has not actually
run since 2026-07-15. H4 was chosen first specifically because its result
conditions how every other hypothesis's future numbers should be read --
cheapest experiment in the round (cost 1 of 5), zero promotion risk (the
mechanism is already live regardless of the answer).

**The verdict-application story, the real discipline win of this
milestone**: `docs/H4_SIZING_PARITY_RESULTS.md` ran the pre-registered
`--vol-scaled-sizing` flag (opt-in, default off, mirrors `run_paper.py`'s
exact fail-open pattern) across the same 3-year BTCUSDT anchor
(2024/2025/2026) already used for every other cross-year round in this
project, and applied H4's own 3-branch keep-rule *literally*, per year,
then in aggregate -- not softened toward whichever branch looked
cleanest. The three years did not land on the same branch: 2024 matched
the "drawdown improves AND PnL/PF materially unchanged" branch, 2025
matched the "nothing moves materially" branch, and 2026 alone (Net PnL
-14.42%, outside the ~10% materiality band) triggered the "Net Profit
materially degrades" branch -- even though 2026's drawdown *also*
improved (-13.4%), because the first bullet requires both halves to
co-occur in the SAME year, and they didn't. The first bullet's own
explicit "at least 2 of 3 years" bar was checked honestly (drawdown
improves in 2024 AND 2026, but PnL/PF is only "unchanged" in 2024 of
those two) and found to clear only 1 of 3 -- not 2. **The verdict is
reported as MIXED, not rounded to whichever single branch would have
made a cleaner story.** This is the same "a hypothesis earns a KEEP only
if the pre-declared criterion is met on the pre-declared anchors,
evaluated after the run, not adjusted to fit the result" ground rule
`docs/HYPOTHESES_ROUND_1.md` itself inherited from every prior evidence
round -- the first time this project's pre-registration discipline was
tested against a keep-rule that genuinely didn't resolve cleanly, and it
held: no branch was stretched, no year was dropped to make the count
work, and the honest "no single bullet covers all three years" read was
reported as such.

**The operator-relevant finding, and why no recommendation was made**:
per the keep-rule's own second bullet (triggered by 2026 alone, which
carries no minimum-year-count qualifier in the original text), the
finding is stated plainly: Milestone 7's disclosed-not-tuned, currently
live 0.5x volatility scalar shows a real, asset/year-dependent cost --
most pronounced in 2026 (-14.4% Net PnL for a -13.4% relative
worst-period drawdown improvement), much smaller in 2024 (-2.4% PnL,
within the unchanged band), absent in 2025 (both metrics flat).
**`docs/H4_SIZING_PARITY_RESULTS.md` explicitly does not recommend
changing the live scalar** -- this is squarely an operator decision, the
identical boundary decision #62 already drew around `MAX_TRADES_PER_DAY`:
a risk-limit-adjacent parameter's cost/benefit tradeoff can be measured
and disclosed by this department, but whether to act on it is not a
CTO-mode or Documentation-mode call. The finding gives the operator
evidence that did not exist before this round; it does not decide for
them.

**Footnote-check outcome**: the first keep-rule bullet's "re-open every
existing finding whose headline number could plausibly move" instruction
is conditioned on its own 2-of-3-years bar clearing, which it did not --
but the check was run anyway, in the instruction's spirit rather than by
the letter. Delay-gate PF retention moved by <=0.002 in all three years
under vol-scaled sizing (2026: 0.023->0.025; 2025: 0.015->0.015; 2024:
0.026->0.025) -- noise at a scale where the pass criterion is 0.5, twenty
times the largest observed value. Walk-forward verdicts were unchanged in
both direction and reason in all three years. **No footnote correcting
`docs/LEGACY_DELAY_ROBUSTNESS.md`'s STRUCTURAL, 3-for-3 verdict is
warranted** -- it is now confirmed to hold under both the sizing model
this platform's evidence base used and the sizing model actually live in
paper trading. One open caveat was flagged, not resolved, this round: any
finding elsewhere resting on Net Profit margins narrower than roughly
10-15% could plausibly flip under vol-scaled sizing and would need a
targeted re-check before being treated as final.

**Coordination note**: two agents briefly worked from the same in-progress
2025 backtest output during this round; the orchestrator caught the
overlap before either wrote a conclusion from partial data and serialized
the two runs -- no data corruption, no incorrect number was ever recorded
in either final document.

**Status**: read-only evidence round, no code touched beyond the already-
implemented, already-tested `--vol-scaled-sizing` flag (78 focused tests
passing at implementation time). Full suite 701/701 at commit time (up
from 692). Full reports, cited not duplicated: `docs/HYPOTHESES_ROUND_1.md`,
`docs/H4_SIZING_PARITY_RESULTS.md`.

---

## 64. Milestone 26: H1 (quality-ranked signal selection within the fixed daily cap) evaluated and REJECTED -- a second confirmation that stricter/smarter filtering doesn't beat raw throughput on this platform

**Decision context**: `docs/HYPOTHESES_ROUND_1.md` section 2's own
ranking put H1 second, right after H4 (decision #63) -- it directly
targets the single largest disclosed, quantified opportunity in this
platform's evidence base: `docs/LEGACY_DELAY_ROBUSTNESS.md` §2 measured
that 92.5% (2025) and 89.1% (2024) of Legacy's raw signal stream is
rejected purely by `MAX_TRADES_PER_DAY 2 reached`, in FIFO
(chronological-arrival) order. H1 asks a narrower, safer question than
"raise the cap" (explicitly out of scope, operator-gated per decision
#62): holding the cap fixed at 2, does selecting the two highest-QUALITY
signals of the day, instead of the first two chronologically, improve
expectancy? New research-only harness `scripts/research_signal_selection.py`
(+ `backend/tests/test_research_signal_selection.py`, 15 tests) replays
each simulated day's full signal supply, ranks by a disclosed-not-tuned
score (`rr` = `TradeSignal.rr` alone; `rr_confluence` = `rr +
confluence_count`, both declared in `docs/HYPOTHESES_ROUND_1.md` §2
before any run), and takes only the top-`MAX_TRADES_PER_DAY` by score.
`RiskManager.evaluate()`'s live sequential-approval logic is untouched --
this is a research re-batching layer on top of `BacktestEngine`'s
existing, unchanged fee/slippage/fill/PnL mechanics. Full suite 716/716
(701 prior + 15 new).

**Baseline reproduction confirmed before trusting the comparison** (same
discipline decisions #14/#15 established): the harness's own
`chronological` variant matched the already-published FIFO baseline
exactly in both anchors -- Net Profit to the cent (2025: $1,714.56, 2026:
$3,400.62), trade count, profitable-period count, and walk-forward
outcome all byte-for-byte identical to `docs/LEGACY_DELAY_ROBUSTNESS.md`/
`docs/ATR_FLOOR_EVALUATION.md`.

**Result, applying H1's own pre-registered keep-rule literally**: quoting
it verbatim, "KEEP ... only if a ranked variant beats the chronological
baseline on Net Profit AND Profit Factor in BOTH the 2026 and 2025
anchors ... A ranked variant that wins one year and loses the other, or
wins on PF but not Net Profit, is REJECT." `rr` wins Profit Factor in
BOTH anchors (+6.5% 2026, +138.3% 2025) but LOSES Net Profit in BOTH
anchors (-24.1% 2026, -4.1% 2025) -- disqualified directly by the rule's
own explicit PF-without-Net-Profit REJECT clause, independently in both
years, not a close or ambiguous case. `rr_confluence` loses both metrics
in both anchors outright. **VERDICT: REJECT for both variants.** Unlike
Milestone 25's H4 (decision #63), which genuinely did not resolve to one
branch of its own keep-rule and was honestly reported MIXED, H1's
keep-rule resolves cleanly here -- this is a straightforward negative
result, not an ambiguous one requiring interpretation.

**Mechanism, the substantive finding of this round**: both ranked
variants realize markedly fewer trades than the chronological baseline
under the SAME fixed `MAX_TRADES_PER_DAY=2` cap (2026: `rr` 82 /
`rr_confluence` 77 vs. baseline 111; 2025: `rr` 43 / `rr_confluence` 46
vs. baseline 65) -- a disclosed structural property of the harness: a
day's top-scored candidates can cluster in time such that after the
first fills, the second-ranked candidate's window overlaps the
still-open first trade and is skipped rather than force-opened
concurrently, whereas chronological FIFO naturally spreads fills as
signals arrive live instead of retrospectively cherry-picking the best
two of a whole day's supply. Quality-ranking traded away raw trade
throughput for higher per-trade selectivity (visible in the PF-per-trade
improvement, sharpest in 2025's `rr` at +138.3%) -- but that throughput
loss cost more aggregate Net Profit than the per-trade quality gain
recovered, in both tested years without exception. **Reading: on this
platform, Legacy's edge scales more with trade FREQUENCY under the fixed
cap than with per-trade selectivity.** This reinforces two standing
findings rather than introducing a new direction: (1) `docs/strategy_spec.md`
§6's existing evidence that `require_full_confluence=True` does not
reliably produce higher-quality trades -- `rr_confluence` performing
WORSE than plain `rr` on both metrics in both years is a second,
independent data point in the same direction, since adding
confluence-count to the ranking score actively hurt rather than helped;
(2) the already-disclosed, deliberately not-acted-on cap-rejection
finding (decision #62) -- H1 tested whether smarter selection within the
fixed cap could recapture some of that discarded opportunity without
touching the cap, and found it cannot (at least not via these two
scoring functions); the opportunity structurally requires trade
THROUGHPUT, i.e. raising the cap itself, which stays explicitly
operator-gated per decision #62's own boundary, not something this
result argues for changing.

**Secondary, non-deciding observation**: `rr`'s 2025 walk-forward PASSED
where the chronological baseline's own 2025 result is a known,
already-documented FAILURE (degradation). Recorded as an interesting
directional note, not a rescue -- Net Profit already disqualifies `rr`
under the pre-registered rule, and the rule treats walk-forward only as a
non-regression check, not a substitute pass condition.

**One disclosed, un-root-caused discrepancy, flagged as a standing
follow-up**: the harness's own computed Profit Factor for the
`chronological` (baseline-reproducing) variant is consistently LOWER than
the previously-published baseline PF for the identical run -- 2026: 4.378
vs. published 5.024; 2025: 3.498 vs. published 4.593 -- despite Net
Profit, trade count, profitable-period count, and walk-forward outcome
all matching byte-for-byte in both years, isolating the gap to PF
computation specifically. Plausible cause (not verified this round): a
per-period-averaged PF vs. a pooled-gross-profit/gross-loss PF, which
diverge whenever period-level gross profit/loss ratios vary across this
project's 6-period splits. **Does not affect this round's verdict**
(Net Profit is the deciding metric per section 3 of the full report, and
it reproduced exactly) -- but this harness's PF output should not be
treated as directly comparable to `run_backtest.py`'s own PF until
root-caused, and should be resolved before `scripts/research_signal_selection.py`
is reused for a future hypothesis round.

**Promotion path**: NONE -- REJECT, same as H4's operative outcome for
the live scalar question. Even a KEEP would not have been a promotion by
itself, per H1's own pre-registered text (`docs/HYPOTHESES_ROUND_1.md`
§2's "Promotion path if KEEP") -- moot here. Legacy's live/paper trading
behavior is completely unchanged by this milestone: `RiskManager.evaluate()`,
`scripts/run_paper.py`, and `BacktestEngine` internals are all
byte-for-byte unchanged, confirmed during implementation. No orders
placed, no writes to `backend/paper_validation.db`.

**Status**: read-only evidence round. Full suite 716/716 at evaluation
time (up from 701). Full report, cited not duplicated:
`docs/H1_SIGNAL_SELECTION_RESULTS.md`.

---

## 65. Milestone 27: H3 (regime-conditional delay survival of the `structure_tp` family) evaluated and REJECTED across all three standard anchors -- a cleaner, evidence-scarcity-compounded zero than H1's

**Decision context**: `docs/HYPOTHESES_ROUND_1.md` section 3's own
ranking put H3 third, right after H1 (decision #64) -- it combines three
already-built, already-independently-validated mechanisms
(`--structure-tp`, `--tag-regimes`, `--delay-check`) in a combination no
prior round had ever run together. `docs/PROFITABILITY_EXPERIMENT_REPORT.md`
§12-14 validated `use_structure_tp=True` as this platform's strongest
candidate family on raw profitability; `docs/ROBUSTNESS_REPORT.md` Test 2
separately found the SAME family catastrophically delay-fragile in
AGGREGATE (PF 5.24 -> 0.16 at a 5-minute delay), later confirmed
structural for Legacy itself (decision #62). H3 asked whether that
aggregate collapse concentrates in choppy regimes and spares
directionally-persistent ones (`strong_trend/*`, or BTC's dominant
`weak_trend/normal_volatility` bucket) -- a genuinely different
mechanism from the already-REJECTED ATR floor (decision #60), which
uniformly widened stops; H3 touches no parameter, it asks whether
`structure_tp`'s EXISTING variable stop/target geometry happens to be
delay-robust in specific regimes. New analysis-only harness
`scripts/research_regime_delay.py` (+
`backend/tests/test_research_regime_delay.py`, 23 tests) joins
`tag_regimes` and `delay-check` output per bucket, reusing both
mechanisms' existing, independently-tested mechanics verbatim.
`RiskManager.evaluate()`'s live sequential-approval logic is untouched.
Full suite 739/739 (716 prior + 23 new).

**Unlike H1's two-anchor requirement, H3's own pre-registered keep-rule
requires THREE tested years** (2024/2025/2026, matching the standard
`docs/LEGACY_DELAY_ROBUSTNESS.md` established for Legacy's own delay
fragility) -- all three were run this round: BTCUSDT 15m, `--candles
3000 --periods 6`, uncapped `--structure-tp --tag-regimes`, zero-delay
vs `entry_delay_candles=1`. 2026 produced 10 regime buckets (incl.
`all`), 2025 produced 9 (no `range/high_volatility`, zero trades that
regime), 2024 produced 8 (also no `strong_trend/low_volatility`) -- a
regime-occurrence artifact of each year's actual market conditions, not
a tool bug.

**Result, applying H3's own pre-registered keep-rule literally**:
quoting it verbatim, "a regime bucket counts as a genuine delay-robust
pocket only if it clears the SAME bar the platform already applies
everywhere else: n>=20 trades on the delayed side of that bucket, PF
retention >=0.5, no sign flip, in AT LEAST 2 of the 3 tested years. If
no bucket clears this bar in any year, REJECT the regime-conditional-
survival hypothesis outright." Across all 27 bucket-year cells (10 + 9 +
8), `meets_keep_bar` is FALSE for every single one -- not one bucket
clears n>=20 on the delayed side AND PF retention >=0.5 AND no sign flip
in even a single year, let alone 2-of-3. Only ONE cell reaches the n>=20
delayed-side floor at all (2026 `weak_trend/normal_volatility`, delayed
N=20), and it fails outright on PF retention (0.170, needs >=0.5) with a
sign flip. Since not even one bucket clears the bar in even one year,
this does not reach the rule's own "directional lead" tier (reserved for
a bucket clearing the bar in exactly 1 of 3 years) -- it is a harder,
cleaner zero than that. **VERDICT: REJECT.** Not ambiguous, not MIXED
(compare Milestone 25's H4, decision #63, which genuinely did not
resolve to one branch) -- a clean negative result on the rule exactly as
pre-registered.

**Evidence-scarcity caveat, the substantive finding of this round**:
this REJECT is compounded by data scarcity, not purely a clean failure
on well-sampled buckets -- **26 of the 27 bucket-year cells never even
reach the n>=20 delayed-side threshold** needed to evaluate the keep-rule
meaningfully in the first place. This mirrors this platform's
already-documented regime-bucket evidence scarcity
(`docs/REGIME_PERFORMANCE_ANALYSIS.md`: 8 of 9 buckets evidence-starved
for Legacy's own signal stream) -- H3's independently-computed
`structure_tp` regime buckets show the same scarcity pattern on a
completely different exit-logic family. Honest framing: this REJECT is
"insufficient data to test most buckets meaningfully" as much as it is
"buckets were tested and failed" -- it does not rule out that a future
round with more history, more assets, or accumulated shadow-mode data
could surface a bucket clearing the n>=20 floor that then passes or
fails the retention/sign-flip bar on its own merits.

**Secondary, non-deciding observation**: the aggregate (`all`) row's PF
retention for `structure_tp` -- 0.080 (2026), 0.051 (2025), 0.067 (2024)
-- runs systematically ~2-3x HIGHER than Legacy's already-documented
default-exit aggregate retention at the same anchors (2026: 0.023, 2025:
0.015, from `docs/LEGACY_DELAY_ROBUSTNESS.md`; no prior 2024 default-exit
delay-check exists to compare against). Both remain catastrophically
below the 0.5 bar with a sign flip in all three years for `structure_tp`
too -- a quantitative footnote, not evidence of practical delay-
robustness, and it does not change the REJECT verdict. It DOES reinforce,
as a third independent data point alongside Legacy's own Milestone 24
finding (decision #62), that this platform's execution-delay fragility
is STRUCTURAL across strategy/exit-logic variants tested so far, not
specific to one exit-logic family.

**Promotion path**: NONE -- REJECT, matching H3's own pre-registered
"Promotion path if KEEP" text (`docs/HYPOTHESES_ROUND_1.md` §3), which is
moot here. Legacy's live/paper trading behavior is completely unchanged
by this milestone: `RiskManager.evaluate()`, `scripts/run_paper.py`, and
`BacktestEngine` internals are all byte-for-byte unchanged, confirmed
during implementation. No orders placed, no writes to
`backend/paper_validation.db`.

**Status**: read-only evidence round. Full suite 739/739 at evaluation
time (up from 716). Full report, cited not duplicated:
`docs/H3_REGIME_DELAY_RESULTS.md`.

---

## 66. Milestone 28: H2 (passive limit-at-level entry as a delay-robust alternative) evaluated and REJECTED -- delay-robustness achieved cleanly, but the entry model itself becomes unprofitable independent of delay

**Decision context**: `docs/HYPOTHESES_ROUND_1.md` section 4's H2 was
ranked #4 -- highest implementation cost of the five hypotheses, since
every prior delay-robustness fix (ATR floor, decision #60; entry-drift
gate, `docs/CONTINUOUS_RESEARCH_LOG.md` Experiment 4) kept the
IMMEDIATE-marketable-fill entry model and tried to compensate
downstream, while H2 targets the entry model itself: instead of an
immediate fill at the signal candle's close, place a passive limit
order at the actual structural entry zone (the OB/FVG/sweep level the
signal is already built from, `docs/strategy_spec.md` §§2-5) and let a
subsequent candle's retest fill it, with a bounded timeout. Unlike H1
and H3, which were pure research-aggregation harnesses atop
already-existing flags, H2 required real new fill-timing logic: two new
opt-in CLI flags, `--limit-at-level` and `--limit-timeout-candles N`,
wired into `BacktestEngine.run()`/`entry_model.py`, default off and
byte-identical when unset -- confirmed by 2 dedicated regression tests
in `backend/tests/test_backtest_engine.py`. `RiskManager.evaluate()`'s
live sequential-approval logic and `scripts/run_paper.py` are untouched.
Full suite 748/748 at evaluation time (up from 739).

**Two disclosed implementation judgment calls**: (1) the limit fill
price is the zone level itself (`signal.entry_price`) with slippage
applied identically to the existing immediate-fill path -- only
WHEN/WHETHER the fill happens changed, never the price formula; (2)
`entry_delay_candles` (used by `--delay-check`) was interpreted as
placement/dispatch latency -- it shifts when the resting order's scan
window *starts*, while `limit_timeout_candles` still measures the
window length from that point, a specific mechanism disclosure that
matters for interpreting the delay-gate result below. Unfilled/expired
signals (price never retested the zone within the timeout) are not
recorded as trades or losses, matching this platform's existing
precedent for other filtered-out signal types.

**Anchor (all three years)**: BTCUSDT 15m, `--candles 3000 --periods 6
--limit-at-level --limit-timeout-candles 4 --walk-forward
--delay-check`, `--end-date 2026-07-10 / 2025-07-10 / 2024-07-10`,
compared against the already-recorded Legacy market-order baseline
(`docs/LEGACY_DELAY_ROBUSTNESS.md`: +$3,400.62/+$1,714.56/+$1,807.75 Net
Profit, PF retention 0.023/0.015/0.026, all three sign-flipped, all
three delay-gate FAILED).

**Result**: `--limit-at-level` produced -$744.13 (2026), -$727.22
(2025), -$895.05 (2024) Net Profit -- 96/51/64 trades (13-21% fewer than
Legacy), 1/6, 0/6, 2/6 profitable periods, walk-forward FAILED all three
years (degrading trends, losing streaks of 5/6/3). Its OWN internal
delay-gate retention (delay=0 vs delay=1 within the mechanism), however,
PASSED cleanly all three years: PF retention 1.003/0.883/0.935, no sign
flip.

**Applying H2's own pre-registered two-part keep-rule literally**:
quoting it verbatim, "1. Cost-of-passivity check: --limit-at-level's own
zero-added-delay Net Profit must retain >=50% of Legacy market-order
baseline Net Profit in at least 2 of 3 years ... 2. Delay-robustness
check: --limit-at-level's delay-gate PF retention must clear >=0.5 with
no sign flip in at least 2 of 3 years ... Both must hold for KEEP.
Either failing alone is REJECT." **Check 2 PASSES cleanly, 3/3 years**
(1.003/0.883/0.935, no sign flip anywhere) -- genuinely, robustly
solving the execution-delay fragility that both Legacy's default exit
and `structure_tp` (decision #65) failed catastrophically, for the
mechanistically sound reason that a resting order's fill price does not
depend on placement latency, only on whether/when price revisits the
level. **Check 1 FAILS catastrophically, 0/3 years** -- not a near-miss,
it inverts sign in every single year (+$3,400.62 -> -$744.13; +$1,714.56
-> -$727.22; +$1,807.75 -> -$895.05). Both must hold; Check 1 alone
disqualifies. **VERDICT: REJECT.**

**Precision note, the substantive finding of this round**: the rule's
own text analogizes a Check-1-only failure to "the same shape of failure
the ATR floor already showed" (fixing delay by mostly not trading). The
actual mechanism here is more precise and materially different, worth
disclosing explicitly rather than filed under the existing analogy:
trade count drops only modestly (13-21% fewer than Legacy) while
profitable-periods collapses almost entirely (1/6, 0/6, 2/6 vs. Legacy's
6/6 in all three years) and walk-forward degrades everywhere with
elevated losing streaks -- too small a volume reduction to explain a
swing from strongly profitable to net-loss on its own. The more precise
finding: **the retest-based passive-fill mechanism itself systematically
selects for structurally worse trade outcomes**, independent of delay
entirely -- waiting for a retest of the OB/FVG/sweep zone edge appears
to filter FOR setups that subsequently underperform (or filters OUT the
specific immediate-continuation setups that drove Legacy's edge), not
merely filter volume. This is a genuinely novel, third distinct failure
mode among this platform's three tested delay-robustness fixes: ATR
floor (thinned population, decision #60), entry-drift gate
(inconsistent/partial, `docs/CONTINUOUS_RESEARCH_LOG.md` Experiment 4),
and now H2 (delay-robustness achieved completely and cleanly, but the
entry model itself becomes unprofitable independent of delay) -- a
clean, well-differentiated addition to the evidence base, not a repeat
of a known pattern.

**Promotion path**: NONE -- REJECT, matching H2's own pre-registered
"Promotion path if KEEP" text (`docs/HYPOTHESES_ROUND_1.md` §4), which
notes even a KEEP here would have had a uniquely different promotion
story than the other hypotheses in this round (a candle-only
approximation of a resting limit order is not verified live
limit-order behavior) -- moot here since the result is REJECT. Legacy's
live/paper trading behavior is completely unchanged:
`RiskManager.evaluate()` and `scripts/run_paper.py` are untouched; the
new flag pair defaults off and is byte-identical when unset, confirmed
during implementation by the 2 dedicated regression tests. No orders
placed, no writes to `backend/paper_validation.db`.

**Status**: read-only-outcome evidence round (real new opt-in
fill-timing code was added, but default off and byte-identical when
unset; no live/paper behavior changed). Full suite 748/748 at evaluation
time (up from 739). Full report, cited not duplicated:
`docs/H2_LIMIT_ENTRY_RESULTS.md`.

## 67. Milestone 29: H5 (session-conditional position sizing) pre-registered in full, then REJECTED at its own Step 0 grounding gate -- the session-quality gradient does not transfer across candidate/timeframe

**Decision context**: `docs/HYPOTHESES_ROUND_1.md` section 1's ranking
table carried H5 as a one-line row only, by explicit prior department
decision -- `CLAUDE.md` records that the operator/CTO declined to have a
full spec fabricated for it after the fact, and instructs any future
session asked to implement H5 to confirm which section actually carries
its full mechanism/keep-rule text before treating anything as
authoritative, not invent the missing pre-registration itself. This
round did both steps in sequence, in the order the department's own rule
#1 requires: **(1)** wrote H5's full pre-registration (new section 6:
mechanism, grounding, pre-registered experiment, keep-rule, cost,
promotion path) built entirely from evidence already committed to this
repository -- no new claim invented -- then, separately, **(2)** ran the
Step 0 precondition check that pre-registration itself declared before
building anything further.

**What the pre-registration surfaced that the original 2026-07-17
ranking-table row did not**: (a) new supporting grounding -- decision
#64 (Milestone 26, H1) found "trade FREQUENCY matters more than
per-trade selectivity on this platform," published the day AFTER H5 was
originally ranked last, independently supporting H5's sizing-not-
filtering mechanism class against the already-rejected Asian-only entry
filter (`docs/CONTINUOUS_RESEARCH_LOG.md` Experiment 3); (b) a disclosed
grounding gap -- H5's sole motivating evidence, `docs/ROBUSTNESS_REPORT.md`
Test 6 (Asian PF 4.65 > London PF 2.41), was measured on BTCUSDT
**5-minute** timeframe against the `structure_tp` candidate, not the
BTCUSDT **15-minute** Legacy default-exit candidate H5's proposed
`session_risk_scalar` would actually size (`scripts/research_session_filter.py`
confirms `TIMEFRAME = "5m"` for that same Test-6-motivated run). The
pre-registration's own Step 0 gate exists specifically to check (b)
before investing in the mechanism at all.

**Step 0 was then run this same round**: new analysis-only harness
`scripts/research_h5_step0_session_grounding.py` (+
`backend/tests/test_research_h5_step0_session_grounding.py`, 8 tests) --
no new `BacktestEngine` parameter, no new CLI flag, `RiskManager.evaluate()`
and `scripts/run_paper.py` untouched throughout. It runs the plain
Legacy default-exit baseline (BTCUSDT 15m, `--candles 3000 --periods 6`,
`--end-date 2026-07-10 / 2025-07-10 / 2024-07-10`) and buckets the
resulting trades by entry-candle UTC hour into Test 6's own three
session windows (Asian 00:00-08:00, London 08:00-16:00, NY/other
16:00-24:00 -- the first two already-disclosed constants from
`backend/app/strategy/session_liquidity.py`/`signal_engine.py`'s
`_SESSION_WINDOWS`, decision #27; the third Test 6's own residual
bucket). **Baseline reproduction confirmed before trusting the new
bucketing logic**: total trade counts (111/65/73 for 2026/2025/2024)
match the already-published Legacy baseline exactly
(`docs/LEGACY_DELAY_ROBUSTNESS.md`; `docs/H2_LIMIT_ENTRY_RESULTS.md`'s
Legacy comparison column).

**Result**: Asian N/PF 71/3.565 (2026), 42/2.690 (2025), 47/3.916
(2024); London N/PF 24/5.303 (2026), 17/4.451 (2025), 20/2.753 (2024).
The sample floor (n>=10 on both buckets) is met in all three years, but
the gradient direction (Asian PF > London PF) holds in only **1 of 3
years** (2024) -- in 2026 and 2025, including the platform's single
most-evidenced anchor (2026, 111 trades, the largest trade count on
record for any anchor in this evidence base), London's PF exceeds
Asian's, the OPPOSITE of Test 6's finding on the unrelated
candidate/timeframe.

**Applying H5's own pre-registered Step-0 gate literally**: quoting it
verbatim, "H5's mechanism proceeds to Step 1 only if Legacy/15m shows
the SAME qualitative gradient direction Test 6 found (Asian PF > London
PF) in at least 2 of the 3 tested years, AND at least the Asian and
London buckets individually reach n>=10 trades in the year(s) counted
toward that check... If this gate fails, H5 is REJECTED at step 0
without building `session_risk_scalar` at all." **VERDICT: REJECT at
Step 0.** 1-of-3 is below the required 2-of-3 threshold; per the rule's
own text this ends the hypothesis outright. `session_risk_scalar` and
`--session-scaled-sizing` were never implemented; H5's Step 1 (the
actual sizing-mechanism keep-rule: drawdown/Net-Profit/delay-gate
conditions) never ran.

**The substantive finding, independent of H5's own REJECT**: a
session-quality gradient measured on one candidate/timeframe does not
transfer to a different candidate/timeframe, even holding the asset and
the UTC session-window convention fixed -- the two candidates' session
ranking actually INVERTS in 2 of 3 years. This is a standalone,
disclosed caveat for this evidence base: any future hypothesis
conditioning on Test 6's specific numbers must re-verify them on the
actual candidate being sized, not assume they transfer. **Hypothesis
Round 1 is now fully resolved**: H1 REJECT (decision #64), H2 REJECT
(decision #66), H3 REJECT (decision #65), H4 MIXED (decision #63), H5
REJECT at Step 0 (this decision) -- zero KEEPs, one MIXED, four REJECTs.

**Promotion path**: NONE -- REJECT at the precondition stage, before any
promotion-relevant keep-rule was even evaluated. Legacy's live/paper
trading behavior is completely unchanged: `RiskManager.evaluate()`,
`scripts/run_paper.py`, and `BacktestEngine` internals are all
byte-for-byte unchanged -- this round needed zero new engine parameters
or CLI flags, unlike H1/H3/H4's harnesses, since Step 0 only buckets
trade output the engine already produces. No orders placed, no writes to
`backend/paper_validation.db`.

**Status**: read-only evidence round, no production code touched (one
new research-only script + its dedicated test file, neither imported by
any production or paper-trading path). Full suite 756/756 at evaluation
time (up from 748 -- 8 new tests for the session-bucketing logic). Full
report, cited not duplicated: `docs/H5_SESSION_GROUNDING_RESULTS.md`.

## 68. Milestone 30: Hypothesis Round 2 opened; H6 root-causes Jade's signal scarcity -- REJECTED, zones don't exist far more often than they're mistimed, and the aggregate masks real per-model heterogeneity

**Decision context**: with Hypothesis Round 1 fully resolved (decisions
#63-#67, zero KEEPs, one MIXED), this round opens `docs/HYPOTHESES_ROUND_2.md`,
scoped to the adaptive platform's own stated objective -- a working
second strategy -- rather than a sixth Legacy-delay-fragility patch,
per the operator's own "prefer structural improvements over parameter
optimization" directive. **Self-correction, disclosed rather than
silently fixed**: `ROADMAP.md`'s milestone 29 close-out claimed Jade
"has never been benchmarked end-to-end." This was factually wrong --
decision #36 already ran that exact comparison (2026-07-12, BTCUSDT 15m
standard scale) and found it lost badly: 6 trades vs. Legacy's 47, 0/6
vs. 6/6 profitable periods, walk-forward FAILED. Re-benchmarking Jade
in Round 2 would have duplicated already-settled work; caught before it
happened via a direct grep-and-read pass over the evidence base before
committing to a Round 2 direction, corrected in the same round's
`ROADMAP.md` update rather than left standing.

**What Round 2 targets instead**: decision #36 itself named a specific,
disclosed, un-executed next step -- "confirm or rule out the
same-bar-retracement-requirement hypothesis directly" -- the
plausible-but-unconfirmed claim that 3 of Jade's 5 entry models (FVG,
Order Block, Breaker Block) require the CURRENT candle to already be
retracing into a zone (`_last_candle_overlaps_zone`,
`entry_point_engine.py`) before producing a candidate, unlike Legacy's
own zone selection, which has no same-bar timing requirement. H6
(`docs/HYPOTHESES_ROUND_2.md` section 2) tests this directly, and
expands it into a complete pipeline attribution after reading
`jade_trade_plan.build_trade_plan` and `signal_engine.
_generate_signal_via_jade_engine` surfaced two more candidate scarcity
drivers decision #36's text did not examine: the upstream
`bias.detect_htf_bias` neutral-bias gate (shared identically with
Legacy's own pipeline, so disclosed as context, not a differential
explanation) and the downstream `exit_point_engine.find_exit_targets`
empty-result gate (Jade-specific, never previously measured).

**New instrumentation** (read-only, walks every candle exactly like
`scripts/research_signal_selection.py`'s `collect_candidates` phase --
same `MIN_CANDLES - 1` start, same no-lookahead `_advance_htf_cursor`):
`scripts/research_h6_jade_scarcity_diagnosis.py` (+
`backend/tests/test_research_h6_jade_scarcity_diagnosis.py`, 17 tests)
calls `bias.detect_htf_bias` and each of `entry_point_engine.py`'s 5
entry-model evaluators directly and unmodified, classifying the 3
same-bar models into `no_matching_zone` / `zone_exists_not_retraced` /
`candidate_found` per step (FVG's own reject reason conflates the first
two, so this re-derives the distinction from `detect_fair_value_gap`
directly -- the same function `_evaluate_fair_value_gap` itself already
calls). `RiskManager.evaluate()`, `scripts/run_paper.py`, and every Jade
module touched are read but UNMODIFIED; no trade is ever executed by
this harness.

**Anchor (all three years)**: BTCUSDT 15m, `--candles 3000 --periods 6`,
`--end-date 2026-07-10 / 2025-07-10 / 2024-07-10` -- this project's
standard 3-anchor set, extending decision #36's original single-window
BTCUSDT scope for cross-year confirmation of the MECHANISM only, not a
re-run of the already-decided trade-count comparison itself.

**Result** (53,910 total steps across 3 anchors, 45,510 = 84.4%
neutral-bias-gated -- a shared constraint on both pipelines, reported as
context per H6's own pre-registered framing, not a differential
explanation): per-model `no_matching_zone` / `zone_exists_not_retraced`,
summed across all 3 years -- `fair_value_gap` 0 / 202; `order_block`
5,004 / 2,070 (2.42x); `breaker_block` 7,477 / 438 (17.07x); aggregate
across all 3 same-bar models: 12,481 / 2,710 (4.61x).

**Applying H6's own pre-registered keep-rule literally**: quoting it
verbatim, "CONFIRMED if zone_exists_not_retraced >= 2x no_matching_zone
... REJECTED if no_matching_zone >= 2x zone_exists_not_retraced ...
INCONCLUSIVE otherwise." **VERDICT: REJECTED** -- the aggregate 4.61x
ratio clears the threshold, and this is not an aggregation artifact:
Order Block (2.42x) and Breaker Block (17.07x) both independently clear
the REJECTED bar evaluated alone. Decision #36's originally-disclosed
fix direction (relaxing the same-bar retracement window) is not
supported by this evidence -- the models overwhelmingly fail to find a
matching ZONE at all, not "find one but miss the exact bar."

**The substantive finding**: the aggregate REJECTED verdict masks real,
disclosed per-model heterogeneity. FVG's own numbers in isolation
(`no_matching_zone=0`, `candidate_found=8,198` of 8,400 zone-checked
steps, ~97.6%) would satisfy CONFIRMED trivially -- FVG is essentially
unconstrained, a direct, disclosed consequence of Jade's deliberate
design choice to never apply `is_zone_mitigated` ("repeated FVG tests do
not invalidate the setup" per spec) and to search the FULL candle
history every step, so the pool of still-valid matching zones only
grows over an ~18,000-candle series. FVG wins `find_entry_point`'s
highest-confidence selection 76.4% of the time (6,421 of 8,400)
specifically because it is almost always available to compete. Order
Block and especially Breaker Block are the genuinely zone-scarce models
-- a real, model-specific finding decision #36's originally-framed
"3 same-bar models behave alike" characterization did not anticipate.

**The larger finding this round surfaces, disclosed and explicitly NOT
chased further this round**: 8,312 `signal_would_generate` steps were
found across the 3 anchors, vastly exceeding decision #36's 6 actual
trades. This is NOT read as a missed-opportunity signal -- three
disclosed methodological reasons the two numbers are not comparable:
(1) this harness does not track open-trade state, unlike
`BacktestEngine.run()`'s real single-open-trade-at-a-time invariant;
(2) Jade's own no-zone-mitigation design lets one real zone satisfy
`candidate_found` across many consecutive candles, so step counts
overcount distinct opportunities; (3) `RiskManager.evaluate()` gating
(`MAX_TRADES_PER_DAY`, already found to reject 89-92% of Legacy's own
raw signals per decision #62; the 1:2 minimum RR rule; daily/weekly loss
limits) was entirely out of H6's declared scope. This gap is recorded as
the most likely remaining explanation for decision #36's low trade
count and a well-grounded H7 candidate for a future round -- named, not
chased, matching decision #36's own precedent exactly.

**Secondary footnotes**: exit-target availability is a negligible gate
(only 88 of 8,400 selected steps, 1.0%, had empty targets) -- this
candidate explanation is effectively ruled out. Liquidity Raid never won
`find_entry_point`'s selection in any of the 8,400 steps across 3 years
despite 3,731 `candidate_found` occurrences of its own -- noted as a
minor, uninvestigated footnote for a future round examining Jade's
confidence-ranking logic specifically.

**Promotion path**: NONE -- this is a diagnostic, not a promotion
candidate. `use_jade_engine` stays `False`. Legacy's live/paper trading
behavior is completely unchanged: `RiskManager.evaluate()` and
`scripts/run_paper.py` are untouched; every Jade module this round
touched (`entry_point_engine.py`, `jade_trade_plan.py`,
`exit_point_engine.py`, `bias.py`) was read, not modified. No trade was
ever executed by this harness; no orders placed, no writes to
`backend/paper_validation.db`.

**Status**: read-only evidence round, no production code touched (one
new research-only script + its dedicated test file, neither imported by
any production or paper-trading path). Full suite 773/773 at evaluation
time (up from 756 -- 17 new tests for the pipeline-attribution logic).
Full report, cited not duplicated: `docs/H6_JADE_SCARCITY_RESULTS.md`.

## 69. Milestone 31: H7 attributes Jade's remaining scarcity gap -- Jade's real bottleneck is reward:risk geometry, not the shared MAX_TRADES_PER_DAY cap; a keep-rule design flaw caught and disclosed mid-analysis

**Decision context**: preceded by a strategic research review
(`docs/RESEARCH_STRATEGY_REVIEW.md`) across all six prior hypotheses
(H1-H6) -- rather than opening a seventh hypothesis in isolation, that
review extracted five cross-cutting patterns and ranked six candidate
future directions by expected ROI, placing H7 (RiskManager/pipeline-
gating attribution for Jade) first. H6 (decision #68) had disclosed but
explicitly not measured a gap: 8,312 step-level `signal_would_generate`
events across 3 anchors versus decision #36's 6 recorded Jade trades,
naming three un-measured candidate explanations (open-trade-state
tracking, Jade's own zone-persistence, `RiskManager.evaluate()` gating)
without chasing any of them in the same round.

**Why this needed essentially zero new code**: `BacktestResult.risk_rejections`
(Milestone 23, decision #61(b)) is generic, engine-agnostic
instrumentation -- it observes whatever `RiskManager.evaluate()`
decides on whatever signal `SignalEngine.generate_signal()` produces,
regardless of `use_jade_engine`. Decision #36's original A/B test
(2026-07-12) simply predates this instrumentation (shipped 2026-07-17)
by 5 days -- nobody had looked at Jade's own risk-rejection breakdown
because the tooling to see it didn't exist yet when #36 ran, not because
anyone chose not to look. New thin wrapper
`scripts/research_h7_jade_risk_attribution.py` (+
`backend/tests/test_research_h7_jade_risk_attribution.py`, 7 tests)
reuses `run_backtest.py`'s own already-existing `run_backtest(...,
use_jade_engine=True)` and `aggregate_risk_rejections()` verbatim -- no
new `BacktestEngine` parameter, no new production code path anywhere.

**Anchor (all three years)**: BTCUSDT 15m, `--candles 3000 --periods 6`,
`--end-date 2026-07-10 / 2025-07-10 / 2024-07-10`, `use_jade_engine=True`
-- this project's standard 3-anchor set. **Disclosed limitation**: H7's
own pre-registered text intended to first confirm reproducing decision
#36's 6-trade result before trusting new numbers; that check as
literally described wasn't actually possible, since decision #36 used
no explicit `--end-date` (candles ending at "now" on 2026-07-12), not
this round's `2026-07-10` anchor -- the two windows differ by ~2 days
out of an ~18,000-candle span. This round's 2026 anchor produced 22
trades, not 6; most plausibly the anchor-date shift interacting with
Jade's own RR-sensitivity (no Jade module was touched by any commit
between decision #36 and this round). This does not weaken H7's own
findings below (about rejection-reason composition and rate, not about
matching one historical trade count), but this round's 57 pooled trades
should be read as new, standalone measurements, not a confirmed
byte-identical replication of #36.

**Result**: 8,021 signals reached `RiskManager.evaluate()` across the 3
anchors -- 96.5% of H6's own step-level `signal_would_generate` count.
**Open-trade/zone-persistence branch of H7's keep-rule: cleanly
REJECTED** -- `total_signals` stayed at 94.6-97.3% of H6's count in
every year, nowhere near the pre-registered <25% threshold. Because the
approval rate is so low (0.7% of signals reaching RiskManager), a trade
is almost never open, so the walk-forward loop has almost nothing to
skip past regardless of Jade's own zone-persistence design -- H6's raw
step counts were NOT mostly duplicate/overlapping retests of the same
zone. Of the 8,021 signals, 7,964 (99.3%) were rejected; only 57 became
real trades.

**Applying H7's own pre-registered RiskManager-gating branch literally**:
quoting it verbatim, "`rejected / total_signals >= 0.5` ... AND
`MAX_TRADES_PER_DAY` is the single most frequent `by_reason` entry."
Mechanically: reject rate 99.3% clears 0.5, and `"trades_today 2 reached
MAX_TRADES_PER_DAY 2"` is, character-for-character, the single most
frequent individual string in `by_reason` -- **RISK_GATING_DOMINANT per
the rule as literally written.**

**A design flaw in this literal result, caught and disclosed rather than
reported as the final answer**: `RiskManager.evaluate()`'s RR-below-minimum
rejection reason embeds the exact numeric RR value in its own string
("rr 0.052 is below required MIN_RR 2.0"), so it fragments into
thousands of distinct near-unique strings, each individually small --
while `MAX_TRADES_PER_DAY`'s reason string never varies, so every one of
its occurrences accumulates under one key. A "single most frequent exact
string" comparison structurally favors whichever reason happens to have
a fixed string, independent of which reason is actually more prevalent
in substance -- the keep-rule's own operationalization has a blind spot
this round discovered on contact with real data, not before. Re-aggregating
`by_reason` by CATEGORY instead of exact string (8,589 total
reason-instances, pooled across all 3 anchors -- more than
`aggregate_rejected` 7,964 because `RiskManager.evaluate()` collects
every failing check per signal, not just the first): **RR below minimum
92.3% (7,929 instances), `MAX_TRADES_PER_DAY` cap 7.3% (624), daily loss
limit 0.4% (36).**

**The substantive finding**: Jade's dominant rejection reason is
overwhelmingly RR-below-minimum, not the shared cap. Unlike Legacy,
whose own raw-signal rejection is 100% `MAX_TRADES_PER_DAY`-driven
(decision #62: 89-92% of Legacy's signals rejected, every fired reason
the daily cap), **Jade's scarcity is a genuinely different mechanism**:
the vast majority of its own generated entry/stop/target combinations
never clear this platform's 1:2 minimum reward:risk requirement.
Consistent with everything else this evidence base has found about Jade
-- its stop/target construction (`entry_point_engine.py`'s
zone-boundary-based stops, `exit_point_engine.find_exit_targets`'s
liquidity/swing/premium-discount targets) has never been swept or tuned
the way Legacy's own `_RR`/`_STOP_BUFFER` were
(`docs/parameter_sweep_report.md`). **Two independently-built strategies
on this platform are bottlenecked by two DIFFERENT gates** -- Legacy by
trade-frequency throughput under a fixed cap, Jade by trade-quality
geometry under the fixed minimum RR -- a disclosed, platform-level
finding for any future Strategy Selection Engine design conversation,
distinct from (and more specific than) the "shared bottleneck"
hypothesis this round originally set out to test.

**Promotion path**: NONE -- diagnostic only. The RR-geometry finding
does not itself validate or invalidate any specific stop/target fix for
Jade -- that would be a new, separately pre-registered hypothesis
(a natural H8 candidate, not authorized or implied by this round).
`use_jade_engine` stays `False`. Legacy's live/paper trading behavior is
completely unchanged: `RiskManager.evaluate()` and `scripts/run_paper.py`
are untouched; no Jade module was modified. No orders placed, no writes
to `backend/paper_validation.db`.

**Status**: read-only evidence round, no production code touched (one
thin new research-only wrapper script + its dedicated test file, both
reusing already-existing, already-tested functions verbatim, neither
imported by any production or paper-trading path). Full suite 780/780
at evaluation time (up from 773 -- 7 new tests for the keep-rule
arithmetic). Full report, cited not duplicated: `docs/H7_JADE_RISK_ATTRIBUTION_RESULTS.md`.
