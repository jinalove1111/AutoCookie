# Database Schema (Draft)

This is a human-readable draft of the intended database schema. The
authoritative implementation is `backend/app/database/models.py`
(SQLAlchemy 2.0). If this document and the SQLAlchemy models ever diverge,
`models.py` is the source of truth.

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
