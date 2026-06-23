"""core/portfolio.py — Track 3: portfolio construction over the universe.

Turns many single-instrument return streams into ONE diversified book and measures how
much diversification actually buys you. Pure numpy; judges, never trades.

  * align_returns: stack per-asset return series into a T x A matrix (aligned at the end).
  * correlation_matrix / covariance.
  * inverse_vol_weights: w_i proportional to 1/sigma_i (ignores correlation).
  * risk_parity_weights: long-only Equal-Risk-Contribution weights (each asset contributes
    the same share of portfolio variance) via the standard fixed-point iteration.
  * diversification_ratio: (w . sigma) / sigma_portfolio; 1.0 = no diversification, higher
    = the book's vol is much lower than the weighted-average asset vol.
  * combine: the portfolio return series for a given weight vector.
"""
import numpy as np


def align_returns(series_by_name):
    """series_by_name: {name: 1d array of per-bar returns}. Returns (names, R) where R is
    T x A, truncated to the shortest series and aligned at the most-recent end."""
    names = [n for n, s in series_by_name.items() if s is not None and len(s) > 0]
    if not names:
        return [], np.zeros((0, 0))
    T = min(len(series_by_name[n]) for n in names)
    R = np.column_stack([np.asarray(series_by_name[n], float)[-T:] for n in names])
    return names, R


def covariance(R):
    return np.cov(R, rowvar=False, ddof=0)


def correlation_matrix(R):
    C = covariance(R)
    d = np.sqrt(np.clip(np.diag(C), 1e-18, None))
    corr = C / np.outer(d, d)
    return np.clip(corr, -1.0, 1.0)


def inverse_vol_weights(R):
    vol = R.std(axis=0, ddof=0)
    inv = 1.0 / np.clip(vol, 1e-12, None)
    return inv / inv.sum()


def risk_parity_weights(R, iters=20000, tol=1e-11):
    """Long-only Equal Risk Contribution weights: each asset contributes the same share
    of portfolio variance. Damped multiplicative update on the risk-contribution shares
    (target 1/n), starting from inverse-vol. For uncorrelated assets this reduces to
    inverse-vol; correlation pulls weight off the crowded, mutually-correlated names."""
    C = covariance(R)
    n = C.shape[0]
    if n == 0:
        return np.zeros(0)
    if n == 1:
        return np.ones(1)
    # ridge for numerical stability if near-singular
    C = C + np.eye(n) * (1e-12 + 1e-10 * np.trace(C) / n)
    w = inverse_vol_weights(R)
    target = 1.0 / n
    for _ in range(iters):
        m = C @ w
        rc = w * m
        tot = rc.sum()
        if tot <= 0:
            break
        rc_share = rc / tot
        if np.max(np.abs(rc_share - target)) < tol:
            break
        # square-root-damped move toward equal risk contribution (stable)
        w = w * np.sqrt(target / np.clip(rc_share, 1e-18, None))
        w = np.clip(w, 0.0, None)
        s = w.sum()
        if s <= 0:
            break
        w /= s
    return w


def diversification_ratio(w, R):
    C = covariance(R)
    sigma = np.sqrt(np.clip(np.diag(C), 1e-18, None))
    port_vol = float(np.sqrt(max(1e-18, w @ C @ w)))
    return float((w @ sigma) / port_vol)


def risk_contributions(w, R):
    """Fraction of total portfolio variance contributed by each asset (sums to 1)."""
    C = covariance(R)
    m = C @ w
    rc = w * m
    tot = rc.sum()
    return rc / tot if tot > 0 else rc


def combine(R, w):
    """Portfolio per-bar return series for weight vector w."""
    return R @ w
