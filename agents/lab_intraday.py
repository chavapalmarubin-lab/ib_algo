"""agents/lab_intraday.py — INTRADAY strategy lab (gold 15m), same gate as the daily lab.

Unlocks the intraday strategies the scout kept logging as "codeable but needs intraday bars":
momentum-breakout + volatility filter (DaviddTech), SMA fast/slow cross, Z-score mean-reversion.
Uses core.ibdata.gold_intraday + the engine with the correct periods-per-year (annualization),
so Sharpe/ruin/DD are computed honestly for the intraday frequency. Research/signal only.
"""
import datetime, json, pathlib, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from core import ibdata, engine
import lab  # reuse CFG (same gate thresholds)

LEDGER = HERE / "INTRADAY_LEDGER.jsonl"
BAR = "15 mins"


def s_sma_cross(px, lookback):
    """Long while fast SMA(lookback) > slow SMA(2*lookback) — intraday trend."""
    px = np.asarray(px, float); n = len(px); sig = np.zeros(n)
    f, s = lookback, lookback * 2
    for t in range(s, n):
        if px[t - f:t].mean() > px[t - s:t].mean():
            sig[t] = 1.0
    return sig


def s_zscore_mr(px, lookback):
    """Z-score mean reversion: long when z<-1 (oversold vs SMA), exit when z>0. Stateful."""
    px = np.asarray(px, float); n = len(px); sig = np.zeros(n); inpos = False
    for t in range(lookback, n):
        w = px[t - lookback:t]; sd = w.std()
        z = (px[t] - w.mean()) / (sd + 1e-9)
        if not inpos and z < -1.0:
            inpos = True
        elif inpos and z > 0.0:
            inpos = False
        sig[t] = 1.0 if inpos else 0.0
    return sig


def breakout_vol_signal(O, H, L, C):
    """DaviddTech S1 precomputed (causal): fast SMA>slow SMA AND close>close[-20] AND green candle."""
    O = np.asarray(O, float); C = np.asarray(C, float); n = len(C)
    sig = np.zeros(n); f, s = 10, 20
    for t in range(20, n):
        if C[t - f:t].mean() > C[t - s:t].mean() and C[t] > C[t - 20] and C[t] > O[t]:
            sig[t] = 1.0
    return sig


def s_passthrough(drv, lookback):
    return np.asarray(drv, float)


def main():
    print(f"INTRADAY LAB: fetching gold {BAR} ...", flush=True)
    rows = ibdata.gold_intraday(bar=BAR, duration="6 M", cid_offset=24)
    if not rows or len(rows) < 500:
        print(f"  not enough intraday data ({len(rows) if rows else 0} bars) — TWS up? Trying 2 M ...")
        rows = ibdata.gold_intraday(bar=BAR, duration="2 M", cid_offset=25)
    if not rows:
        print("  no intraday data — is TWS running on the paper account?"); return
    C = np.array([r[4] for r in rows], float)
    O = np.array([r[1] for r in rows], float)
    H = np.array([r[2] for r in rows], float)
    L = np.array([r[3] for r in rows], float)
    # periods-per-year from the actual timestamps (honest annualization)
    try:
        t0 = datetime.datetime.fromisoformat(rows[0][0].replace(" ", "T"))
        t1 = datetime.datetime.fromisoformat(rows[-1][0].replace(" ", "T"))
        yrs = max(1e-6, (t1 - t0).total_seconds() / (365.25 * 86400))
        ppy = len(rows) / yrs
    except Exception:
        ppy = 96 * 252  # 15-min, ~24h gold fallback
    print(f"  gold: {len(rows)} {BAR} bars  {rows[0][0]} .. {rows[-1][0]}  ppy~{ppy:,.0f}", flush=True)

    brk = breakout_vol_signal(O, H, L, C)
    strategies = [
        ("intraday_breakout_vol", "fast SMA>slow & close>close[-20] & green [DaviddTech S1]", C, brk, s_passthrough),
        ("intraday_sma_cross",    "fast SMA(lb) > slow SMA(2lb)",                              C, C,   s_sma_cross),
        ("intraday_zscore_mr",    "z-score mean reversion: long z<-1, exit z>0",               C, C,   s_zscore_mr),
    ]
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    results = []
    for name, thesis, px, drv, mk in strategies:
        r = engine.walk_forward(px, drv, mk, lab.CFG, ppy=ppy)
        results.append((name, r))
        with open(LEDGER, "a") as f:
            f.write(json.dumps({"ts": ts, "bar": BAR, "strategy": name, "verdict": r["verdict"],
                                "oos_sharpe": r["oos"]["sharpe"], "max_dd_pct": r["oos"]["max_dd_pct"],
                                "ruin_pct": r["mc"]["ruin_pct"], "lookback": r["lookback"],
                                "trades": r["trades"], "ppy": round(ppy)}) + "\n")
    results.sort(key=lambda x: x[1]["oos"]["sharpe"], reverse=True)
    print("\n========= INTRADAY LEADERBOARD (gold 15m, by OOS Sharpe) =========")
    print(f"  {'strategy':<22}{'verdict':<7}{'Sharpe':>7}{'DD%':>6}{'ruin%':>7}{'trades':>7}")
    for name, r in results:
        print(f"  {name:<22}{r['verdict']:<7}{r['oos']['sharpe']:>7}{r['oos']['max_dd_pct']:>6}"
              f"{r['mc']['ruin_pct']:>7}{r['trades']:>7}")
    npass = sum(1 for _, r in results if r["verdict"] == "PASS")
    print(f"\n  {npass}/{len(results)} cleared the gate. Research/signal only — gate decides, live = CEO's hands.")
    print("  Intraday bars now flow through the same gate + improver + forward-test as daily.")


if __name__ == "__main__":
    main()
