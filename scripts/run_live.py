"""run_live.py

Future purpose: run the trading strategy in LIVE_MODE against the real
exchange account, placing real orders. Not implemented in Milestone 1
(infra/foundation only) -- no trading logic lives here.

The one piece of real logic in this file is a safety gate: LIVE trading
must never start unless it has been explicitly enabled via
Settings().is_live_trading_allowed. This is a guard-rail, not a
strategy, and it must run before anything else in this script.
"""

import sys

from app.config import Settings

if __name__ == "__main__":
    if not Settings().is_live_trading_allowed:
        print("LIVE trading is disabled. Set LIVE_TRADING_ENABLED to allow it.")
        sys.exit(1)

    print("TODO: implement in later milestone")
