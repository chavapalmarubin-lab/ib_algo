"""core/stats.py — Track 2: anti-overfit statistics.

Separates real edge from backtest luck. Three tools, all pure-numpy (no scipy),
all judges (they never trade — maker != auditor):

  * probabilistic / deflated Sharpe ratio (Bailey & Lopez de Prado, 2014):
    adjusts an observed Sharpe for sample length, return skew & kurtosis, and the
    number of trials it took to find it -> probability the TRUE Sharpe beats a hurdle.
  * expected_max_sharpe: the Sharpe you'd expect from the BEST of N independent random
    trials (the multiple-testing hurdle the winner must clear to be believable).
  * purged_kfold_indices: K-fold cross-validation splits with a purge + embargo gap so
    train and test never leak across the boundary on a time series.

All Sharpe inputs/outputs here are PER-OBSERVATION (not annualized) unless noted.
"""
import math
import numpy as np

EULER_GAMMA = 0.5772156649015329


def norm_cdf(x):
    """Standard normal CDF via erf (no scipy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p):
    """Inverse standard normal CDF (Acklam's rational approximation)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)


def _moments(r):
    """Return (sr_per_obs, skew, kurtosis_raw) for a return series. Kurtosis is raw (normal=3)."""
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3:
        return 0.0, 0.0, 3.0
    mu = r.mean()
    sd = r.std(ddof=0)
    if sd < 1e-12:
        return 0.0, 0.0, 3.0
    z = (r - mu) / sd
    sr = mu / sd
    skew = float((z**3).mean())
    kurt = float((z**4).mean())
    return float(sr), skew, kurt


def probabilistic_sharpe_ratio(returns, sr_benchmark=0.0):
    """PSR: probability the true (per-obs) Sharpe exceeds sr_benchmark, given the sample.
    Accounts for sample length and non-normal (skew/fat-tailed) returns. Range 0..1."""
    r = np.asarray(returns, float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3:
        return float("nan")
    sr, skew, kurt = _moments(r)
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr))
    stat = (sr - sr_benchmark) * math.sqrt(n - 1) / denom
    return norm_cdf(stat)


def expected_max_sharpe(n_trials, sr_trials_std):
    """Multiple-testing hurdle: the expected MAX per-obs Sharpe across n_trials independent
    trials whose individual Sharpes have standard deviation sr_trials_std (under H0 mean 0)."""
    n = max(2, int(n_trials))
    v = float(sr_trials_std)
    if v <= 0:
        return 0.0
    g = EULER_GAMMA
    return v * ((1.0 - g) * norm_ppf(1.0 - 1.0 / n) +
                g * norm_ppf(1.0 - 1.0 / (n * math.e)))


def deflated_sharpe_ratio(returns, n_trials, sr_trials_std):
    """DSR: PSR where the benchmark is the multiple-testing-adjusted expected max Sharpe.
    Probability (0..1) that the strategy's edge survives both non-normality AND the fact
    that it was the best of n_trials. > ~0.95 = credible; near 0.5 or below = likely luck."""
    sr_star = expected_max_sharpe(n_trials, sr_trials_std)
    return probabilistic_sharpe_ratio(returns, sr_benchmark=sr_star), sr_star


def purged_kfold_indices(n, k=5, embargo_pct=0.01):
    """Yield (train_idx, test_idx) for K contiguous test folds over range(n), removing
    `purge` points adjacent to each test fold and an `embargo` band after it, so no train
    observation overlaps or immediately trails a test observation (Lopez de Prado, AFML)."""
    k = max(2, int(k))
    embargo = int(round(n * embargo_pct))
    folds = np.array_split(np.arange(n), k)
    out = []
    for f in folds:
        if len(f) == 0:
            continue
        t0, t1 = int(f[0]), int(f[-1])
        test = np.arange(t0, t1 + 1)
        lo = max(0, t0 - embargo)
        hi = min(n, t1 + 1 + embargo)
        mask = np.ones(n, dtype=bool)
        mask[lo:hi] = False
        train = np.arange(n)[mask]
        out.append((train, test))
    return out
