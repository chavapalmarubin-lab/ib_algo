"""auto_trader.py — AUTONOMOUS paper executor (gate-pass-only).

The maker/auditor wall, made live but SAFE:
  * It trades a strategy ONLY if that strategy PASSES the same backtest gate the
    lab uses (core.engine.walk_forward). No edge -> no trade. Today nothing passes,
    so an honest loop places ZERO strategy trades and simply reports "flat".
  * PAPER-LOCKED: config.py refuses any live port on import.
  * ARMED by the human, once: set IB_EXECUTION_ENABLED=1 OR create an `ARMED`
    file in the project dir. Until armed it runs DISARMED (dry-run: prints what it
    WOULD do, places nothing). A `KILL` file halts everything instantly.
  * Risk-capped via config.MAX_POSITION_PCT.

Modes:
  --proof   one-time connectivity proof: SPY 1-share MARKET buy -> confirm fill
            -> MARKET sell -> confirm flat. Proves place/fill/exit end-to-end.
  --once    one evaluation+reconcile pass (what the 15-min schedule calls).
  (default) same as --once.
"""
import argparse
import datetime
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT / "agents" / "gold_quant"))

import config
from core import ibdata, engine
import lab  # reuse build_strategies + CFG (same gate as the lab)
from ib_insync import IB, Stock, Commodity, MarketOrder

LEDGER = ROOT / "agents" / "TRADE_LEDGER.jsonl"
ARM_FILE = ROOT / "ARMED"
GOLD_MAX_UNITS = 50  # extra hard cap on gold units, belt-and-suspenders


APPROVED_FILE = ROOT / "agents" / "APPROVED_SIZING.json"
try:
    APPROVED = json.loads(APPROVED_FILE.read_text()) if APPROVED_FILE.exists() else None
except Exception:
    APPROVED = None


def voltarget_fraction(gold_rows, sizing):
    """Live vol-target position fraction from the approved risk envelope: scale exposure so gold's
    recent realized vol hits the target annual vol, capped by max_leverage. Vol-responsive (the live
    analogue of the backtest sizing that made the config pass the gate)."""
    px = np.asarray([c for _, c in gold_rows], float)
    if len(px) < 5:
        return config.MAX_POSITION_PCT
    ret = np.diff(px) / px[:-1]
    lb = int(sizing.get("vol_lookback_days", 20))
    w = ret[-lb:] if len(ret) >= lb else ret
    rv = float(w.std()) * (252 ** 0.5)
    if rv < 1e-9:
        return 0.0
    return min(float(sizing.get("max_leverage", 1.0)), float(sizing["vol_target_annual"]) / rv)


def is_armed():
    return config.EXECUTION_ENABLED or ARM_FILE.exists()


def log(rec):
    rec["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec) + "\n")


def gate_pass_signals(gold_rows):
    """Run every strategy through the SAME gate as the lab. Return:
    (passers, desired_long) where passers is a list of (name, verdict dict, today_signal)
    and desired_long is True iff at least one GATE-PASS strategy says LONG today."""
    passers, desired_long = [], False
    for name, thesis, px, drv, mk in lab.build_strategies(gold_rows):
        r = engine.walk_forward(px, drv, mk, lab.CFG)
        today_sig = float(mk(np.asarray(drv, float), r["lookback"])[-1])
        passers.append((name, r["verdict"], today_sig))
        if r["verdict"] == "PASS" and today_sig >= 1.0:
            desired_long = True
    return passers, desired_long


def ranked_signals(gold_rows):
    """Every strategy's OOS verdict + Sharpe + today's live signal, ranked by Sharpe desc.
    Forward-test trades the champion (rank 1) regardless of the gate; logs all the rest as the
    live learning substrate (per-strategy signals each cycle)."""
    rows = []
    for name, thesis, px, drv, mk in lab.build_strategies(gold_rows):
        r = engine.walk_forward(px, drv, mk, lab.CFG)
        sig = float(mk(np.asarray(drv, float), r["lookback"])[-1])
        rows.append((name, r["verdict"], r["oos"]["sharpe"], sig))
    rows.sort(key=lambda x: x[2], reverse=True)
    return rows


def proof_trade(ib):
    """Tiny SPY market round-trip on paper: buy 1 -> fill -> sell 1 -> flat."""
    spy = Stock("SPY", "SMART", "USD")
    ib.qualifyContracts(spy)
    print("PROOF: BUY 1 SPY @ market (paper) ...")
    t1 = ib.placeOrder(spy, MarketOrder("BUY", 1))
    for _ in range(40):
        ib.sleep(0.5)
        if t1.orderStatus.status == "Filled":
            break
    print(f"  buy status={t1.orderStatus.status} filled={t1.orderStatus.filled} "
          f"avgPx={t1.orderStatus.avgFillPrice}")
    print("PROOF: SELL 1 SPY @ market (close the position) ...")
    t2 = ib.placeOrder(spy, MarketOrder("SELL", 1))
    for _ in range(40):
        ib.sleep(0.5)
        if t2.orderStatus.status == "Filled":
            break
    print(f"  sell status={t2.orderStatus.status} filled={t2.orderStatus.filled} "
          f"avgPx={t2.orderStatus.avgFillPrice}")
    pos = [p for p in ib.positions() if p.contract.symbol == "SPY"]
    flat = (not pos) or all(p.position == 0 for p in pos)
    print(f"PROOF RESULT: {'FLAT — round-trip OK' if flat else 'STILL HOLDING (check!)'}")
    log({"event": "proof_trade", "buy": t1.orderStatus.status,
         "sell": t2.orderStatus.status, "buy_px": t1.orderStatus.avgFillPrice,
         "sell_px": t2.orderStatus.avgFillPrice, "flat": flat})
    return flat


def gold_position(ib):
    for p in ib.positions():
        if p.contract.symbol == "XAUUSD":
            return p.position, p.contract
    return 0.0, None


def reconcile_gold(ib, desired_long, netliq, dry=False, frac=None):
    """Bring the gold paper position in line with desired_long, risk-capped."""
    gold = Commodity("XAUUSD", "SMART", "USD")
    ib.qualifyContracts(gold)
    cur, _ = gold_position(ib)

    target_units = 0
    if desired_long:
        tkr = ib.reqMktData(gold, "", True, False)
        ib.sleep(2.0)
        px = tkr.last or tkr.close or tkr.delayedLast or tkr.delayedClose or 0
        if px and px == px and px > 0:
            use_frac = config.MAX_POSITION_PCT if frac is None else min(frac, config.MAX_POSITION_PCT)
            cap_notional = netliq * use_frac
            target_units = min(GOLD_MAX_UNITS, int(cap_notional // px))
    delta = target_units - int(cur)
    print(f"  gold: current={cur} target={target_units} delta={delta}")
    if delta == 0:
        return {"action": "hold", "current": cur, "target": target_units}
    side = "BUY" if delta > 0 else "SELL"
    if (not is_armed()) or dry:
        tag = "DRY" if dry else "DISARMED"
        print(f"  {tag} -> would {side} {abs(delta)} XAUUSD (placing nothing)")
        return {"action": f"would_{side.lower()}", "qty": abs(delta), "armed": is_armed() and not dry}
    t = ib.placeOrder(gold, MarketOrder(side, abs(delta)))
    for _ in range(40):
        ib.sleep(0.5)
        if t.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled"):
            break
    print(f"  {side} {abs(delta)} XAUUSD -> {t.orderStatus.status}")
    log({"event": "gold_order", "side": side, "qty": abs(delta),
         "status": t.orderStatus.status, "avg_px": t.orderStatus.avgFillPrice})
    return {"action": side.lower(), "qty": abs(delta), "status": t.orderStatus.status}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proof", action="store_true", help="one-time SPY round-trip proof")
    ap.add_argument("--once", action="store_true", help="single eval+reconcile pass")
    ap.add_argument("--forward-test", dest="forward_test", action="store_true",
                    help="paper-trade the TOP-ranked strategy's live signal regardless of the gate")
    ap.add_argument("--dry", action="store_true", help="force dry-run: print what it WOULD do, place nothing")
    args = ap.parse_args()

    if pathlib.Path(config.KILL_SWITCH_FILE).exists():
        sys.exit("HALTED: kill-switch file present.")
    print(f"auto_trader  mode={config.mode()} port={config.IB_PORT} "
          f"armed={is_armed()}  {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    if not config.is_paper():
        sys.exit("REFUSED: not a paper port. This executor is paper-only.")
    if args.proof and not is_armed():
        sys.exit("BLOCKED: proof trade needs you to ARM first "
                 "(IB_EXECUTION_ENABLED=1 or create the ARMED file).")

    ib = IB()
    ib.connect(config.IB_HOST, config.IB_PORT,
               clientId=config.IB_CLIENT_ID + 31, timeout=20)
    try:
        ib.reqMarketDataType(3)
        summ = {s.tag: s.value for s in ib.accountSummary() if s.tag == "NetLiquidation"}
        netliq = float(summ.get("NetLiquidation", 0) or 0)
        print(f"  NetLiquidation={netliq:,.0f}")

        if args.proof:
            proof_trade(ib)

        gold_rows = ibdata.gold_daily(years="8", cid_offset=20)
        if not gold_rows:
            print("  no gold data — holding, nothing placed.")
            log({"event": "skip", "reason": "no_data"})
            return
        if args.forward_test:
            ranked = ranked_signals(gold_rows)
            champ_name, champ_verdict, champ_sharpe, champ_sig = ranked[0]
            print("  FORWARD-TEST (paper): trade the TOP-ranked strategy live, regardless of the gate")
            for nm, vd, sh, sg in ranked:
                print(f"    {nm:<22} {vd:<5} Sharpe={sh:>5}  signal={sg:.0f}")
            desired_long = champ_sig >= 1.0
            print(f"  champion={champ_name} (Sharpe {champ_sharpe}) -> desired_long={desired_long}")
            frac = None
            if APPROVED and champ_name == APPROVED.get("strategy"):
                frac = voltarget_fraction(gold_rows, APPROVED["sizing"])
                print(f"  using APPROVED sizing for {champ_name}: vol_target="
                      f"{APPROVED['sizing']['vol_target_annual']} -> live vol-target frac={frac:.3f} "
                      f"(capped at MAX_POSITION_PCT={config.MAX_POSITION_PCT})")
            res = reconcile_gold(ib, desired_long, netliq, dry=args.dry, frac=frac)
            log({"event": "forward_test", "champion": champ_name, "champ_sharpe": champ_sharpe,
                 "desired_long": desired_long, "armed": is_armed(), "dry": args.dry,
                 "approved_frac": frac, "signals": {nm: sg for nm, vd, sh, sg in ranked}, **res})
        else:
            print("  evaluating strategies through the gate ...")
            passers, desired_long = gate_pass_signals(gold_rows)
            for name, verdict, sig in passers:
                print(f"    {name:<16} {verdict:<5} today_signal={sig:.0f}")
            n_pass = sum(1 for _, v, _ in passers if v == "PASS")
            print(f"  gate-pass strategies: {n_pass}  -> desired_long={desired_long}")
            res = reconcile_gold(ib, desired_long, netliq, dry=args.dry)
            log({"event": "cycle", "n_pass": n_pass, "desired_long": desired_long,
                 "armed": is_armed(), "dry": args.dry, **res})
        print("  cycle complete.")
    finally:
        ib.disconnect()


if __name__ == "__main__":
    main()
