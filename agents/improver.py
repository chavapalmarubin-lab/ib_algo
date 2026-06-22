"""agents/improver.py — the LAB's scientific-method self-improvement loop.

Inspired by the "self-improving agent" idea but done with discipline:
  1. rank strategies, take the CHAMPION (top OOS Sharpe) as the baseline,
  2. DIAGNOSE which gate it fails (Sharpe<1 / DD>20 / ruin>1) -> form a hypothesis,
  3. run a series of experiments, each changing EXACTLY ONE variable (scientific method):
       vol_target_annual -> vol_lookback_days -> max_leverage,
     re-gating every variant through the SAME engine (the auditor),
  4. the best variant that beats the current baseline BECOMES the new baseline
     (baseline-then-improve), and the next experiment builds on it,
  5. log every experiment to IMPROVER_LEDGER.jsonl (the learning) and, if a config
     beats baseline, write it to STRATEGY_PROPOSALS.jsonl for CEO review.
Research only — it PROPOSES improved risk-envelopes; it never edits the live lab or trades.
A variant that finally PASSES the full gate is flagged loudly (first tradeable candidate).
"""
import copy
import datetime
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE / "gold_quant"))
from core import ibdata, engine
import lab

LEDGER = HERE / "IMPROVER_LEDGER.jsonl"
PROPOSALS = HERE / "STRATEGY_PROPOSALS.jsonl"

# one-variable experiment grids (baseline values live in lab.CFG["sizing"])
GRIDS = {
    "vol_target_annual": [0.03, 0.04, 0.06, 0.08, 0.10, 0.12, 0.16],
    "vol_lookback_days": [10, 15, 20, 30, 40, 60],
    "max_leverage":      [0.5, 0.75, 1.0, 1.5, 2.0],
}


def gate_status(r):
    m, mc = r["oos"], r["mc"]
    return {"sharpe_ok": m["sharpe"] >= 1.0, "dd_ok": m["max_dd_pct"] <= 20.0,
            "ruin_ok": mc["ruin_pct"] <= 1.0}


def score(r):
    """Higher is better: (#gates passed, then OOS Sharpe). Drives the search."""
    g = gate_status(r)
    return (sum(g.values()), r["oos"]["sharpe"])


def fails(r):
    g = gate_status(r)
    return [k.replace("_ok", "") for k, v in g.items() if not v]


def run(px, drv, mk, cfg):
    return engine.walk_forward(px, drv, mk, cfg)


def log(rec):
    rec["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec) + "\n")


def main():
    print("IMPROVER: fetching gold + ranking strategies ...", flush=True)
    gold_rows = ibdata.gold_daily(years="8", cid_offset=20)
    if not gold_rows:
        print("No data — is TWS running on the paper account?")
        return
    base_cfg = copy.deepcopy(lab.CFG)
    ranked = []
    for name, thesis, px, drv, mk in lab.build_strategies(gold_rows):
        r = run(px, drv, mk, base_cfg)
        ranked.append((name, px, drv, mk, r))
    ranked.sort(key=lambda x: x[4]["oos"]["sharpe"], reverse=True)
    name, px, drv, mk, base_r = ranked[0]

    base_score = score(base_r)
    print(f"\nCHAMPION: {name}  Sharpe={base_r['oos']['sharpe']} DD={base_r['oos']['max_dd_pct']} "
          f"ruin={base_r['mc']['ruin_pct']}  gates_failed={fails(base_r)}")
    hypo = (f"{name} clears {base_score[0]}/3 gates; fails {fails(base_r) or 'none'}. "
            "Hypothesis: shrinking the risk envelope (lower vol-target / leverage) cuts ruin & DD "
            "while keeping Sharpe — search ONE variable at a time.")
    print("HYPOTHESIS:", hypo)
    log({"event": "start", "champion": name, "baseline": base_r["oos"] | base_r["mc"],
         "gates_failed": fails(base_r), "hypothesis": hypo})

    cur_cfg = copy.deepcopy(base_cfg)
    cur_r = base_r
    cur_score = base_score

    for var, grid in GRIDS.items():
        baseval = cur_cfg["sizing"][var]
        print(f"\n— EXPERIMENT: vary {var} (baseline {baseval}), hold all else —")
        trials = []
        for val in grid:
            cfg = copy.deepcopy(cur_cfg)
            cfg["sizing"][var] = val
            r = run(px, drv, mk, cfg)
            sc = score(r)
            trials.append((val, sc, r))
            tag = "PASS-ALL" if sc[0] == 3 else f"{sc[0]}/3"
            print(f"    {var}={val:<6} -> Sharpe={r['oos']['sharpe']:>5} DD={r['oos']['max_dd_pct']:>5} "
                  f"ruin={r['mc']['ruin_pct']:>6} [{tag}]")
        trials.sort(key=lambda t: t[1], reverse=True)
        best_val, best_sc, best_r = trials[0]
        improved = best_sc > cur_score and best_val != baseval
        log({"event": "experiment", "variable": var, "baseline_value": baseval,
             "tried": [{"val": v, "gates": s[0], "sharpe": s[1]} for v, s, _ in trials],
             "winner": best_val, "winner_gates": best_sc[0], "winner_sharpe": best_sc[1],
             "adopted": bool(improved)})
        if improved:
            print(f"    -> ADOPT {var}={best_val} (was {baseval}): "
                  f"gates {cur_score[0]}->{best_sc[0]}, Sharpe {cur_score[1]}->{best_sc[1]}")
            cur_cfg["sizing"][var] = best_val
            cur_r, cur_score = best_r, best_sc
        else:
            print(f"    -> keep {var}={baseval} (no one-variable improvement)")

    print("\n================ IMPROVER RESULT ================")
    print(f"  champion         : {name}")
    print(f"  baseline gates   : {base_score[0]}/3  (Sharpe {base_r['oos']['sharpe']}, "
          f"ruin {base_r['mc']['ruin_pct']})")
    print(f"  improved gates   : {cur_score[0]}/3  (Sharpe {cur_r['oos']['sharpe']}, "
          f"ruin {cur_r['mc']['ruin_pct']})")
    print(f"  improved sizing  : {cur_cfg['sizing']}")
    passes = cur_score[0] == 3
    if cur_score > base_score:
        prop = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "strategy": name, "improved_sizing": cur_cfg["sizing"],
                "baseline_gates": base_score[0], "improved_gates": cur_score[0],
                "oos": cur_r["oos"], "mc": cur_r["mc"], "passes_full_gate": passes}
        with open(PROPOSALS, "a") as f:
            f.write(json.dumps(prop) + "\n")
        print(f"  -> PROPOSAL written for CEO review (improved {base_score[0]}->{cur_score[0]} gates)")
        if passes:
            print("  *** THIS CONFIG PASSES THE FULL GATE — first tradeable candidate. Still CEO + forward-test gated. ***")
    else:
        print("  -> no improvement beat the baseline this run (honest: the envelope search didn't help).")
    print("  Research only — proposes a risk-envelope; never edits the live lab or trades.")


if __name__ == "__main__":
    main()
