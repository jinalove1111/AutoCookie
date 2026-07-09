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

      {!loading && !error && signals && signals.signals.length === 0 && (
        <p>No signals recorded yet.</p>
      )}

      {!loading && !error && signals && signals.signals.length > 0 && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
          {signals.signals.map((signal) => (
            <li key={signal.id} style={{ borderBottom: "1px solid #eee", paddingBottom: 4 }}>
              <div style={{ fontSize: 12, opacity: 0.7 }}>
                {signal.timestamp} · {signal.symbol} · {signal.status}
              </div>
              <div>
                <strong>{signal.direction}</strong> — entry {signal.entry_price}, RR{" "}
                {signal.rr.toFixed(2)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
