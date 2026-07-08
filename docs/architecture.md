# JadeCap Automated Trading Bot — System Architecture

Milestone 1: System Architecture. This document describes the intended
architecture of the bot. No trading logic is implemented yet — this is the
scaffolding and design contract that later milestones build against.

## 1. System Overview — The 6 Core Layers

The system is composed of six core layers. Each layer has a single
responsibility and communicates with adjacent layers only.

### Data Layer
- Fetch candles
- Store historical data
- Store live market data
- Normalize exchange data

### Strategy Engine
- Analyze market structure
- Detect HTF bias
- Detect liquidity sweep
- Detect CHOCH/MSS
- Detect FVG/OB/Breaker Block
- Generate trade signal
- Never place orders directly

### Risk Engine
- Validate every trade signal
- Calculate position size
- Check max daily loss
- Check max weekly loss
- Check max trades per day
- Check RR minimum 1:2
- Block trades when risk rules fail

### Execution Engine
- Receive approved signal
- Place entry order
- Place SL and TP
- Handle partial TP
- Handle break-even move
- Handle exchange errors
- Cancel unsafe orders

### Portfolio/Journal Engine
- Track open positions
- Track closed trades
- Track PnL
- Save trade reason
- Save screenshots/chart state if possible
- Generate trade journal

### Dashboard/Control Panel
- Show bot status
- Current bias
- Active signals
- Open positions
- Risk status
- Logs
- Switch between Paper and Live mode (Live mode locked behind env var)

## 2. System Data Flow

```
Market Data → Data Layer → Strategy Engine → Trade Signal → Risk Engine →
Approved/Rejected → Execution Engine → Exchange API → Portfolio/Journal →
Dashboard/Notifications
```

Risk Engine always sits between Strategy Engine and Execution Engine.
Strategy Engine cannot send orders directly.

## 3. Trading Modes

| Mode | Data Source | Orders | Capital | Notes |
|---|---|---|---|---|
| `BACKTEST_MODE` | Historical candles | No exchange orders | Simulated | Includes fee + slippage simulation |
| `PAPER_MODE` | Live market data | Simulated orders | No real capital | **Default mode** |
| `LIVE_MODE` | Real exchange API | Real orders | Real capital | Disabled by default. Enabled only when `LIVE_TRADING_ENABLED=true` |

## 4. Folder Structure

Stub files exist for this milestone; implementation logic is out of scope
until later milestones (see `next_milestone_plan.md`).

```
jadecap-bot/
├── backend/
│   └── app/
│       ├── api/                # Next.js-facing / REST API routes for dashboard & control panel
│       ├── data/                # Data Layer: candle fetching, storage, normalization
│       ├── strategy/            # Strategy Engine: bias, liquidity, CHOCH, FVG, OB, signal generation
│       ├── risk/                # Risk Engine: validation, position sizing, loss/trade limits
│       ├── execution/           # Execution Engine: order placement, SL/TP, break-even, error handling
│       ├── exchange/            # Exchange API clients (OKX, OrangeX) and shared exchange interface
│       ├── backtesting/         # Backtest Mode: simulated fills, historical replay
│       ├── portfolio/           # Portfolio/Journal Engine: positions, trades, PnL, journal
│       ├── database/            # DB models, session/connection management
│       ├── notifications/       # Telegram / alert notifications
│       ├── utils/                # Shared utilities (logging, config loading, helpers)
│       ├── config.py
│       └── main.py
├── frontend/
│   ├── app/                     # Dashboard/Control Panel pages
│   ├── components/              # UI components
│   ├── lib/                     # Frontend API clients / shared frontend logic
│   ├── next.config.js
│   ├── package.json
│   └── tsconfig.json
├── docs/                        # This documentation set
├── scripts/                     # Operational / dev scripts
├── .env.example
├── docker-compose.yml
├── README.md
└── CHANGELOG.md
```

## 5. Module Responsibility Table

One row per module file under `backend/app/`, responsibility derived from the
layer descriptions above.

| Directory | File | Responsibility |
|---|---|---|
| `data/` | `candle_fetcher.py` | Fetch candles from exchange APIs |
| `data/` | `historical_data.py` | Store and retrieve historical data |
| `data/` | `live_feed.py` | Store and stream live market data |
| `data/` | `data_normalizer.py` | Normalize exchange data into a common internal format |
| `strategy/` | `market_structure.py` | Analyze market structure |
| `strategy/` | `bias.py` | Detect HTF bias |
| `strategy/` | `liquidity.py` | Detect liquidity sweep |
| `strategy/` | `fvg.py` | Detect FVG (Fair Value Gap) |
| `strategy/` | `order_block.py` | Detect Order Block / Breaker Block |
| `strategy/` | `entry_model.py` | Model precise entry conditions from confluences above |
| `strategy/` | `signal_engine.py` | Generate trade signal; never places orders directly |
| `risk/` | `risk_manager.py` | Validate every trade signal against all risk rules |
| `risk/` | `position_sizing.py` | Calculate position size |
| `risk/` | `drawdown_guard.py` | Check max daily loss / max weekly loss |
| `risk/` | `circuit_breaker.py` | Check max trades per day and RR minimum 1:2; block trades when risk rules fail |
| `execution/` | `execution_engine.py` | Receive approved signal; place entry, SL, TP; handle partial TP, break-even, exchange errors, and cancel unsafe orders |
| `exchange/` | (OKX client) | Exchange API integration for OKX |
| `exchange/` | (OrangeX client) | Exchange API integration for OrangeX |
| `backtesting/` | `backtest_engine.py` | Run signals through a simulated fill model with fee + slippage |
| `portfolio/` | (portfolio tracker) | Track open positions, closed trades, and PnL |
| `portfolio/` | (trade journal) | Save trade reason, screenshots/chart state, and generate trade journal |
| `database/` | `models.py` | SQLAlchemy 2.0 models — authoritative DB schema (see `database_schema.md`) |
| `notifications/` | (notifier) | Send bot status / alerts (e.g. Telegram) |
| `utils/` | (shared utils) | Logging, config loading, shared helpers |
| `api/` | (routes) | Expose bot status, bias, signals, positions, risk status, logs, and mode switch to the Dashboard/Control Panel |
