import BotStatusCard from "../components/BotStatusCard";
import BiasCard from "../components/BiasCard";
import SignalsPanel from "../components/SignalsPanel";
import PositionsPanel from "../components/PositionsPanel";
import RiskStatusPanel from "../components/RiskStatusPanel";
import LogsPanel from "../components/LogsPanel";
import ModeToggle from "../components/ModeToggle";

export default function DashboardPage() {
  return (
    <main style={{ padding: 24, display: "grid", gap: 16 }}>
      <h1>JadeCap Trading Bot — Dashboard</h1>
      <ModeToggle />
      <BotStatusCard />
      <BiasCard />
      <SignalsPanel />
      <PositionsPanel />
      <RiskStatusPanel />
      <LogsPanel />
    </main>
  );
}
