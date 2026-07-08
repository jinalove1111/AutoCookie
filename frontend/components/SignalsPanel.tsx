"use client";

import { getSignals } from "../lib/api";
import { usePolling } from "../lib/usePolling";

export default function SignalsPanel() {
  const { data: signals, loading, error } = usePolling(getSignals, 10000);

  return (
    <section style={{ border: "1px solid #ccc", borderRadius: 8, padding: 16 }}>
      <h2>Active Signals</h2>

      {loading && <p>Loading...</p>}

      {!loading && error && (
        <p style={{ color: "#b00" }}>Backend unreachable: {error}</p>
      )}

      {!loading && !error && signals && (
        <>
          <span
            style={{
              display: "inline-block",
              background: "#eee",
              border: "1px solid #ccc",
              borderRadius: 4,
              padding: "2px 8px",
              fontSize: 12,
              marginBottom: 8,
            }}
          >
            Not live yet
          </span>
          <p style={{ margin: "4px 0" }}>
            {signals.signals.length === 0
              ? "No signals recorded."
              : `${signals.signals.length} signal(s).`}
          </p>
          <p style={{ margin: "4px 0", fontSize: 12, opacity: 0.7 }}>{signals.note}</p>
        </>
      )}
    </section>
  );
}
