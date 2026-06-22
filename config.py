"""config.py — IB algo bot configuration. PAPER-LOCKED and EXECUTION-OFF by default.

Safety posture (matches Trading Hearts' "research/signal first" rule):
  * Connects to the PAPER port by default. A LIVE port is REFUSED unless you
    personally set IB_ALLOW_LIVE=1 and accept the risk.
  * Order execution is OFF by default — the bot scans and signals but will not
    place any order (even paper) until you set IB_EXECUTION_ENABLED=1.
  * A kill-switch file halts everything instantly.
All values are overridable via environment variables (or a .env file).
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
# Ports: 7497 = TWS paper · 7496 = TWS live · 4002 = IB Gateway paper · 4001 = IB Gateway live
IB_PORT = int(os.getenv("IB_PORT", "7497"))      # PAPER by default
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "11"))

# ── HARD SAFETY GATES ────────────────────────────────────────────────────────
LIVE_PORTS = {7496, 4001}
PAPER_PORTS = {7497, 4002}
ALLOW_LIVE = os.getenv("IB_ALLOW_LIVE", "0") == "1"
if IB_PORT in LIVE_PORTS and not ALLOW_LIVE:
    raise SystemExit(
        f"REFUSED: port {IB_PORT} is a LIVE (real-money) trading port. This bot is paper-only.\n"
        "To ever trade real money you must set IB_ALLOW_LIVE=1 yourself and own that decision."
    )

# The bot may scan/signal always; it may only PLACE ORDERS when this is explicitly on.
EXECUTION_ENABLED = os.getenv("IB_EXECUTION_ENABLED", "0") == "1"

# Risk caps (only used once execution is enabled)
RISK_PER_TRADE = float(os.getenv("IB_RISK_PER_TRADE", "0.01"))       # 1% of account per trade
MAX_POSITION_PCT = float(os.getenv("IB_MAX_POSITION_PCT", "0.10"))   # 10% max single position

# Kill switch: if this file exists in the project dir, the bot halts immediately.
KILL_SWITCH_FILE = os.getenv("IB_KILL_SWITCH", "KILL")


def is_paper() -> bool:
    return IB_PORT in PAPER_PORTS


def mode() -> str:
    return "PAPER" if is_paper() else "LIVE"
