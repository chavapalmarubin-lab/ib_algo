"""agents/gold_quant/gold_signal.py — the GOLD strategy SIGNAL (the maker).

Ported faithfully from TH Quant's "Real-Yield Gold" thesis:
  Hold gold LONG while the 10-year real yield is trending DOWN, else FLAT.
Economic rationale: real yields are the opportunity cost of holding non-yielding gold;
when real yields fall, gold tends to rise. One free parameter: the trend lookback (tuned
in-sample, evaluated out-of-sample by the engine).

(Named gold_signal — NOT 'signal' — to avoid shadowing Python's stdlib signal module.)
"""
import bisect
import csv
import numpy as np


def signal(ry, lookback):
    """Gate 3 (point-in-time): signal at t uses only data up to t.
    Long (1.0) while real-yield trend is down (ry[t] < ry[t-lookback]), else flat (0.0)."""
    ry = np.asarray(ry, float)
    sig = np.zeros(len(ry))
    for t in range(lookback, len(ry)):
        sig[t] = 1.0 if ry[t] < ry[t - lookback] else 0.0
    return sig


def load_real_yield(path):
    """Read the bundled DFII10 10y real-yield CSV -> (dates, values), chronologically sorted."""
    dates, vals = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            dates.append(row["observation_date"][:10])
            vals.append(float(row["real_yield_10y"]))
    pairs = sorted(zip(dates, vals))
    return [d for d, _ in pairs], [v for _, v in pairs]


def align(gold_rows, ry_dates, ry_vals):
    """Point-in-time align (Gate 3, no look-ahead): for each gold (date, close) take the
    MOST RECENT real-yield value dated ON OR BEFORE that date (forward-fill via bisect)."""
    gold, ry = [], []
    for gd, gv in gold_rows:
        i = bisect.bisect_right(ry_dates, gd) - 1
        if i < 0:
            continue   # gold bar predates any real-yield obs
        gold.append(gv)
        ry.append(ry_vals[i])
    return np.asarray(gold, float), np.asarray(ry, float)
