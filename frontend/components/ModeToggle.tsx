"use client";

import { getBotStatus } from "../lib/api";
import { usePolling } from "../lib/usePolling";

// Informational display only this milestone — no working mode-switch action.
// Wiring a real switch is explicitly out of scope for Milestone 6.
export default function ModeToggle() {
  const { data: status, loading, error } = usePolling(getBotStatus, 7000);

  return (
    <section style={{ border: "1px solid #ccc", borderRadius: 8, padding: 16 }}>
      <h2>Live Mode</h2>

      {loading && <p>Loading...</p>}

      {!loading && error && (
        <p style={{ color: "#b00" }}>Backend unreachable: {error}</p>
      )}

      {!loading && !error && status && (
        <>
          <p style={{ fontWeight: "bold", fontSize: 16 }}>
            {status.mode.toUpperCase()} MODE
            {status.live_enabled ? " — live trading enabled" : " — live trading locked"}
          </p>
          <label style={{ opacity: 0.5 }}>
            <input type="checkbox" checked={status.live_enabled} disabled readOnly />
            {" "}Live Mode
          </label>
          <p style={{ color: status.trading_allowed ? "#080" : "#b00", fontSize: 14 }}>
            {status.trading_allowed
              ? "Trading currently allowed."
              : "Trading currently NOT allowed (risk gate active)."}
          </p>
          <p style={{ fontSize: 12, opacity: 0.7 }}>
            Mode switching is display-only this milestone — no action wired.
          </p>
        </>
      )}
    </section>
  );
}
