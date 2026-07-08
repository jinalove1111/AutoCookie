"use client";

import { useState } from "react";
import { getBotStatus, setTradingMode } from "../lib/api";
import { usePolling } from "../lib/usePolling";

type Mode = "backtest" | "paper" | "live";

const MODES: Mode[] = ["backtest", "paper", "live"];

export default function ModeToggle() {
  const { data: status, loading, error } = usePolling(getBotStatus, 7000);

  // Local, request-scoped state for the mode-switch action — separate from
  // the polling hook's own loading/error, which stays untouched below.
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);

  async function handleSwitch(mode: Mode) {
    setSubmitting(true);
    setResult(null);
    setSwitchError(null);
    try {
      const response = await setTradingMode(mode);
      setResult(`Switched to ${response.trading_mode.toUpperCase()} mode.`);
    } catch (cause) {
      // Real safety-gate rejections (e.g. live 403) land here — show the
      // actual backend message in full, never softened or hidden.
      setSwitchError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSubmitting(false);
    }
  }

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
        </>
      )}

      <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
        {MODES.map((mode) => (
          <button
            key={mode}
            type="button"
            onClick={() => handleSwitch(mode)}
            disabled={submitting}
            style={{ padding: "6px 12px" }}
          >
            {submitting ? "Switching..." : `Switch to ${mode.toUpperCase()}`}
          </button>
        ))}
      </div>

      {result && (
        <p style={{ color: "#080", fontWeight: "bold", marginTop: 8 }}>{result}</p>
      )}

      {switchError && (
        <p
          style={{
            color: "#fff",
            background: "#b00",
            fontWeight: "bold",
            padding: 8,
            borderRadius: 4,
            marginTop: 8,
          }}
        >
          Mode switch rejected: {switchError}
        </p>
      )}
    </section>
  );
}
