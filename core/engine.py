"""core/engine.py — generic vectorized backtest engine + validation gates.

Shared by every strategy agent. Ported faithfully from TH Quant
(TH_QUANT/research/th_quant_backtest.py): vol-target sizing, point-in-time execution,
walk-forward IS/OOS tuning, Monte-Carlo ruin, TH Quant cost model.

Design: the AGENT supplies the signal (the maker); THIS engine is the separate verifier
(the auditor) — maker != auditor. It never trades; it only judges a strategy.
"""
import math
import numpy as np

# ── TH Quant cost model (Gate 2) ─────────────────────────────────────────────
SPREAD_USD = 0.30
SLIPPAGE_USD = 0.20
SWAP_PER_DAY_USD = -0.15                      # long-gold overnight financing (cost)
ROUND_TURN = SPREAD_USD + 2 * SLIPPAGE_USD    # entry+exit slippage + spread = 0.70


def vol_scale(gret, target, lb, max_lev):
    """Iteration-2 sizing: scale exposure to a constant annual vol using ONLY past returns."""
    n = len(gret)
    sc = np.ones(n)
    if target <= 0:
        return sc
    for t in range(n):
        w = gret[max(0, t - lb):t]            # strictly past window (excludes t)
        if len(w) > 2:
            rv = float(w.std()) * math.sqrt(252)
            sc[t] = min(max_lev, target / rv) if rv > 1e-9 else 0.0
        else:
            sc[t] = 0.0
    return sc


def backtest(px, sig, target, vol_lb, max_lev, start_equity=10000.0):
    px = np.asarray(px, float)
    sig = np.asarray(sig, float)
    ret = np.diff(px, prepend=px[0]) / px
    pos = np.concatenate([[0.0], sig[:-1]]) * vol_scale(ret, target, vol_lb, max_lev)  # act next bar
    turn = np.abs(np.diff(pos, prepend=0.0))
    cost_ret = turn * (ROUND_TURN / px) + pos * (abs(SWAP_PER_DAY_USD) / px)
    stratret = pos * ret - cost_ret
    eq = start_equity * np.cumprod(1 + stratret)
    trades, inpos, entry_i = [], False, 0
    for t in range(len(pos)):
        if pos[t] > 0 and not inpos:
            inpos, entry_i = True, t
        elif pos[t] == 0 and inpos:
            inpos = False
            trades.append(eq[t] / eq[entry_i] - 1)
    return eq, stratret, np.array(trades)


def metrics(eq, stratret):
    ann = math.sqrt(252)
    sharpe = (stratret.mean() / (stratret.std() + 1e-9)) * ann
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    return {"sharpe": round(float(sharpe), 2),
            "max_dd_pct": round(float(-dd.min() * 100), 1),
            "total_return_pct": round(float(eq[-1] / eq[0] - 1) * 100, 1)}


def monte_carlo(stratret, ruin_dd_pct, paths=10000, start=10000.0):
    rng = np.random.default_rng(11)
    n = len(stratret)
    ruin_level = 1 - ruin_dd_pct / 100
    ruined = 0
    for _ in range(paths):
        samp = rng.choice(stratret, n, replace=True)
        eq = start * np.cumprod(1 + samp)
        if (eq / np.maximum.accumulate(eq)).min() < ruin_level:
            ruined += 1
    return {"ruin_pct": round(100 * ruined / paths, 2)}


def walk_forward(px, drv, make_signal, cfg, lookbacks=range(5, 60, 5)):
    """Gate 4: tune the ONE param in-sample (first 60%) by Sharpe, evaluate OOS (last 40%),
    then judge OOS against the validation gates. Returns the agent's PASS/FAIL verdict.

    px         = price series (e.g. gold closes)
    drv        = signal driver series aligned to px (e.g. real yield)
    make_signal(drv_slice, lookback) -> signal array  (supplied by the agent)
    """
    s = cfg["sizing"]
    v = cfg["validation_gates"]
    target, vol_lb, max_lev = s["vol_target_annual"], s["vol_lookback_days"], s["max_leverage"]
    n = len(px)
    split = int(n * 0.6)
    px_is, drv_is = px[:split], drv[:split]
    px_oos, drv_oos = px[split:], drv[split:]

    best = None
    for L in lookbacks:
        sig = make_signal(drv_is, L)
        eq, sr, _ = backtest(px_is, sig, target, vol_lb, max_lev)
        sh = metrics(eq, sr)["sharpe"]
        if best is None or sh > best[1]:
            best = (L, sh)
    L = best[0]

    sig = make_signal(drv_oos, L)
    eq, sr, tr = backtest(px_oos, sig, target, vol_lb, max_lev)
    m = metrics(eq, sr)
    mc = monte_carlo(sr, cfg["drawdown_kill_switch"]["max_drawdown_pct"], v["montecarlo_paths"])
    passed = (m["sharpe"] >= v["min_sharpe"]
              and m["max_dd_pct"] <= v["max_backtest_dd_pct"]
              and mc["ruin_pct"] <= v["montecarlo_ruin_pct_max"])
    return {"lookback": L, "is_sharpe": best[1], "oos": m, "mc": mc,
            "trades": int(len(tr)), "verdict": "PASS" if passed else "FAIL"}
