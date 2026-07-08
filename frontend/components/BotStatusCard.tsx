"use client";

import { getBotStatus } from "../lib/api";
import { usePolling } from "../lib/usePolling";

export default function BotStatusCard() {
  const { data: status, loading, error } = usePolling(getBotStatus, 7000);

  return (
    <section style={{ border: "1px solid #ccc", borderRadius: 8, padding: 16 }}>
      <h2>Bot Status</h2>
      {loading && <p>Loading...</p>}
      {!loading && error && (
        <p style={{ color: "#b00" }}>Backend unreachable: {error}</p>
      )}
      {!loading && !error && status && (
        <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px", margin: 0 }}>
          <dt>Mode</dt>
          <dd>{status.mode.toUpperCase()}</dd>

          <dt>Live trading</dt>
          <dd>{status.live_enabled ? "ENABLED" : "disabled"}</dd>

          <dt>Trading allowed</dt>
          <dd>{status.trading_allowed ? "yes" : "no"}</dd>

          <dt>Daily PnL</dt>
          <dd>{status.daily_pnl}</dd>

          <dt>Weekly PnL</dt>
          <dd>{status.weekly_pnl}</dd>

          <dt>Current drawdown</dt>
          <dd>{status.current_drawdown}</dd>

          <dt>Updated at</dt>
          <dd>{status.updated_at ?? "—"}</dd>
        </dl>
      )}
    </section>
  );
}
