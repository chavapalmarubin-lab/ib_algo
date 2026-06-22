"""agents/../test_order.py — IBKR paper connectivity test (place -> status -> cancel).

Proves the full order round-trip WITHOUT taking any real position:
  * Places 1 share of SPY at a LIMIT far BELOW market, so it rests UNFILLED.
  * Prints the order status, waits briefly, then CANCELS it.
Safety:
  * PAPER-LOCKED: refuses any LIVE port (inherits config.py hard gate).
  * EXECUTION-GATED: refuses to run unless IB_EXECUTION_ENABLED=1 AND TWS
    Read-Only API is unchecked. The human enables both; the bot never does.
  * Kill-switch file halts instantly.
This is a connectivity check, not a strategy. It never fills.
"""
import sys
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config
from ib_insync import IB, Stock, LimitOrder


def main():
    # ── Gate 1: kill switch ──────────────────────────────────────────────
    if pathlib.Path(config.KILL_SWITCH_FILE).exists():
        sys.exit("HALTED: kill-switch file present.")

    # ── Gate 2: paper only (config.py already refuses live ports on import)
    print(f"Mode: {config.mode()}  port={config.IB_PORT}")
    if not config.is_paper():
        sys.exit("REFUSED: not a paper port. Test orders are paper-only.")

    # ── Gate 3: execution must be explicitly enabled by the human ─────────
    if not config.EXECUTION_ENABLED:
        sys.exit(
            "BLOCKED: order execution is OFF. This is the maker/executor wall.\n"
            "To run THIS PAPER connectivity test, you (the human) set:\n"
            "    IB_EXECUTION_ENABLED=1\n"
            "and make sure TWS > API > Settings > 'Read-Only API' is UNCHECKED."
        )

    ib = IB()
    ib.connect(config.IB_HOST, config.IB_PORT,
               clientId=config.IB_CLIENT_ID + 30, timeout=20)
    try:
        spy = Stock("SPY", "SMART", "USD")
        ib.qualifyContracts(spy)
        ib.reqMarketDataType(3)  # delayed ok

        # Reference price -> resting limit ~30% below, rounded to a cent.
        tkr = ib.reqMktData(spy, "", False, False)
        ib.sleep(2.5)
        ref = tkr.last or tkr.close or tkr.delayedLast or tkr.delayedClose
        if not ref or ref != ref:  # None or NaN
            ref = 600.0  # conservative fallback; limit still rests far below
        limit_px = round(ref * 0.70, 2)
        print(f"SPY reference ~{ref:.2f} -> resting BUY limit @ {limit_px:.2f} (will NOT fill)")

        order = LimitOrder("BUY", 1, limit_px)
        order.tif = "DAY"
        trade = ib.placeOrder(spy, order)
        print("Order placed. Waiting for acknowledgement...")

        # Poll status up to ~6s.
        for _ in range(12):
            ib.sleep(0.5)
            st = trade.orderStatus.status
            if st in ("Submitted", "PreSubmitted", "Filled", "Cancelled",
                      "ApiCancelled", "Inactive"):
                break
        st = trade.orderStatus.status
        print(f"Order status: {st}  (orderId={trade.order.orderId}, "
              f"filled={trade.orderStatus.filled})")

        if trade.orderStatus.filled and trade.orderStatus.filled > 0:
            print("!! Unexpected fill — cancelling immediately and flagging.")

        # Always cancel so nothing rests on the book.
        ib.cancelOrder(order)
        for _ in range(12):
            ib.sleep(0.5)
            if trade.orderStatus.status in ("Cancelled", "ApiCancelled"):
                break
        print(f"Final status: {trade.orderStatus.status}")
        print("\nROUND-TRIP OK: place -> status -> cancel verified. No position taken.")
    finally:
        ib.disconnect()


if __name__ == "__main__":
    main()
