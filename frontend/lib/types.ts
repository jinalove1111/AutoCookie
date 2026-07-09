// Type contracts mirroring the REAL backend API response shapes (Milestone 6).
//
// Design choice: these interfaces intentionally keep the backend's snake_case
// field names as-is (BotStatus.live_enabled, Trade.entry_price, etc.) instead
// of introducing a camelCase transform layer. The backend returns
// FastAPI/SQLAlchemy row dicts directly (see backend/app/api/routes_dashboard.py
// and routes_trades.py) — mirroring the wire format 1:1 keeps this file a
// simple, verifiable contract instead of adding a mapping layer that could
// silently drift from the real API.

/** GET /dashboard/status — real BotState row. */
export interface BotStatus {
  id: number;
  mode: "backtest" | "paper" | "live" | string;
  live_enabled: boolean;
  daily_pnl: number;
  weekly_pnl: number;
  current_drawdown: number;
  trading_allowed: boolean;
  updated_at: string | null;
}

/** Real Trade row shape, shared by /dashboard/positions, /trades/open, /trades/closed, /trades/{id}. */
export interface Trade {
  id: number;
  symbol: string;
  direction: "long" | "short" | string;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  exit_price: number | null;
  size: number;
  leverage: number;
  pnl: number | null;
  fee: number | null;
  slippage: number | null;
  status: "open" | "closed" | "cancelled" | string;
  mode: "backtest" | "paper" | "live" | string;
  opened_at: string;
  closed_at: string | null;
  created_at: string;
}

/** GET /dashboard/logs — real StrategyLog rows, most recent first. */
export interface LogEntry {
  id: number;
  timestamp: string | null;
  module: string;
  decision: string;
  reason: string;
  candle_context: Record<string, unknown> | null;
  signal_id: number | null;
}

/**
 * GET /dashboard/bias — INTENTIONALLY still a placeholder on the backend.
 * Always includes `note` explaining it is not yet wired to live strategy state.
 */
export interface Bias {
  symbol: string;
  htf_bias: string;
  ltf_bias: string;
  note: string;
}

/**
 * GET /dashboard/signals — INTENTIONALLY still a placeholder on the backend.
 * Always includes `note`; `signals` is currently always an empty array.
 */
export interface SignalsResponse {
  signals: unknown[];
  note: string;
}

/**
 * GET /dashboard/risk-status — real, DB-backed risk-budget usage (via
 * TradeJournal's daily/weekly reports and TradeTracker's trades-today
 * count), the same figures RiskManager.evaluate()/the circuit breaker use.
 * `note` is always present (kept for a stable API contract) but currently
 * always an empty string.
 */
export interface RiskStatus {
  daily_loss_used_percent: number;
  weekly_loss_used_percent: number;
  trades_today: number;
  note: string;
}
