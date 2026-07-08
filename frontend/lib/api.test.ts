// Tests for the fetch wrappers in lib/api.ts: success case, non-2xx
// error propagation (parsing the `detail` field for setTradingMode),
// and network failure -- all against a stubbed global `fetch`, no real
// network calls.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getBotStatus, setTradingMode } from "./api";

function jsonResponse(body: unknown, init: { status?: number; ok?: boolean } = {}) {
  const status = init.status ?? 200;
  return {
    ok: init.ok ?? (status >= 200 && status < 300),
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: async () => body,
  } as Response;
}

describe("apiGet (via getBotStatus)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with parsed JSON on a 200 response", async () => {
    const body = {
      id: 1,
      mode: "paper",
      live_enabled: false,
      daily_pnl: 0,
      weekly_pnl: 0,
      current_drawdown: 0,
      trading_allowed: true,
      updated_at: null,
    };
    fetchMock.mockResolvedValueOnce(jsonResponse(body));

    const result = await getBotStatus();

    expect(result).toEqual(body);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/dashboard/status",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("rejects with a plain Error including the status on a non-2xx response", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}, { status: 500, ok: false }));

    await expect(getBotStatus()).rejects.toThrow(/Backend returned 500/);
  });

  it("rejects with a plain Error on network failure", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(getBotStatus()).rejects.toThrow(/Failed to reach backend/);
  });
});

describe("setTradingMode", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with the parsed response on success", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ trading_mode: "paper", applied: true })
    );

    const result = await setTradingMode("paper");

    expect(result).toEqual({ trading_mode: "paper", applied: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/settings/mode",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trading_mode: "paper" }),
      })
    );
  });

  it("surfaces the backend's `detail` field verbatim on a non-2xx response (live 403)", async () => {
    const detail =
      "Live trading is not allowed. Requires TRADING_MODE=live AND " +
      "LIVE_TRADING_ENABLED=true in the environment configuration. " +
      "This is a Milestone 1 safety gate; no live orders can be placed.";
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail }, { status: 403, ok: false }));

    await expect(setTradingMode("live")).rejects.toThrow(detail);
  });

  it("falls back to a generic message when the error body isn't parseable JSON", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => {
        throw new SyntaxError("not json");
      },
    } as unknown as Response);

    await expect(setTradingMode("paper")).rejects.toThrow(/Backend returned 500/);
  });

  it("rejects with a plain Error on network failure", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(setTradingMode("paper")).rejects.toThrow(/Failed to reach backend/);
  });
});
