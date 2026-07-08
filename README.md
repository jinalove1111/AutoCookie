# JadeCap Automated Trading Bot

JadeCap is an automated trading bot designed to progress through a strict,
staged validation pipeline before any capital is put at real risk. It
combines a Strategy Engine (market structure / smart-money style detection),
a Risk Engine (position sizing and loss limits), an Execution Engine
(order placement and management), a Portfolio/Journal Engine (trade
tracking), and a Dashboard/Control Panel (monitoring and mode control) — see
[`docs/architecture.md`](docs/architecture.md) for the full system design.

## Pipeline

**Backtest → Paper → Small Live → Full Live**

Every strategy and risk change must pass through this pipeline in order.
No stage is skipped.

## Quickstart

```bash
docker-compose up
```

or, to run the backend directly:

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Documentation

See [`docs/architecture.md`](docs/architecture.md) for the full system
architecture, and the rest of `docs/` for strategy spec, risk rules, API
key security practices, the live trading checklist, database schema draft,
and the Milestone 2 plan.

## Safety Note

**`LIVE_TRADING_ENABLED` defaults to `false`.** Real order placement is
disabled by default and must be deliberately enabled via environment
variable, in `TRADING_MODE=live`, only after every item in
[`docs/live_trading_checklist.md`](docs/live_trading_checklist.md) is
satisfied.
