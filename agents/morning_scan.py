"""morning_scan.py — the pre-open market scan (the morning TRIGGER of the Strategy Lab loop).

Read-only. Each morning it reports:
  1. the overnight / latest gold move,
  2. the macro REGIME (10y real-yield level + recent trend — TH Quant's gold driver),
  3. what each gated strategy SAYS TODAY (long or flat), using its last walk-forward lookback,
  4. the current lab leaderboard (latest verdict per strategy from the ledger).
It writes a dated watch note (MORNING_SCAN_YYYY-MM-DD.md) and prints it. Places NO orders.

GeoMatrix regime + news (Supabase) are an optional enhancement wired later; this v1 runs fully
local and reliable so the morning loop works even if Supabase is unreachable.

  python agents/morning_scan.py
"""
import datetime
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE / "gold_quant"))
sys.path.insert(0, str(HERE))

from core import ibdata
import gold_signal as GS
from lab import s_trend_ma, s_donchian   # reuse the makers (DRY)

LEDGER = HERE / "STRATEGY_LEDGER.jsonl"
RY_CSV = HERE / "gold_quant" / "data" / "real_yield_10y.csv"


def latest_lookbacks():
    """Most recent tuned lookback per strategy from the ledger (fallback 20)."""
    lb = {}
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            lb[d["strategy"]] = d.get("lookback", 20)
    return lb


def latest_leaderboard():
    """Latest verdict/Sharpe per strategy from the ledger, sorted by Sharpe desc."""
    last = {}
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            last[d["strategy"]] = d
    return sorted(last.values(), key=lambda d: d.get("oos_sharpe", -9), reverse=True)


def main():
    gold_rows = ibdata.gold_daily(years="8", cid_offset=22)
    if not gold_rows:
        print("No data — is TWS running + logged into paper?")
        return
    dates = [d for d, _ in gold_rows]
    closes = [c for _, c in gold_rows]
    px = np.asarray(closes, float)
    last, prev = closes[-1], closes[-2]
    chg = (last / prev - 1) * 100

    ry_dates, ry_vals = GS.load_real_yield(RY_CSV)
    ry_last = ry_vals[-1]
    ry_20 = ry_vals[-21] if len(ry_vals) > 21 else ry_vals[0]
    ry_trend = "FALLING (gold-supportive)" if ry_last < ry_20 else "RISING (gold-headwind)"

    lb = latest_lookbacks()
    px_ry, drv_ry = GS.align(gold_rows, ry_dates, ry_vals)
    signals = {
        "gold_realyield": GS.signal(drv_ry, lb.get("gold_realyield", 20))[-1],
        "gold_trend_ma":  s_trend_ma(px, lb.get("gold_trend_ma", 20))[-1],
        "gold_donchian":  s_donchian(px, lb.get("gold_donchian", 20))[-1],
    }
    board = latest_leaderboard()
    today = datetime.date.today().isoformat()

    lines = []
    lines.append(f"# MORNING SCAN — {today}")
    lines.append("")
    lines.append(f"**Gold (XAUUSD):** last {last:.2f}  ({chg:+.2f}% vs prior close {prev:.2f})  ·  data {dates[-1]}")
    lines.append(f"**Macro regime:** 10y real yield {ry_last:.2f}% — {ry_trend} (20d ago {ry_20:.2f}%)")
    lines.append("")
    lines.append("## What each gated strategy says TODAY")
    for name, s in signals.items():
        state = "LONG gold" if s >= 1.0 else "flat / stand aside"
        lines.append(f"- **{name}** (lookback {lb.get(name, 20)}d): {state}")
    lines.append("")
    lines.append("## Current lab leaderboard (latest verdict per strategy)")
    lines.append("| strategy | verdict | OOS Sharpe | ruin% |")
    lines.append("|---|---|---|---|")
    for d in board:
        lines.append(f"| {d['strategy']} | {d.get('verdict')} | {d.get('oos_sharpe')} | {d.get('ruin_pct')} |")
    lines.append("")
    lines.append("_Research/signal only — nothing trades. The lab's gate still rules: no strategy is "
                 "execution-eligible until it clears the gate out-of-sample for weeks. (GeoMatrix regime + "
                 "news layer to be wired next.)_")

    note = "\n".join(lines)
    out = HERE / f"MORNING_SCAN_{today}.md"
    out.write_text(note)
    print(note)
    print(f"\n(written: {out})")


if __name__ == "__main__":
    main()
