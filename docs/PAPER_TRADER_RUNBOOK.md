# Paper Trader Operational Runbook

Milestone 38 (Priority 3, "recovery checkpoints"). This is the missing
piece between the health-check tool (`scripts/paper_trader_health_check.py`,
milestone 37/38) and actually knowing what to DO when it reports a
problem. Cite-don't-duplicate: this doc doesn't restate risk rules
(`docs/risk_rules.md`), the launch mechanics
(`[[paper-trader-launch]]` agent memory), or Finding details
(`docs/PAPER_TRADING_VALIDATION_REPORT.md`) -- it links to them and
tells you which one to read for a given symptom.

## 1. Check health first, always

```
cd backend
PYTHONPATH=<repo>/backend DATABASE_URL=sqlite:///<repo>/backend/paper_validation.db \
  python ../scripts/paper_trader_health_check.py
```

Or, for continuous monitoring instead of a one-shot check:

```
python ../scripts/paper_trader_health_check.py --watch \
  --poll-interval-seconds 120 --heartbeat-every 30 \
  --alert-log paper_trader_health_alerts.log
```

`--watch` writes one line to `--alert-log` only when HEALTHY/UNHEALTHY
*changes*, plus a periodic heartbeat -- read that file, not the raw
`tail -f` of the trader's own stdout log, to see whether something
actually changed recently.

## 2. Symptom -> diagnosis -> action

| Health-check reports | Likely cause | Action |
|---|---|---|
| `Circuit breaker: TRIPPED` | A real risk-limit trip (daily/weekly loss limit, or another circuit-breaker condition) -- `PersistentCircuitBreaker` persisted this to `bot_state` and a respawned process will stay tripped by design (`ENGINEERING_DECISIONS.md`, milestone-21-era circuit-breaker persistence work). | **Do not silently restart or clear this.** Read `reason`/`tripped_at` from the health-check output. This tripped for a reason -- understand it (check `docs/risk_rules.md` for what the specific limit means) before deciding whether to reset. Resetting the circuit breaker is a decision with real trading-behavior consequences, same class of decision as any other risk-affecting change. |
| `Snapshot freshness: STALE` (or `NO_SNAPSHOTS_YET`) | The process died, is hung, or was never running against this DB file. | Check `tasklist \| grep python` (Windows) / `ps aux \| grep run_paper` for a live process. If absent, relaunch using the exact invocation in `[[paper-trader-launch]]` agent memory (PYTHONPATH + DATABASE_URL explicit; `ENABLE_SHADOW_STRATEGY_SIGNALS=true`; `-u` unbuffered). Run `scripts/migrate_paper_db.py --apply` first if the DB hasn't been touched in a while -- it auto-backs-up before migrating, safe to run repeatedly. |
| `Open positions: ANOMALY_MULTIPLE_OPEN_POSITIONS` (count > 1) | Should be structurally impossible per the documented one-trade-open-at-a-time concurrency guard in `scripts/run_paper.py::run_once()` (verified intact in `scripts/verify_signal_to_fill.py`'s Phase 2 check, milestone 37). If you see this, treat it as **evidence of a real bug**, not a fluke. | Do NOT manually close/edit trade rows to "fix" it -- that could mask the actual bug and would be a direct DB write outside the app's own code paths. Stop new signal generation is already automatic (the guard itself blocks it once >0 positions are open, though >1 means something already got past it). Escalate: this needs the same root-cause treatment Finding #1 (milestone 33/34) got -- reproduce against a throwaway temp DB, not the live one. |
| Health-check itself fails to open the DB (`DB_OPEN_FAILED`) | Wrong `db_path` argument, or the file genuinely doesn't exist yet (fresh environment, migrations never run). | Confirm the path. Run `scripts/migrate_paper_db.py <path>` (detection-only, no `--apply`) to check status before doing anything else. |
| Trader process alive, health check HEALTHY, but no trades ever appear | Expected, not a bug -- Legacy's real signal rate is roughly one every 1-4 days per backtest evidence (`scripts/verify_signal_to_fill.py`'s own docstring). Use `scripts/verify_signal_to_fill.py` (injects a deterministic synthetic signal into the REAL pipeline against a throwaway temp DB) to verify the wiring is correct without waiting for a real signal. | No action needed; this is normal. |

## 3. Standing, not-yet-resolved findings (don't re-diagnose these from scratch)

- **Finding #2** (`docs/PAPER_TRADING_VALIDATION_REPORT.md`): which
  `DEFAULT_TIMEFRAME` the real deployed `.env` actually used historically
  is still unconfirmed -- affects how to interpret delay-fragility
  research against real production behavior. Needs operator's real
  `.env` access, not something diagnosable from this repo.
- **Finding #5**: `strategy_logs`/`risk_events` are real DB tables that
  nothing writes to -- confirmed still true as of milestone 37. Not a
  health-check blind spot; this runbook's checks deliberately don't
  depend on those tables for exactly this reason (`regime_snapshots` and
  `trades` are the tables actually written every pass).

## 4. What this runbook does NOT authorize

Per this project's gated-file discipline (`CLAUDE.md` section 2):
editing `scripts/run_paper.py` or `app.risk.risk_manager.RiskManager.evaluate()`
themselves -- for ANY reason, including a fix that looks obviously safe
-- needs explicit operator sign-off before implementation, not just
before merge. This runbook only covers operating the EXISTING code
(restart, check, read); it is not a blanket approval to modify either
file when a symptom above points at one of them.
