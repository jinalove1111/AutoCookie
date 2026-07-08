// Type contracts mirroring the future backend API shapes.
// No logic here — shapes only, used to keep frontend/backend aligned.

export interface BotStatus {
  mode: "paper" | "live";
  liveEnabled: boolean;
  running: boolean;
  lastHeartbeat: string;
}

export interface Bias {
  symbol: string;
  direction: "long" | "short" | "neutral";
  confidence: number;
  updatedAt: string;
}

export interface Signal {
  symbol: string;
  direction: "long" | "short";
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  rr: number;
  status: "pending" | "active" | "filled" | "cancelled";
}

export interface Position {
  symbol: string;
  direction: "long" | "short";
  size: number;
  entryPrice: number;
  pnl: number;
}

export interface RiskStatus {
  maxDrawdown: number;
  currentDrawdown: number;
  dailyLossLimit: number;
  dailyLossUsed: number;
  tradingHalted: boolean;
}

export interface LogEntry {
  timestamp: string;
  level: "info" | "warn" | "error";
  message: string;
}
