"""Coherent scenario completion: shrunk covariance, Gaussian conditioning, basis maps.

The linear algebra behind the Phase-42 completion study. A scenario that names
a few factor moves (the *anchors*) is completed into a full factor vector by
the conditional expectation of the remaining factors given the anchors,

    s_u = Σ_ua Σ_aa⁻¹ a,

with the residual uncertainty Σ_uu − Σ_ua Σ_aa⁻¹ Σ_au. Both blocks of Σ scale
by the same horizon h under i.i.d. weekly returns, so the conditional MEAN is
horizon-free and only the conditional covariance needs `h`.

Weekly factor returns are demeaned before Σ is estimated, so the completion
carries no drift term: over a stress episode the weekly mean (h·μ) is small
next to the anchored moves and is deliberately ignored.

Pure numpy/pandas; no network, no LLM.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd


def ledoit_wolf_shrinkage(X: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit–Wolf (2004) linear shrinkage of a centered sample toward μ·I.

    `X` is n×p and already centered. Returns `(Σ, δ)` with
    `Σ = δ·μI + (1−δ)·S`, `S = XᵀX/n`, `μ = tr(S)/p`, and `δ = min(b̄², d²)/d²`
    where `d² = ‖S − μI‖²_F/p` and `b̄² = Σ_k ‖x_k x_kᵀ − S‖²_F/(n²p)`. The
    per-observation sum uses the identity `Σ_k ‖x_k x_kᵀ − S‖²_F =
    Σ_k ‖x_k‖⁴ − n‖S‖²_F`, so no p×p matrix is built per observation.
    """
    n, p = X.shape
    if n < 2 or p < 1:
        raise ValueError(f"Ledoit–Wolf needs n ≥ 2 observations and p ≥ 1 columns; got {X.shape}")
    sample = X.T @ X / n
    mu = float(np.trace(sample)) / p
    target = mu * np.eye(p)
    d2 = float(np.sum((sample - target) ** 2)) / p
    row_norms_sq = np.sum(X**2, axis=1)
    b2_bar = (float(np.sum(row_norms_sq**2)) - n * float(np.sum(sample**2))) / (n**2 * p)
    b2 = min(b2_bar, d2)
    delta = 0.0 if d2 == 0.0 else b2 / d2
    return delta * target + (1.0 - delta) * sample, delta


def shrunk_covariance(returns: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Weekly covariance with Ledoit–Wolf shrinkage applied to the CORRELATIONS.

    Factor scales differ by orders of magnitude (a short-Treasury ETF vs the VIX
    level), so shrinking the raw covariance toward μ·I would drag every variance
    toward the average and distort the low-vol factors. Instead the complete
    rows are standardized, the correlation matrix is shrunk toward the identity
    (target μ = 1), and the result is rescaled by the sample standard
    deviations. Returns `(covariance, δ)`.
    """
    complete = returns.dropna(how="any")
    X = complete.to_numpy(dtype=float)
    X = X - X.mean(axis=0, keepdims=True)
    sd = X.std(axis=0, ddof=0)
    flat = [str(c) for c, s in zip(complete.columns, sd, strict=True) if not s > 0.0]
    if flat:
        raise ValueError(f"Zero-variance factor column(s) cannot be standardized: {flat}")
    corr, delta = ledoit_wolf_shrinkage(X / sd)
    cov = corr * np.outer(sd, sd)
    return pd.DataFrame(cov, index=complete.columns, columns=complete.columns), delta


@dataclass(frozen=True)
class Completion:
    """A scenario completed from its anchors.

    `shocks` covers every factor in the covariance index (anchors verbatim, the
    rest implied); `implied` holds only the unanchored entries; and
    `conditional_cov` is the PER-WEEK residual covariance of the unanchored
    factors given the anchors. Scale it by the horizon in weeks for an episode.
    """

    shocks: pd.Series
    implied: pd.Series
    conditional_cov: pd.DataFrame


def complete_shocks(cov: pd.DataFrame, anchors: Mapping[str, float]) -> Completion:
    """Conditional expectation of the unanchored factors given the anchored moves.

    `s_u = Σ_ua Σ_aa⁻¹ a`. With no anchors every implied move is 0 and the
    conditional covariance is Σ itself; with every factor anchored nothing is
    implied. Unknown anchor names raise rather than being silently dropped.
    """
    names = [str(c) for c in cov.index]
    unknown = sorted(set(anchors) - set(names))
    if unknown:
        raise ValueError(f"Anchors not in the covariance universe: {unknown}")
    anchored = [n for n in names if n in anchors]
    free = [n for n in names if n not in anchors]
    a_vec = np.array([float(anchors[n]) for n in anchored])

    sigma = cov.loc[names, names].to_numpy(dtype=float)
    idx = {n: i for i, n in enumerate(names)}
    ia = [idx[n] for n in anchored]
    iu = [idx[n] for n in free]
    s_uu = sigma[np.ix_(iu, iu)]
    if anchored and free:
        s_aa = sigma[np.ix_(ia, ia)]
        s_au = sigma[np.ix_(ia, iu)]
        coef = np.linalg.solve(s_aa, s_au).T  # (u × a) = Σ_ua Σ_aa⁻¹ (Σ_aa symmetric)
        implied_vals = coef @ a_vec
        cond = s_uu - coef @ s_au
    else:
        implied_vals = np.zeros(len(free))
        cond = s_uu

    implied = pd.Series(implied_vals, index=free, dtype=float)
    shocks = pd.concat([pd.Series(a_vec, index=anchored, dtype=float), implied]).reindex(names)
    return Completion(
        shocks=shocks,
        implied=implied,
        conditional_cov=pd.DataFrame(cond, index=free, columns=free),
    )


def mahalanobis_distance(
    cov: pd.DataFrame, moves: Mapping[str, float], horizon_weeks: float
) -> float:
    """Statistical distance of an episode move: √(aᵀ (h·Σ_aa)⁻¹ a).

    `cov` is the weekly covariance; `h` scales it to the episode. Larger means
    more extreme than the weekly history would suggest at that horizon.
    """
    if horizon_weeks <= 0.0:
        raise ValueError(f"horizon_weeks must be positive; got {horizon_weeks}")
    names = [n for n in (str(c) for c in cov.index) if n in moves]
    if not names:
        return 0.0
    a = np.array([float(moves[n]) for n in names])
    s_aa = cov.loc[names, names].to_numpy(dtype=float) * horizon_weeks
    return math.sqrt(max(float(a @ np.linalg.solve(s_aa, a)), 0.0))


@dataclass(frozen=True)
class RelativeBasis:
    """Market plus market-relative factors: `r_k^rel = r_k − b_k · r_market`.

    The column span is unchanged (an invertible linear map), so OLS fits and
    P&L are invariant; what changes is that each relativized factor now reads
    as "this factor's move beyond its usual co-move with the market", and a
    relative move of zero means "moves with the market", not "stays flat".
    """

    market: str
    loadings: dict[str, float]

    def returns(self, factor_returns: pd.DataFrame) -> pd.DataFrame:
        """Transform a weekly factor-return frame into the relative basis."""
        out = factor_returns.copy()
        for name, b in self.loadings.items():
            if name in out.columns:
                out[name] = factor_returns[name] - b * factor_returns[self.market]
        return out

    def to_relative(self, moves: Mapping[str, float]) -> dict[str, float]:
        """Map absolute factor moves into relative-basis moves.

        Any relativized factor requires the market move to be present: a
        relative move is undefined without it, and assuming 0 would silently
        re-introduce the zero-hole this basis exists to remove.
        """
        needs_market = any(name in self.loadings for name in moves)
        if needs_market and self.market not in moves:
            raise ValueError(
                f"Relative-basis mapping needs the market move ({self.market}) "
                "alongside any relativized factor"
            )
        m = float(moves.get(self.market, 0.0))
        return {
            name: (float(v) - self.loadings[name] * m if name in self.loadings else float(v))
            for name, v in moves.items()
        }

    def to_absolute(self, moves: Mapping[str, float]) -> dict[str, float]:
        """Inverse of `to_relative` (same market-presence requirement)."""
        needs_market = any(name in self.loadings for name in moves)
        if needs_market and self.market not in moves:
            raise ValueError(
                f"Absolute-basis mapping needs the market move ({self.market}) "
                "alongside any relativized factor"
            )
        m = float(moves.get(self.market, 0.0))
        return {
            name: (float(v) + self.loadings[name] * m if name in self.loadings else float(v))
            for name, v in moves.items()
        }


def fit_relative_basis(
    factor_returns: pd.DataFrame, market: str, relative: Sequence[str]
) -> RelativeBasis:
    """Estimate each `b_k = cov(r_k, r_m)/var(r_m)` on the rows where both exist."""
    if market not in factor_returns.columns:
        raise ValueError(f"Market factor {market!r} is not in the factor-return frame")
    loadings: dict[str, float] = {}
    for name in relative:
        if name == market or name not in factor_returns.columns:
            continue
        pair = factor_returns[[market, name]].dropna(how="any")
        var_m = float(pair[market].var(ddof=1)) if len(pair) > 1 else 0.0
        if not var_m > 0.0:
            raise ValueError(f"Cannot fit a market loading for {name}: no market variance")
        loadings[name] = float(pair[name].cov(pair[market], ddof=1)) / var_m
    return RelativeBasis(market=market, loadings=loadings)
