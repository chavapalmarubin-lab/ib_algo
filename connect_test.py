"""connect_test.py — first IBKR connection test (READ-ONLY).

Mirrors the first step in the Humbled Trader video: connect to TWS paper, then
print account summary, buying power, and any open positions. Places NO orders.

PREREQUISITE: Trader Workstation (TWS) or IB Gateway must be RUNNING and LOGGED IN
to your PAPER account, with the API enabled (see README step 2). Then run:
    python connect_test.py
"""
import sys
import config
from ib_insync import IB


def main():
    ib = IB()
    print(f"Connecting to {config.IB_HOST}:{config.IB_PORT} "
          f"(clientId={config.IB_CLIENT_ID}) — mode={config.mode()} ...")
    try:
        ib.connect(config.IB_HOST, config.IB_PORT, clientId=config.IB_CLIENT_ID, timeout=15)
    except Exception as e:
        print(f"\nCONNECTION FAILED: {e}\n")
        print("Checklist:")
        print("  1. Is TWS/IB Gateway running and logged into your PAPER account?")
        print("  2. Global Config > API > Settings: 'Enable ActiveX and Socket Clients' checked?")
        print(f"  3. Socket port set to {config.IB_PORT}? (7497 = TWS paper)")
        print("  4. 127.0.0.1 added to Trusted IPs?")
        sys.exit(1)

    print("CONNECTED ✓\n")
    summary = {v.tag: v.value for v in ib.accountSummary()}
    for k in ("NetLiquidation", "TotalCashValue", "BuyingPower", "AvailableFunds"):
        print(f"  {k}: {summary.get(k)}")

    pos = ib.positions()
    print(f"\nOpen positions: {len(pos)}")
    for p in pos:
        print(f"  {p.contract.symbol}: {p.position} @ avg {p.avgCost}")

    ib.disconnect()
    print("\nDisconnected. Connection test OK.")


if __name__ == "__main__":
    main()
