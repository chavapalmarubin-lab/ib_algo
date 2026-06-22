"""gold_data_test.py — read-only GOLD market-data test for IBKR.

Resolves IBKR's gold contract and pulls recent daily bars. Places NO orders.
Tries spot XAUUSD (Commodity then Forex spec); if neither qualifies, lists matching
symbols so we can pick the right one. Proves our asset (gold, extending TH Quant) has
working data before we build the strategy.
"""
import config
from ib_insync import IB, Forex, Commodity


def try_contract(ib, c, label):
    try:
        q = ib.qualifyContracts(c)
        if not q:
            print(f"[{label}] did not qualify")
            return None
        cc = q[0]
        print(f"[{label}] QUALIFIED: conId={cc.conId} {cc.symbol} {cc.secType} "
              f"exch={cc.exchange} cur={cc.currency}")
        return cc
    except Exception as e:
        print(f"[{label}] error: {e}")
        return None


def main():
    ib = IB()
    ib.connect(config.IB_HOST, config.IB_PORT, clientId=config.IB_CLIENT_ID + 5, timeout=15)
    ib.reqMarketDataType(3)  # delayed data if no live subscription

    contract = (try_contract(ib, Commodity("XAUUSD", "SMART", "USD"), "CMDTY XAUUSD")
                or try_contract(ib, Forex("XAUUSD"), "FX XAUUSD"))

    if not contract:
        print("\nNo direct gold contract qualified. Matching symbols for 'XAUUSD':")
        try:
            for d in ib.reqMatchingSymbols("XAUUSD"):
                c = d.contract
                print(f"  {c.symbol} {c.secType} {c.primaryExchange} {c.currency}")
        except Exception as e:
            print(f"  matching-symbols error: {e}")
        ib.disconnect()
        return

    got = False
    for what in ("MIDPOINT", "TRADES", "BID_ASK"):
        try:
            bars = ib.reqHistoricalData(contract, endDateTime="", durationStr="30 D",
                                        barSizeSetting="1 day", whatToShow=what, useRTH=False)
            if bars:
                print(f"\n{len(bars)} daily bars (whatToShow={what}); last 5:")
                for b in bars[-5:]:
                    print(f"  {b.date}  O{b.open}  H{b.high}  L{b.low}  C{b.close}")
                got = True
                break
            else:
                print(f"whatToShow={what}: 0 bars (likely no market-data permission for this type)")
        except Exception as e:
            print(f"whatToShow={what} error: {e}")

    if not got:
        print("\nNo historical bars returned. This usually means the paper account lacks a "
              "market-data subscription for spot metals. Options: enable delayed/free data in the "
              "client portal, or switch the gold instrument to GC futures (COMEX).")
    ib.disconnect()


if __name__ == "__main__":
    main()
