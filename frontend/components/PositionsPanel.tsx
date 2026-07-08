"use client";

import { getPositions } from "../lib/api";
import { usePolling } from "../lib/usePolling";

export default function PositionsPanel() {
  const { data: positions, loading, error } = usePolling(getPositions, 7000);

  return (
    <section style={{ border: "1px solid #ccc", borderRadius: 8, padding: 16 }}>
      <h2>Open Positions</h2>

      {loading && <p>Loading...</p>}

      {!loading && error && (
        <p style={{ color: "#b00" }}>Backend unreachable: {error}</p>
      )}

      {!loading && !error && positions && positions.length === 0 && (
        <p>No open positions.</p>
      )}

      {!loading && !error && positions && positions.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Symbol</th>
              <th style={{ textAlign: "left" }}>Direction</th>
              <th style={{ textAlign: "right" }}>Entry</th>
              <th style={{ textAlign: "right" }}>Size</th>
              <th style={{ textAlign: "right" }}>PnL</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => (
              <tr key={position.id}>
                <td>{position.symbol}</td>
                <td>{position.direction}</td>
                <td style={{ textAlign: "right" }}>{position.entry_price}</td>
                <td style={{ textAlign: "right" }}>{position.size}</td>
                <td style={{ textAlign: "right" }}>{position.pnl ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
