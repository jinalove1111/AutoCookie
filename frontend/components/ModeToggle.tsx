export default function ModeToggle() {
  return (
    <section style={{ border: "1px solid #ccc", borderRadius: 8, padding: 16 }}>
      <h2>Live Mode</h2>
      <label style={{ opacity: 0.5 }}>
        <input type="checkbox" disabled />
        {" "}Live Mode
      </label>
      <p style={{ color: "#b00", fontSize: 14 }}>
        Live trading locked — enable via LIVE_TRADING_ENABLED env var
      </p>
    </section>
  );
}
