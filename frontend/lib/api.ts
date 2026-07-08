// Fetch wrapper for the real JadeCap backend (Milestone 6).
//
// Consistent error pattern: every exported getter returns a Promise that
// resolves to the parsed JSON on success, or REJECTS with a plain `Error`
// (clear message, no thrown response objects) on network failure or a
// non-2xx status. Callers (components) are expected to wrap calls in
// try/catch and render a "backend unreachable" state on rejection — this
// keeps the API layer dumb/typed and all UI fallback decisions in the
// components themselves.

import type {
  Bias,
  BotStatus,
  LogEntry,
  RiskStatus,
  SignalsResponse,
  Trade,
} from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function apiGet<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "GET",
      cache: "no-store",
    });
  } catch (cause) {
    throw new Error(
      `Failed to reach backend at ${API_BASE_URL}${path}: ${
        cause instanceof Error ? cause.message : String(cause)
      }`
    );
  }

  if (!response.ok) {
    throw new Error(
      `Backend returned ${response.status} ${response.statusText} for ${path}`
    );
  }

  return (await response.json()) as T;
}

export function getBotStatus(): Promise<BotStatus> {
  return apiGet<BotStatus>("/dashboard/status");
}

export function getPositions(): Promise<Trade[]> {
  return apiGet<Trade[]>("/dashboard/positions");
}

export function getOpenTrades(): Promise<Trade[]> {
  return apiGet<Trade[]>("/trades/open");
}

export function getClosedTrades(): Promise<Trade[]> {
  return apiGet<Trade[]>("/trades/closed");
}

export function getLogs(): Promise<LogEntry[]> {
  return apiGet<LogEntry[]>("/dashboard/logs");
}

export function getBias(): Promise<Bias> {
  return apiGet<Bias>("/dashboard/bias");
}

export function getSignals(): Promise<SignalsResponse> {
  return apiGet<SignalsResponse>("/dashboard/signals");
}

export function getRiskStatus(): Promise<RiskStatus> {
  return apiGet<RiskStatus>("/dashboard/risk-status");
}
