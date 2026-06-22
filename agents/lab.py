"""agents/lab.py — the STRATEGY LAB: test many strategies, gate them, learn what works.

The learning loop, in code:
  1. fetch market data once (shared),
  2. run EVERY registered strategy through the core walk-forward + Monte-Carlo gate
     (the maker = each signal; the auditor = core.engine — separate, per doctrine),
  3. append each verdict to STRATEGY_LEDGER.jsonl (the memory / state),
  4. print today's leaderboard AND each strategy's track record across all past runs.

Run it daily (scheduled) and the ledger accumulates: "what works" = strategies that
keep passing / keep scoring high out-of-sample; "what doesn't" decays down the board.
Research/signal only — never trades. Adding a new strategy = one entry in STRATEGIES.

  python agents/lab.py
"""
import datetime
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent           # ~/ib_algo/agents
ROOT = HERE.parent                                        # ~/ib_algo
sys.path.insert(0, str(ROOT))                             # core
sys.path.insert(0, str(HERE / "gold_quant"))             # gold_signal

from core import ibdata, engine
import gold_signal as GS

LEDGER = HERE / "STRATEGY_LEDGER.jsonl"
RY_CSV = HERE / "gold_quant" / "data" / "real_yield_10y.csv"

CFG = {
    "sizing": {"vol_target_annual": 0.08, "vol_lookback_days": 20, "max_leverage": 1.0},
    "validation_gates": {"min_sharpe": 1.0, "max_backtest_dd_pct": 20.0,
                         "montecarlo_paths": 10000, "montecarlo_ruin_pct_max": 1.0},
    "drawdown_kill_switch": {"max_drawdown_pct": 12.0},
}


# ── strategy signals (the makers). Each: make_signal(series, lookback) -> {0,1} array ──
def s_trend_ma(px, lookback):
    """Long while price is above its own SMA(lookback) — trend-following."""
    px = np.asarray(px, float)
    sig = np.zeros(len(px))
    for t in range(lookback, len(px)):
        if px[t] > px[t - lookback:t].mean():
            sig[t] = 1.0
    return sig


def s_donchian(px, lookback):
    """Long on an N-day breakout (close >= highest close of prior N) — momentum breakout."""
    px = np.asarray(px, float)
    sig = np.zeros(len(px))
    for t in range(lookback, len(px)):
        if px[t] >= px[t - lookback:t].max():
            sig[t] = 1.0
    return sig



# ── indicators + new strategy signals added from the gold-video digest (2026-06-22) ──
def _rsi(px, period):
    """Wilder RSI over a close series (causal/point-in-time). Neutral 50 during warmup."""
    px = np.asarray(px, float); n = len(px)
    rsi = np.full(n, 50.0)
    if n < period + 1:
        return rsi
    d = np.diff(px)
    gain = np.where(d > 0, d, 0.0); loss = np.where(d < 0, -d, 0.0)
    ag = gain[:period].mean(); al = loss[:period].mean()
    for t in range(period, n):
        ag = (ag * (period - 1) + gain[t - 1]) / period
        al = (al * (period - 1) + loss[t - 1]) / period
        rsi[t] = 100 - 100 / (1 + ag / (al + 1e-9))
    return rsi


def _dayofweek(dates):
    import datetime as _dt
    out = []
    for d in dates:
        try:
            out.append(_dt.date.fromisoformat(str(d)[:10]).weekday())  # Mon=0 .. Thu=3 .. Sun=6
        except Exception:
            out.append(-1)
    return np.asarray(out)


def s_rsi2_meanrev(px, lookback):
    """Connors RSI(2) mean-reversion (Chart Fanatics video), long-only, stateful:
    enter long when close > SMA(200) AND RSI(2) < 20; exit when RSI(2) > 70.
    Fully specified — `lookback` is unused (walk-forward evaluates it OOS as-is)."""
    px = np.asarray(px, float); n = len(px)
    sig = np.zeros(n); rsi = _rsi(px, 2); inpos = False
    for t in range(n):
        if t >= 200:
            sma200 = px[t - 200:t].mean()
            if not inpos and px[t] > sma200 and rsi[t] < 20:
                inpos = True
            elif inpos and rsi[t] > 70:
                inpos = False
        sig[t] = 1.0 if inpos else 0.0
    return sig


def s_rush_hold3(elig, lookback):
    """'Gold Rush' seasonal (Chart Fanatics): on each eligibility bar (Thursday & RSI(2)<40,
    precomputed in the driver) go long and hold 3 bars. `lookback` unused (fixed 3-bar hold)."""
    elig = np.asarray(elig, float); sig = np.zeros(len(elig)); hold = 0
    for t in range(len(elig)):
        if elig[t] > 0:
            hold = 3
        if hold > 0:
            sig[t] = 1.0; hold -= 1
    return sig


def build_strategies(gold_rows):
    """Return [(name, thesis, price_series, driver_series, make_signal)]. One IB fetch, reused."""
    ry_dates, ry_vals = GS.load_real_yield(RY_CSV)
    px_ry, drv_ry = GS.align(gold_rows, ry_dates, ry_vals)     # aligned (gold, real-yield)
    px = np.asarray([c for _, c in gold_rows], float)          # full gold closes
    dates = [d for d, _ in gold_rows]
    _rsi2 = _rsi(px, 2)
    _dow = _dayofweek(dates)
    elig_rush = np.where((_dow == 3) & (_rsi2 < 40), 1.0, 0.0)   # Thursday & RSI(2)<40
    return [
        ("gold_realyield", "long while 10y real-yield trend is down (TH Quant)", px_ry, drv_ry, GS.signal),
        ("gold_trend_ma",  "long while price > its SMA(lookback)",               px,    px,     s_trend_ma),
        ("gold_donchian",  "long on N-day close breakout",                       px,    px,     s_donchian),
        ("gold_rsi2_meanrev", "RSI(2) mean-rev: close>SMA200 & RSI2<20 in, RSI2>70 out [Chart Fanatics]", px, px, s_rsi2_meanrev),
        ("gold_rush_thu",     "seasonal: long Thursdays when RSI(2)<40, hold 3 bars [Chart Fanatics Gold Rush]", px, elig_rush, s_rush_hold3),
    ]


def track_record():
    """Per-strategy history from the ledger: runs, pass-rate, avg OOS Sharpe."""
    rec = {}
    if not LEDGER.exists():
        return rec
    for line in LEDGER.read_text().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        r = rec.setdefault(d["strategy"], {"runs": 0, "passes": 0, "sharpes": []})
        r["runs"] += 1
        r["passes"] += 1 if d.get("verdict") == "PASS" else 0
        if d.get("oos_sharpe") is not None:
            r["sharpes"].append(d["oos_sharpe"])
    return rec


def main():
    print("LAB: fetching market data ...", flush=True)
    gold_rows = ibdata.gold_daily(years="8", cid_offset=20)
    if not gold_rows:
        print("No data — is TWS running + logged into paper?")
        return
    print(f"  gold: {len(gold_rows)} bars  {gold_rows[0][0]} .. {gold_rows[-1][0]}", flush=True)

    ts = datetime.datetime.now().isoformat(timespec="seconds")
    today = []
    for name, thesis, px, drv, mk in build_strategies(gold_rows):
        r = engine.walk_forward(px, drv, mk, CFG)
        today.append((name, thesis, r))
        with open(LEDGER, "a") as f:
            f.write(json.dumps({
                "ts": ts, "strategy": name, "asset": "gold", "verdict": r["verdict"],
                "oos_sharpe": r["oos"]["sharpe"], "max_dd_pct": r["oos"]["max_dd_pct"],
                "oos_return_pct": r["oos"]["total_return_pct"], "ruin_pct": r["mc"]["ruin_pct"],
                "lookback": r["lookback"], "trades": r["trades"],
            }) + "\n")

    today.sort(key=lambda x: x[2]["oos"]["sharpe"], reverse=True)
    print("\n================ TODAY'S LEADERBOARD (by OOS Sharpe) ================")
    print(f"  {'strategy':<16} {'verdict':<7} {'Sharpe':>7} {'DD%':>6} {'ruin%':>7} {'trades':>7}")
    for name, thesis, r in today:
        print(f"  {name:<16} {r['verdict']:<7} {r['oos']['sharpe']:>7} "
              f"{r['oos']['max_dd_pct']:>6} {r['mc']['ruin_pct']:>7} {r['trades']:>7}")

    print("\n================ TRACK RECORD (all runs, the learning) ================")
    rec = track_record()
    for name in sorted(rec, key=lambda n: -(sum(rec[n]['sharpes']) / max(1, len(rec[n]['sharpes'])))):
        h = rec[name]
        avg = sum(h["sharpes"]) / len(h["sharpes"]) if h["sharpes"] else 0
        print(f"  {name:<16} runs={h['runs']:<3} pass={h['passes']:<3} avg OOS Sharpe={avg:.2f}")

    print("\n  Research/signal only — never trades. None cleared the Sharpe>=1.0 gate yet;")
    print("  the lab keeps the leaderboard honest and accumulates a track record over time.")
    print("  Add a strategy = one entry in STRATEGIES. Next: feed it the morning market scan.")


if __name__ == "__main__":
    main()
