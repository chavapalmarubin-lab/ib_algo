"""backtest_gold.py — simple GOLD baseline to VALIDATE THE LOOP (read-only, NO orders).

Pulls daily XAUUSD bars from IBKR, runs a transparent dual-SMA crossover, and reports
backtest metrics vs buy-and-hold. This proves data -> signal -> backtest end-to-end on our
asset before we drop in the real TH Quant (real-yield) signal. It is a BASELINE, not a
recommended strategy.

  python backtest_gold.py            # default 20/50 SMA on 3Y daily
  python backtest_gold.py 10 30 5 Y  # fast slow years
"""
import sys
import config
from ib_insync import IB, Commodity


def sma(vals, n):
    out = [None] * len(vals)
    run = 0.0
    for i, v in enumerate(vals):
        run += v
        if i >= n:
            run -= vals[i - n]
        if i >= n - 1:
            out[i] = run / n
    return out


def main():
    fast = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    slow = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    years = sys.argv[3] if len(sys.argv) > 3 else "3"

    ib = IB()
    ib.connect(config.IB_HOST, config.IB_PORT, clientId=config.IB_CLIENT_ID + 6, timeout=20)
    ib.reqMarketDataType(3)
    c = Commodity("XAUUSD", "SMART", "USD")
    ib.qualifyContracts(c)
    bars = ib.reqHistoricalData(c, endDateTime="", durationStr=f"{years} Y",
                                barSizeSetting="1 day", whatToShow="MIDPOINT", useRTH=False)
    ib.disconnect()

    closes = [b.close for b in bars]
    dates = [str(b.date) for b in bars]
    n = len(closes)
    print(f"Loaded {n} daily gold bars  {dates[0] if n else '-'} .. {dates[-1] if n else '-'}")
    if n < slow + 5:
        print("Not enough data for the chosen SMAs.")
        return

    f, s = sma(closes, fast), sma(closes, slow)
    position = 0
    entry = 0.0
    entry_date = None
    trades = []
    equity = 1.0
    for i in range(slow, n - 1):
        if f[i] is None or s[i] is None:
            continue
        long_sig = f[i] > s[i]
        if long_sig and position == 0:                       # enter next bar
            position, entry, entry_date = 1, closes[i + 1], dates[i + 1]
        elif (not long_sig) and position == 1:               # exit next bar
            exitp = closes[i + 1]
            ret = exitp / entry - 1
            trades.append((entry_date, dates[i + 1], entry, exitp, ret))
            equity *= (1 + ret)
            position = 0
    if position == 1:
        exitp = closes[-1]
        ret = exitp / entry - 1
        trades.append((entry_date, dates[-1], entry, exitp, ret))
        equity *= (1 + ret)

    rets = [t[4] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    wr = (len(wins) / len(rets) * 100) if rets else 0
    gross_w, gross_l = sum(wins), -sum(losses)
    pf = (gross_w / gross_l) if gross_l > 0 else float("inf")
    bh = closes[-1] / closes[slow] - 1

    print(f"\nDual-SMA {fast}/{slow} on gold (daily, long-or-flat):")
    print(f"  trades: {len(rets)}   win-rate: {wr:.0f}%   profit-factor: {pf:.2f}")
    print(f"  strategy total return: {(equity - 1) * 100:+.1f}%   buy & hold: {bh * 100:+.1f}%")
    if wins:
        print(f"  avg win: {sum(wins)/len(wins)*100:+.2f}%", end="")
    if losses:
        print(f"   avg loss: {sum(losses)/len(losses)*100:+.2f}%", end="")
    print("\n\n(Baseline only — validates the loop. The real edge = TH Quant signal, added next.)")


if __name__ == "__main__":
    main()
