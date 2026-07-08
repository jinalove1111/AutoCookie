"use client";

import { getLogs } from "../lib/api";
import { usePolling } from "../lib/usePolling";

export default function LogsPanel() {
  const { data: logs, loading, error } = usePolling(getLogs, 7000);

  return (
    <section style={{ border: "1px solid #ccc", borderRadius: 8, padding: 16 }}>
      <h2>Logs</h2>

      {loading && <p>Loading...</p>}

      {!loading && error && (
        <p style={{ color: "#b00" }}>Backend unreachable: {error}</p>
      )}

      {!loading && !error && logs && logs.length === 0 && (
        <p>No recent log entries.</p>
      )}

      {!loading && !error && logs && logs.length > 0 && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
          {logs.map((log) => (
            <li key={log.id} style={{ borderBottom: "1px solid #eee", paddingBottom: 4 }}>
              <div style={{ fontSize: 12, opacity: 0.7 }}>
                {log.timestamp ?? "—"} · {log.module}
              </div>
              <div>
                <strong>{log.decision}</strong> — {log.reason}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
