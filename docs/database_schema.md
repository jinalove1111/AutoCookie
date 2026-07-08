# Database Schema (Draft)

This is a human-readable draft of the intended database schema. The
authoritative implementation is `backend/app/database/models.py`
(SQLAlchemy 2.0). If this document and the SQLAlchemy models ever diverge,
`models.py` is the source of truth.

## Migrations (Alembic)

Schema migrations are now managed via Alembic (no longer "not initialized" —
`models.py` remains the canonical model definitions that migrations are
generated *from*, but applying/versioning the schema goes through Alembic):

- Apply the schema to a database: `cd backend && alembic upgrade head`
- Version history lives in `backend/app/database/migrations/versions/`
- `backend/app/database/migrations/env.py` reads the connection string from
  `app.config.settings.DATABASE_URL` at runtime (no URL is committed to
  `alembic.ini`)
- To generate a new migration after changing `models.py`:
  `alembic revision --autogenerate -m "<description>"`, then review the
  generated file by hand before committing (autogenerate can miss or
  mis-detect constraints)

## `candles`

- `id`
- `symbol`
- `timeframe`
- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`

## `signals`

- `id`
- `symbol`
- `timeframe`
- `timestamp`
- `direction`
- `entry`
- `stop_loss`
- `take_profit`
- `rr`
- `reasoning`

## `trades`

- `id`
- `signal_id`
- `symbol`
- `direction`
- `entry_price`
- `exit_price`
- `stop_loss`
- `take_profit`
- `position_size`
- `pnl`
- `status`
- `opened_at`
- `closed_at`

## `risk_events`

- `id`
- `event_type`
- `reason`
- `timestamp`
- `related_trade_id`

## `bot_state`

- `id`
- `mode`
- `live_trading_enabled`
- `status`
- `current_bias`
- `updated_at`

## `strategy_logs`

- `id`
- `timestamp`
- `module`
- `message`
- `context`
