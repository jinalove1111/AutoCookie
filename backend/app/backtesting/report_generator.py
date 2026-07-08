"""Report generator for producing human-readable backtest summaries."""

import csv
from typing import Any

MAX_TABLE_ROWS = 50
TRADE_FIELDS = ["direction", "entry_price", "exit_price", "pnl", "opened_at", "closed_at"]


class ReportGenerator:
    """Formats a BacktestResult into readable reports or exportable files."""

    def generate(self, result: Any) -> str:
        """Produces a human-readable markdown summary of the backtest result."""
        total_trades = getattr(result, "total_trades", 0)
        win_rate = getattr(result, "win_rate", 0.0)
        total_pnl = getattr(result, "total_pnl", 0.0)
        max_drawdown = getattr(result, "max_drawdown", 0.0)
        trades = getattr(result, "trades", []) or []

        header = (
            "# Backtest Report\n\n"
            f"- **Total trades:** {total_trades}\n"
            f"- **Win rate:** {win_rate * 100:.2f}%\n"
            f"- **Total PnL:** {total_pnl:.2f}\n"
            f"- **Max drawdown:** {max_drawdown * 100:.2f}%\n"
        )

        if total_trades == 0 or not trades:
            return header + "\nNo trades were executed during this backtest.\n"

        lines = [
            "\n## Trades\n",
            "| Direction | Entry Price | Exit Price | PnL | Opened At | Closed At |",
            "|---|---|---|---|---|---|",
        ]
        shown = trades[:MAX_TABLE_ROWS]
        for t in shown:
            lines.append(
                f"| {t.get('direction', '')} | {t.get('entry_price', '')} | "
                f"{t.get('exit_price', '')} | {t.get('pnl', 0):.2f} | "
                f"{t.get('opened_at', '')} | {t.get('closed_at', '')} |"
            )

        remaining = len(trades) - len(shown)
        if remaining > 0:
            lines.append(f"\n_...and {remaining} more trade(s) not shown._\n")

        return header + "\n".join(lines) + "\n"

    def export_csv(self, result: Any, path: str) -> None:
        """Writes the backtest result's trade-by-trade data to a CSV file at path."""
        trades = getattr(result, "trades", []) or []
        fieldnames = list(trades[0].keys()) if trades else TRADE_FIELDS

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for trade in trades:
                writer.writerow(trade)
