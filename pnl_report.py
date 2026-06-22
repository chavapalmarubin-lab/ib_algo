"""pnl_report.py — daily P&L + forward-test track record for the IBKR paper lab.

Read-only. Pulls the authoritative numbers from IBKR (NetLiq, realized/unrealized P&L,
open positions) and joins them with the forward-test ledger (which strategy is champion,
how often each strategy is long, orders placed) so you can see whether the live paper
forward-test is working — without trusting any backtest claim.
"""
import json
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import config
from ib_insync import IB

LEDGER = ROOT / "agents" / "TRADE_LEDGER.jsonl"
START_EQUITY = 1_000_000.0   # paper account opening balance


def acct_numbers(ib):
    s = {v.tag: v.value for v in ib.accountSummary()
         if v.tag in ("NetLiquidation", "UnrealizedPnL", "RealizedPnL", "TotalCashValue")}
    return {k: float(s.get(k, 0) or 0) for k in
            ("NetLiquidation", "UnrealizedPnL", "RealizedPnL", "TotalCashValue")}


def positions(ib):
    out = []
    for p in ib.portfolio():
        out.append((p.contract.symbol, p.position, p.averageCost,
                    getattr(p, "marketPrice", 0), getattr(p, "unrealizedPNL", 0)))
    return out


def ledger_stats():
    if not LEDGER.exists():
        return None
    cycles = 0
    champs = defaultdict(int)
    long_count = defaultdict(int)
    sig_total = defaultdict(int)
    orders = []
    last_champ = last_sig = None
    for line in LEDGER.read_text().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        ev = d.get("event")
        if ev == "forward_test":
            cycles += 1
            c = d.get("champion")
            champs[c] += 1
            last_champ = c
            last_sig = d.get("desired_long")
            for nm, sg in (d.get("signals") or {}).items():
                sig_total[nm] += 1
                if sg and sg >= 1:
                    long_count[nm] += 1
        elif ev == "gold_order":
            orders.append((d.get("ts"), d.get("side"), d.get("qty"),
                           d.get("status"), d.get("avg_px")))
    return {"cycles": cycles, "champs": dict(champs), "long_count": dict(long_count),
            "sig_total": dict(sig_total), "orders": orders,
            "last_champ": last_champ, "last_sig": last_sig}


def main():
    if not config.is_paper():
        sys.exit("REFUSED: not a paper port.")
    ib = IB()
    ib.connect(config.IB_HOST, config.IB_PORT, clientId=config.IB_CLIENT_ID + 33, timeout=20)
    try:
        ib.reqMarketDataType(3)
        a = acct_numbers(ib)
        pos = positions(ib)
    finally:
        ib.disconnect()

    net = a["NetLiquidation"]
    total_pnl = net - START_EQUITY
    print("=" * 56)
    print(f"  IBKR PAPER LAB — P&L  ({config.mode()} acct, port {config.IB_PORT})")
    print("=" * 56)
    print(f"  NetLiquidation : ${net:,.2f}")
    print(f"  Total P&L      : ${total_pnl:,.2f}  ({total_pnl/START_EQUITY*100:+.3f}% vs $1.00M start)")
    print(f"  Realized P&L   : ${a['RealizedPnL']:,.2f}")
    print(f"  Unrealized P&L : ${a['UnrealizedPnL']:,.2f}")
    print(f"  Cash           : ${a['TotalCashValue']:,.2f}")

    print("\n  OPEN POSITIONS:")
    live = [p for p in pos if p[1] != 0]
    if not live:
        print("    (flat — no open positions)")
    else:
        for sym, qty, avg, mkt, upnl in live:
            print(f"    {sym:<8} qty={qty:<8g} avg={avg:<12,.2f} mkt={mkt:<10,.2f} uPnL=${upnl:,.2f}")

    st = ledger_stats()
    print("\n  FORWARD-TEST TRACK RECORD:")
    if not st or st["cycles"] == 0:
        print("    (no forward-test cycles logged yet — runs every 15 min on weekdays)")
    else:
        print(f"    cycles logged : {st['cycles']}")
        print(f"    champion now  : {st['last_champ']}  (desired_long={st['last_sig']})")
        orders = st["orders"]
        print(f"    paper orders placed : {len(orders)}")
        for ts, side, qty, status, px in orders[-5:]:
            print(f"      {ts}  {side} {qty} XAUUSD -> {status} @ {px}")
        print("    per-strategy % long (live cycles):")
        for nm in sorted(st["sig_total"], key=lambda n: -st["long_count"].get(n, 0)):
            tot = st["sig_total"][nm]
            lc = st["long_count"].get(nm, 0)
            print(f"      {nm:<22} {lc}/{tot} long  ({100*lc/max(1,tot):.0f}%)")
    print("=" * 56)


if __name__ == "__main__":
    main()
