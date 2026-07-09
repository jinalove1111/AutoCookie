"use client";

import { getRiskStatus } from "../lib/api";
import { usePolling } from "../lib/usePolling";

export default function RiskStatusPanel() {
  const { data: risk, loading, error } = usePolling(getRiskStatus, 10000);

  return (
    <section style={{ border: "1px solid #ccc", borderRadius: 8, padding: 16 }}>
      <h2>Risk Status</h2>

      {loading && <p>Loading...</p>}

      {!loading && error && (
        <p style={{ color: "#b00" }}>Backend unreachable: {error}</p>
      )}

      {!loading && !error && risk && (
        <>
          <p style={{ margin: "4px 0" }}>
            Daily loss used: {risk.daily_loss_used_percent.toFixed(2)}%
          </p>
          <p style={{ margin: "4px 0" }}>
            Weekly loss used: {risk.weekly_loss_used_percent.toFixed(2)}%
          </p>
          <p style={{ margin: "4px 0" }}>Trades today: {risk.trades_today}</p>
          {risk.note && (
            <p style={{ margin: "4px 0", fontSize: 12, opacity: 0.7 }}>{risk.note}</p>
          )}
        </>
      )}
    </section>
  );
}
