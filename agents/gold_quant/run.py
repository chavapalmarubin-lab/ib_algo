"""agents/gold_quant/run.py — the gold_quant AGENT (research/signal only, never trades).

Pulls IBKR spot-gold daily bars, aligns the bundled DFII10 real-yield driver point-in-time,
and runs the TH Quant walk-forward + Monte-Carlo gate over the Real-Yield Gold signal.
Prints the OOS verdict against the TH Quant validation gates. Places NO orders.

  python agents/gold_quant/run.py
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]            # ~/ib_algo
sys.path.insert(0, str(ROOT))    # for `core`
sys.path.insert(0, str(HERE))    # for `gold_signal`

from core import ibdata, engine
import gold_signal as S

# Mirrors TH Quant schemas/risk_config.json (the parts the engine needs).
CFG = {
    "sizing": {"vol_target_annual": 0.08, "vol_lookback_days": 20, "max_leverage": 1.0},
    "validation_gates": {"min_sharpe": 1.0, "max_backtest_dd_pct": 20.0,
                         "montecarlo_paths": 10000, "montecarlo_ruin_pct_max": 1.0},
    "drawdown_kill_switch": {"max_drawdown_pct": 12.0},
}


def main():
    print("gold_quant: fetching IBKR spot-gold daily bars ...", flush=True)
    gold_rows = ibdata.gold_daily(years="8", cid_offset=20)
    if not gold_rows:
        print("No gold bars returned — is TWS running + logged into paper?")
        return
    print(f"  {len(gold_rows)} bars  {gold_rows[0][0]} .. {gold_rows[-1][0]}")

    ry_dates, ry_vals = S.load_real_yield(HERE / "data" / "real_yield_10y.csv")
    px, drv = S.align(gold_rows, ry_dates, ry_vals)
    print(f"  aligned {len(px)} bars with DFII10 10y real yield "
          f"({ry_dates[0]} .. {ry_dates[-1]})", flush=True)
    if len(px) < 250:
        print("  too few aligned bars to judge.")
        return

    r = engine.walk_forward(px, drv, S.signal, CFG)
    g = CFG["validation_gates"]
    print("\n=== gold_quant — Real-Yield Gold (OOS walk-forward) ===")
    print(f"  tuned lookback: {r['lookback']}d (IS Sharpe {r['is_sharpe']})   OOS trades: {r['trades']}")
    print(f"  OOS Sharpe: {r['oos']['sharpe']}   max DD: {r['oos']['max_dd_pct']}%   "
          f"return: {r['oos']['total_return_pct']}%")
    print(f"  Monte-Carlo ruin: {r['mc']['ruin_pct']}%")
    print(f"  gates: Sharpe>={g['min_sharpe']}, DD<={g['max_backtest_dd_pct']}%, "
          f"ruin<={g['montecarlo_ruin_pct_max']}%")
    print(f"  >>> VERDICT: {r['verdict']} <<<")
    print("\n  Research/signal only — never trades. A FAIL is the discipline working,")
    print("  not a bug: TH Quant found real-yield gold is a mild (~0.4 Sharpe) edge that")
    print("  does not clear a Sharpe>=1.0 standalone gate. This agent reproduces that honestly.")


if __name__ == "__main__":
    main()
