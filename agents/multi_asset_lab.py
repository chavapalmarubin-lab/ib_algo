"""agents/multi_asset_lab.py — run EVERY price-generic strategy across the WHOLE universe.

The point: a strategy that passes on gold but fails on the other 9 instruments was
gold-luck, not edge. A strategy that scores well across many uncorrelated markets is
real. This runner reads the CACHED universe (core.multidata), runs each strategy through
the SAME core.engine gate on every instrument, writes MULTI_ASSET_LEDGER.jsonl, and prints
a strategy x instrument Sharpe matrix plus a cross-asset robustness summary.

  python agents/multi_asset_lab.py            # uses cached universe
  python agents/multi_asset_lab.py --fetch    # refresh cache from IBKR first
"""
import datetime
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core import engine, multidata, stats, portfolio
from agents.lab import (CFG, s_trend_ma, s_donchian, s_rsi2_meanrev,
                        _heikin_signal, _breakout_signal, s_passthrough)

LEDGER = HERE / "MULTI_ASSET_LEDGER.jsonl"

# Price-generic strategies that make sense on ANY instrument (no gold-specific driver).
PRICE_STRATS = [
    ("trend_ma", "long while price > its SMA(lookback)", s_trend_ma),
    ("donchian", "long on N-day close breakout", s_donchian),
    ("rsi2_meanrev", "RSI(2) mean-reversion vs SMA200", s_rsi2_meanrev),
]


def strategies_for(rows):
    """Build [(name, px, driver, make_signal)] for one instrument's OHLC rows."""
    px = np.array([c for _, o, h, l, c in rows], float)
    H = np.array([h for _, o, h, l, c in rows], float)
    Lo = np.array([l for _, o, h, l, c in rows], float)
    O = np.array([o for _, o, h, l, c in rows], float)
    out = [(n, px, px, mk) for n, _t, mk in PRICE_STRATS]
    # OHLC strategies via precomputed driver + passthrough
    out.append(("heikin_trend", px, _heikin_signal(O, H, Lo, px), s_passthrough))
    out.append(("prevday_breakout", px, _breakout_signal(H, Lo, px), s_passthrough))
    return out


def _overfit_and_portfolio_report(matrix, summ):
    """Track 2 (deflated Sharpe / multiple-testing) + Track 3 (risk-parity portfolio),
    applied to the best cross-asset strategy. Research only; never trades."""
    ranked = sorted(summ, key=lambda x: -x[3])
    if not ranked:
        return
    champ = ranked[0][0]
    per = matrix.get(champ, {})
    if not per:
        return
    ppy = next(iter(per.values())).get("ppy", 252)
    ann = np.sqrt(ppy)

    # ---- global multiple-testing hurdle from ALL trials run ----
    all_trials, n_trials = [], 0
    for pm in matrix.values():
        for r in pm.values():
            ts = r.get("trial_sharpes", [])
            n_trials += len(ts)
            all_trials.extend(ts)
    sr_trials_std = (float(np.std(all_trials)) / ann) if all_trials else 0.0
    hurdle = stats.expected_max_sharpe(max(2, n_trials), sr_trials_std)

    print("\n================ TRACK 2 — ANTI-OVERFIT (deflated Sharpe) ================")
    print(f"  champion strategy : {champ}")
    print(f"  trials searched   : {n_trials}  (strategy x instrument x lookback backtests)")
    print(f"  multiple-testing hurdle Sharpe : {hurdle*ann:.2f} ann ({hurdle:.4f}/bar)")
    print(f"  {'instrument':<12} {'OOS Sh':>7} {'DSR':>6}  verdict")
    credible = 0
    for inst, r in sorted(per.items(), key=lambda kv: -kv[1]["oos"]["sharpe"]):
        oos = np.asarray(r.get("oos_ret", []), float)
        if len(oos) < 30:
            continue
        dsr, _ = stats.deflated_sharpe_ratio(oos, n_trials, sr_trials_std)
        ok = dsr >= 0.95
        credible += int(ok)
        print(f"  {inst:<12} {r['oos']['sharpe']:>7.2f} {dsr:>6.2f}  {'CREDIBLE' if ok else 'luck-risk'}")
    print(f"  -> {credible}/{len(per)} instruments survive the trials-adjusted test (DSR>=0.95).")
    print("     DSR = P(true Sharpe > hurdle) after skew/kurtosis + #trials. <0.95 = likely overfit.")

    # ---- Track 3: risk-parity portfolio across instruments ----
    series = {inst: np.asarray(r.get("oos_ret", []), float)
              for inst, r in per.items() if len(r.get("oos_ret", [])) >= 30}
    print("\n================ TRACK 3 — PORTFOLIO (risk parity across the universe) ================")
    if len(series) < 2:
        print("  need >=2 instruments with OOS returns to build a portfolio — skipped.")
        return
    pnames, R = portfolio.align_returns(series)
    corr = portfolio.correlation_matrix(R)
    iu = np.triu_indices(len(pnames), 1)
    avg_corr = float(corr[iu].mean()) if len(iu[0]) else 0.0
    w_iv = portfolio.inverse_vol_weights(R)
    w_rp = portfolio.risk_parity_weights(R)
    dr = portfolio.diversification_ratio(w_rp, R)
    sh = lambda x: float(x.mean() / (x.std() + 1e-12)) * ann
    port_rp = portfolio.combine(R, w_rp)
    port_ew = portfolio.combine(R, np.ones(len(pnames)) / len(pnames))
    single = [sh(R[:, i]) for i in range(len(pnames))]
    print(f"  champion strategy : {champ}   instruments: {len(pnames)} ({', '.join(pnames)})")
    print(f"  avg pairwise corr : {avg_corr:.2f}")
    print(f"  {'instrument':<12} {'risk-parity':>12} {'inv-vol':>9}")
    for nm, a, b in sorted(zip(pnames, w_rp, w_iv), key=lambda t: -t[1]):
        print(f"  {nm:<12} {a:>11.1%} {b:>8.1%}")
    print(f"  diversification ratio (risk-parity): {dr:.2f}   (1.0 = none; >1 = real diversification)")
    print(f"  portfolio Sharpe  risk-parity={sh(port_rp):.2f}  equal-weight={sh(port_ew):.2f}"
          f"  mean-single={np.mean(single):.2f}  best-single={max(single):.2f}")
    print("  A risk-parity book that beats the mean single-asset Sharpe with diversification >1")
    print("  is where the edge (if any) compounds with the least single-market dependence.")


def main():
    if "--fetch" in sys.argv:
        print("Refreshing universe cache from IBKR ...", flush=True)
        multidata.cache_universe()
    names = multidata.cached_names()
    if not names:
        print("No cached universe. Run: python agents/multi_asset_lab.py --fetch  (needs TWS up)")
        return
    print(f"Universe: {len(names)} instruments — {', '.join(names)}\n", flush=True)

    ts = datetime.datetime.now().isoformat(timespec="seconds")
    # matrix[strategy][instrument] = {sharpe, verdict, ...}
    matrix = {}
    for name in names:
        rows = multidata.load_cached(name)
        if len(rows) < 300:
            print(f"  {name}: only {len(rows)} bars — skipped (need >=300)")
            continue
        for sname, px, drv, mk in strategies_for(rows):
            try:
                r = engine.walk_forward(px, drv, mk, CFG)
            except Exception as e:
                print(f"  {name}/{sname} ERROR: {e}")
                continue
            matrix.setdefault(sname, {})[name] = r
            with open(LEDGER, "a") as f:
                f.write(json.dumps({
                    "ts": ts, "strategy": sname, "asset": name, "verdict": r["verdict"],
                    "oos_sharpe": r["oos"]["sharpe"], "max_dd_pct": r["oos"]["max_dd_pct"],
                    "oos_return_pct": r["oos"]["total_return_pct"], "ruin_pct": r["mc"]["ruin_pct"],
                    "lookback": r["lookback"], "trades": r["trades"],
                }) + "\n")

    # ---- Sharpe matrix ----
    insts = [n for n in names if any(n in matrix.get(s, {}) for s in matrix)]
    print("================ OOS SHARPE MATRIX (strategy x instrument) ================")
    head = "  " + f"{'strategy':<16}" + "".join(f"{i[:7]:>8}" for i in insts)
    print(head)
    for sname in matrix:
        cells = []
        for i in insts:
            r = matrix[sname].get(i)
            if not r:
                cells.append(f"{'-':>8}")
            else:
                mark = "*" if r["verdict"] == "PASS" else " "
                cells.append(f"{r['oos']['sharpe']:>7.2f}{mark}")
        print("  " + f"{sname:<16}" + "".join(cells))
    print("  (* = cleared the full gate on that instrument)")

    # ---- cross-asset robustness: the real signal ----
    print("\n================ CROSS-ASSET ROBUSTNESS (the real test) ================")
    print(f"  {'strategy':<16} {'passes':>8} {'mean Sh':>9} {'% Sh>0':>8} {'median':>8}")
    summ = []
    for sname, per in matrix.items():
        shs = [r["oos"]["sharpe"] for r in per.values()]
        npass = sum(1 for r in per.values() if r["verdict"] == "PASS")
        pos = 100 * sum(1 for s in shs if s > 0) / len(shs) if shs else 0
        mean = float(np.mean(shs)) if shs else 0
        med = float(np.median(shs)) if shs else 0
        summ.append((sname, npass, len(per), mean, pos, med))
    for sname, npass, ntot, mean, pos, med in sorted(summ, key=lambda x: -x[3]):
        print(f"  {sname:<16} {f'{npass}/{ntot}':>8} {mean:>9.2f} {pos:>7.0f}% {med:>8.2f}")
    _overfit_and_portfolio_report(matrix, summ)
    print("\n  Read this column-down, not row-across: a strategy that PASSES on 1/10 instruments")
    print("  and has mean Sharpe ~0 is luck; one with mean Sharpe>0 across many is a candidate.")
    print("  Research/signal only — never trades. Verdicts are OOS, cost-realistic, point-in-time.")


if __name__ == "__main__":
    main()
