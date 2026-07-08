// Tests for ModeToggle: backtest/paper switch success path, and the
// live-attempt 403 rejection surfaced verbatim to the user -- the exact
// behavior manually verified by the prior audit, pinned here as a
// regression test.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ModeToggle from "./ModeToggle";
import * as api from "../lib/api";

const BOT_STATUS = {
  id: 1,
  mode: "paper" as const,
  live_enabled: false,
  daily_pnl: 0,
  weekly_pnl: 0,
  current_drawdown: 0,
  trading_allowed: true,
  updated_at: null,
};

describe("ModeToggle", () => {
  beforeEach(() => {
    vi.spyOn(api, "getBotStatus").mockResolvedValue(BOT_STATUS);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the current mode once the initial status loads", async () => {
    render(<ModeToggle />);

    expect(await screen.findByText(/PAPER MODE/i)).toBeInTheDocument();
  });

  it("switching to backtest/paper shows the success message from the backend", async () => {
    const setTradingModeSpy = vi
      .spyOn(api, "setTradingMode")
      .mockResolvedValue({ trading_mode: "backtest", applied: true });

    const user = userEvent.setup();
    render(<ModeToggle />);
    await screen.findByText(/PAPER MODE/i);

    await user.click(screen.getByRole("button", { name: /switch to backtest/i }));

    expect(await screen.findByText(/Switched to BACKTEST mode\./i)).toBeInTheDocument();
    expect(setTradingModeSpy).toHaveBeenCalledWith("backtest");
  });

  it("surfaces a live-attempt 403 rejection verbatim, not softened or hidden", async () => {
    const detail =
      "Live trading is not allowed. Requires TRADING_MODE=live AND " +
      "LIVE_TRADING_ENABLED=true in the environment configuration. " +
      "This is a Milestone 1 safety gate; no live orders can be placed.";
    vi.spyOn(api, "setTradingMode").mockRejectedValue(new Error(detail));

    const user = userEvent.setup();
    render(<ModeToggle />);
    await screen.findByText(/PAPER MODE/i);

    await user.click(screen.getByRole("button", { name: /switch to live/i }));

    const errorText = await screen.findByText(new RegExp(detail.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    expect(errorText).toBeInTheDocument();
    expect(screen.queryByText(/Switched to LIVE mode\./i)).not.toBeInTheDocument();
  });

  it("shows a backend-unreachable message when the initial status fetch fails", async () => {
    vi.spyOn(api, "getBotStatus").mockRejectedValue(new Error("network down"));

    render(<ModeToggle />);

    await waitFor(() => {
      expect(screen.getByText(/Backend unreachable: network down/i)).toBeInTheDocument();
    });
  });
});
