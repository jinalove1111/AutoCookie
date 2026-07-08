"use client";

import { getBias } from "../lib/api";
import { usePolling } from "../lib/usePolling";

export default function BiasCard() {
  const { data: bias, loading, error } = usePolling(getBias, 10000);

  return (
    <section style={{ border: "1px solid #ccc", borderRadius: 8, padding: 16 }}>
      <h2>Current Bias</h2>

      {loading && <p>Loading...</p>}

      {!loading && error && (
        <p style={{ color: "#b00" }}>Backend unreachable: {error}</p>
      )}

      {!loading && !error && bias && (
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
          <p style={{ margin: "4px 0" }}>Symbol: {bias.symbol}</p>
          <p style={{ margin: "4px 0" }}>HTF bias: {bias.htf_bias}</p>
          <p style={{ margin: "4px 0" }}>LTF bias: {bias.ltf_bias}</p>
          <p style={{ margin: "4px 0", fontSize: 12, opacity: 0.7 }}>{bias.note}</p>
        </>
      )}
    </section>
  );
}
