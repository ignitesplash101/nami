"""Rolling-window beta estimation via standardized (unit-variance) ridge OLS.

Factor columns are scaled to unit variance inside the solve and the coefficients
are rescaled back to raw units, so the ridge penalty shrinks every factor
direction homogeneously instead of penalizing low-variance equity factors far
harder than high-variance macro factors. Output betas are raw-units: applying
them to raw decimal shocks is dimensionally identical to the historical
estimator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import NamedTuple

import numpy as np
import pandas as pd

from app.data.market import compute_weekly_returns, fetch_weekly_prices
from app.data.sample_portfolios import Portfolio
from app.factors.universe import factor_name_by_ticker, factor_tickers

# Minimum non-NaN weekly observations (overlapping the complete-factor rows)
# required to estimate one ticker's betas. Below ~9 months of weekly data a
# 22-factor ridge fit is mostly prior, so we raise loudly instead of silently
# returning noise. 52 would reject names listed 10-12 months ago; the SHAP
# background's separate 52-row floor governs the factor matrix, not this.
MIN_REGRESSION_WEEKS = 40

# Estimator identity for `regression_spec` — bump when the regression MATH
# changes (e.g. raw-units ridge -> standardized ridge was v1 -> v2).
REGRESSION_ESTIMATOR_ID = "ridge-std-v2"


class InsufficientHistoryError(RuntimeError):
    """A ticker has too few overlapping non-NaN weekly observations for beta estimation."""


@dataclass(frozen=True)
class TickerRegressionStats:
    """Per-ticker fit quality for the standardized-ridge regression.

    `r2` is in-sample on the centered ridge fit, clipped to [0, 1] (0.0 when the
    ticker's centered variance is zero). `idio_vol_weekly` is the ddof=1 standard
    deviation of the weekly residuals, NOT annualized.

    Phase-21 additions (default None so pre-existing constructors/mocks and old
    payloads stay valid):
      - `r2_adj`: dof-honest R² using the ridge EFFECTIVE dof
        (`1 − (1−r2)(n−1)/(n−p_eff−1)`); can be negative (worse than the mean);
        None when `n − p_eff − 1 < 1`.
      - `p_eff`: ridge effective dof `Σ s/(s+α)` over the standardized Gram's
        eigenvalues — equals the live-factor count at α→0, shrinks as α grows.
      - `beta_se`: RAW-unit per-factor standard errors (`σ̂·√diag(A⁻¹GA⁻¹)/σ_f`,
        σ̂² on n−p_eff−1 dof). In-process only — deliberately NOT persisted in
        the cached RegressionQuality block.
    """

    r2: float
    n_obs: int
    idio_vol_weekly: float
    r2_adj: float | None = None
    p_eff: float | None = None
    beta_se: dict[str, float] | None = None


def regression_spec(
    *,
    lookback_weeks: int,
    alpha: float,
    min_obs: int = MIN_REGRESSION_WEEKS,
) -> str:
    """Cache-key component identifying the estimator AND its parameters.

    Folded into `scenario_cache_key` so any change to the regression math or its
    configuration (including RIDGE_ALPHA / BETA_LOOKBACK_WEEKS env overrides)
    self-invalidates cached results instead of serving stale P&L. PROMPT_VERSION
    remains the prompt/schema-semantics lever; this is the engine-math lever.
    """
    return f"{REGRESSION_ESTIMATOR_ID}|lookback={lookback_weeks}|alpha={alpha:g}|min_obs={min_obs}"


def fetch_factor_returns(
    start: date | datetime | str | None = None,
    end: date | datetime | str | None = None,
    lookback_weeks: int | None = None,
) -> pd.DataFrame:
    """Weekly returns for every factor in the universe, columns renamed to friendly names."""
    prices = fetch_weekly_prices(
        factor_tickers(),
        start=start,
        end=end,
        lookback_weeks=lookback_weeks,
    )
    returns = compute_weekly_returns(prices)
    return returns.rename(columns=factor_name_by_ticker())


def fetch_factor_returns_history(
    lookback_weeks: int = 156,
    end: date | datetime | str | None = None,
    *,
    min_complete_rows: int = 52,
) -> pd.DataFrame:
    """T × F demeaned weekly factor-return history for use as a SHAP background.

    Rows with ANY NaN are dropped — do NOT fillna(0). Zero-filling a missing ETF
    manufactures false zero-correlation that contaminates Conditional Shapley.
    The strict drop restricts the surviving sample to the post-XLC-launch window
    (mid-2018+) once every factor in `FACTORS` is present; older windows cannot
    carry the modern factor universe's correlation structure.
    """
    raw = fetch_factor_returns(end=end, lookback_weeks=lookback_weeks)
    return _demean_factor_history(raw, min_complete_rows=min_complete_rows)


def _demean_factor_history(
    raw: pd.DataFrame,
    *,
    min_complete_rows: int = 52,
) -> pd.DataFrame:
    complete = raw.dropna(how="any")
    if len(complete) < min_complete_rows:
        raise RuntimeError(
            f"Conditional Shapley background needs ≥{min_complete_rows} complete rows; "
            f"got {len(complete)} after dropna across {len(raw.columns)} factors. "
            "Try a more recent date range or a smaller factor universe."
        )
    return complete - complete.mean(axis=0)


def fetch_factor_returns_with_history(
    lookback_weeks: int = 156,
    end: date | datetime | str | None = None,
    *,
    min_complete_rows: int = 52,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Single yfinance round-trip → (raw weekly factor returns, demeaned history-or-None).

    Used by `run_scenario` to avoid two near-identical fetches (one for beta
    estimation, one for the Conditional Shapley background). The demeaned history
    is None when there aren't enough complete rows for SHAP — preserves the
    existing best-effort semantics in `portfolio_pnl`.
    """
    raw = fetch_factor_returns(end=end, lookback_weeks=lookback_weeks)
    try:
        history = _demean_factor_history(raw, min_complete_rows=min_complete_rows)
    except RuntimeError:
        history = None
    return raw, history


class _SolveResult(NamedTuple):
    betas: np.ndarray  # F × N, raw units
    r2: np.ndarray  # N
    r2_adj: np.ndarray  # N; NaN when n − p_eff − 1 < 1
    idio: np.ndarray  # N, weekly residual vol
    p_eff: float  # ridge effective dof (shared per solve — same X)
    beta_se: np.ndarray  # F × N, raw units; 0.0 on zero-variance columns


def _solve_standardized_ridge(
    X: np.ndarray,
    Y: np.ndarray,
    alpha: float,
) -> _SolveResult:
    """One centered + standardized ridge solve → betas + fit/uncertainty stats.

    Centering both X and Y is equivalent to an unpenalized intercept that is
    estimated and discarded. Columns are scaled to unit variance for the solve
    and the coefficients are rescaled back (`beta_raw = beta_std / sigma_f`) —
    this rescale is load-bearing: it keeps `betas @ raw_decimal_shock`
    dimensionally identical to an unstandardized regression. Zero-variance
    columns get an exact 0.0 beta (and 0.0 SE).

    Effective dof and SEs come from one eigendecomposition of the standardized
    Gram G = X_stdᵀX_std: `p_eff = Σ s/(s+α)` and
    `Var(β̂_std) = σ̂² · V diag(s/(s+α)²) Vᵀ` (the ridge sandwich A⁻¹GA⁻¹ with
    A = G + αI). σ̂² uses `n − p_eff − 1` dof (the −1 is the absorbed
    intercept), matching OLS-with-constant SEs exactly as α → 0.
    """
    X_centered = X - X.mean(axis=0, keepdims=True)
    Y_centered = Y - Y.mean(axis=0, keepdims=True)
    n_obs = X.shape[0]
    n_factors = X.shape[1]
    n_tickers = Y.shape[1]

    sigma = X_centered.std(axis=0, ddof=1)
    live = np.isfinite(sigma) & (sigma > 0.0)

    betas = np.zeros((n_factors, n_tickers))
    beta_se = np.zeros((n_factors, n_tickers))
    p_eff = 0.0
    sandwich_diag: np.ndarray | None = None
    if bool(live.any()):
        X_std = X_centered[:, live] / sigma[live]
        gram = X_std.T @ X_std
        A = gram + alpha * np.eye(int(live.sum()))
        b_std = np.linalg.solve(A, X_std.T @ Y_centered)
        betas[live, :] = b_std / sigma[live][:, None]

        eigenvalues, eigenvectors = np.linalg.eigh(gram)
        eigenvalues = np.clip(eigenvalues, 0.0, None)
        p_eff = float((eigenvalues / (eigenvalues + alpha)).sum())
        # diag(A⁻¹ G A⁻¹) = Σ_k V²_{jk} · s_k/(s_k+α)²
        sandwich_diag = (eigenvectors**2) @ (eigenvalues / (eigenvalues + alpha) ** 2)

    resid = Y_centered - X_centered @ betas
    ss_res = (resid**2).sum(axis=0)
    ss_tot = (Y_centered**2).sum(axis=0)
    # Ridge RSS is monotone in alpha between the OLS RSS and the TSS, so r2 is
    # mathematically in [0, 1]; the clip handles float noise only.
    r2 = np.where(ss_tot > 0.0, 1.0 - ss_res / np.where(ss_tot > 0.0, ss_tot, 1.0), 0.0)
    r2 = np.clip(r2, 0.0, 1.0)
    idio = resid.std(axis=0, ddof=1) if resid.shape[0] > 1 else np.zeros(n_tickers)

    resid_dof = n_obs - p_eff - 1.0
    if resid_dof >= 1.0:
        r2_adj = 1.0 - (1.0 - r2) * (n_obs - 1.0) / resid_dof
        if sandwich_diag is not None:
            sigma2_hat = ss_res / resid_dof  # per-ticker residual variance
            se_std = np.sqrt(np.outer(sandwich_diag, sigma2_hat))
            beta_se[live, :] = se_std / sigma[live][:, None]
    else:
        r2_adj = np.full(n_tickers, np.nan)

    return _SolveResult(betas, r2, r2_adj, idio, p_eff, beta_se)


def estimate_betas_and_stats(
    ticker_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
    alpha: float = 0.1,
    *,
    min_obs: int = MIN_REGRESSION_WEEKS,
) -> tuple[pd.DataFrame, dict[str, TickerRegressionStats]]:
    """Standardized ridge OLS betas with per-ticker NaN masks and fit stats.

    Returns `(betas, stats)`: a (tickers × factors) DataFrame of raw-unit betas
    plus per-ticker `TickerRegressionStats`. Indices are aligned to the
    intersection of the two inputs; rows where any FACTOR is NaN are dropped
    globally, then each ticker is regressed on its own non-NaN rows (tickers are
    grouped by identical mask pattern, one vectorized solve per group) so one
    short-history holding no longer truncates the estimation window for the
    whole book. Each ticker needs at least `min_obs` surviving rows or
    `InsufficientHistoryError` is raised naming every offender.
    """
    if alpha < 0:
        raise ValueError(f"alpha must be non-negative; got {alpha}")

    common_idx = factor_returns.index.intersection(ticker_returns.index)
    if len(common_idx) == 0:
        raise RuntimeError("No overlapping dates between factor_returns and ticker_returns")

    F = factor_returns.loc[common_idx]
    Y = ticker_returns.loc[common_idx]
    factor_valid = ~F.isna().any(axis=1)
    F = F[factor_valid]
    Y = Y[factor_valid]
    if F.empty:
        raise RuntimeError("All overlapping rows contained NaN factors; nothing to regress")

    X_all = F.to_numpy(dtype=float)
    Y_all = Y.to_numpy(dtype=float)
    n_factors = X_all.shape[1]
    n_tickers = Y_all.shape[1]

    valid_mask = ~np.isnan(Y_all)
    n_obs = valid_mask.sum(axis=0)
    too_short = [
        f"{ticker} (n={int(n)})" for ticker, n in zip(Y.columns, n_obs, strict=True) if n < min_obs
    ]
    if too_short:
        # n=0 is almost never a genuinely short listing — it means the market
        # data fetch returned no usable prices for the ticker (transient
        # yfinance failure). Distinguish it so users retry instead of dropping
        # the holding. The market layer no longer caches such batches.
        message = (
            f"Insufficient weekly history for beta estimation: {', '.join(too_short)}; "
            f"minimum {min_obs} non-NaN weeks overlapping the factor matrix required"
        )
        if any(int(n) == 0 for n in n_obs if n < min_obs):
            message += (
                ". n=0 usually means the market-data fetch returned no prices for the "
                "ticker (a transient provider failure) — retry the run"
            )
        raise InsufficientHistoryError(message)

    betas = np.zeros((n_factors, n_tickers))
    r2_all = np.zeros(n_tickers)
    r2_adj_all = np.full(n_tickers, np.nan)
    idio_all = np.zeros(n_tickers)
    p_eff_all = np.zeros(n_tickers)
    beta_se_all = np.zeros((n_factors, n_tickers))

    # Group tickers by identical NaN-mask pattern; the all-complete common case
    # collapses to a single vectorized solve identical to a joint regression.
    pattern_groups: dict[bytes, list[int]] = {}
    for j in range(n_tickers):
        pattern_groups.setdefault(valid_mask[:, j].tobytes(), []).append(j)

    for cols in pattern_groups.values():
        rows = valid_mask[:, cols[0]]
        solved = _solve_standardized_ridge(X_all[rows], Y_all[np.ix_(rows, cols)], alpha)
        betas[:, cols] = solved.betas
        r2_all[cols] = solved.r2
        r2_adj_all[cols] = solved.r2_adj
        idio_all[cols] = solved.idio
        p_eff_all[cols] = solved.p_eff
        beta_se_all[:, cols] = solved.beta_se

    factor_names = [str(c) for c in F.columns]
    stats = {
        str(ticker): TickerRegressionStats(
            r2=float(r2_all[j]),
            n_obs=int(n_obs[j]),
            idio_vol_weekly=float(idio_all[j]),
            r2_adj=(None if np.isnan(r2_adj_all[j]) else float(r2_adj_all[j])),
            p_eff=float(p_eff_all[j]),
            beta_se={name: float(beta_se_all[i, j]) for i, name in enumerate(factor_names)},
        )
        for j, ticker in enumerate(Y.columns)
    }
    return pd.DataFrame(betas.T, index=Y.columns, columns=F.columns), stats


def estimate_betas(
    ticker_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
    alpha: float = 0.1,
    *,
    min_obs: int = MIN_REGRESSION_WEEKS,
) -> pd.DataFrame:
    """Thin wrapper over `estimate_betas_and_stats` returning the betas only."""
    return estimate_betas_and_stats(ticker_returns, factor_returns, alpha=alpha, min_obs=min_obs)[0]


def estimate_betas_for_portfolio(
    portfolio: Portfolio,
    lookback_weeks: int = 156,
    alpha: float = 0.1,
    end: date | datetime | str | None = None,
    *,
    factor_returns: pd.DataFrame | None = None,
    ticker_returns: pd.DataFrame | None = None,
    min_obs: int = MIN_REGRESSION_WEEKS,
) -> tuple[pd.DataFrame, dict[str, TickerRegressionStats]]:
    """Convenience wrapper: fetch portfolio + factor returns and run the estimator.

    Returns `(betas, stats)` — see `estimate_betas_and_stats`. Either of
    `factor_returns` and `ticker_returns` may be supplied pre-fetched (caller has
    already paid for them, e.g. when running the two yfinance calls in parallel)
    to avoid a duplicate fetch.

    Validates that every portfolio holding has a beta row. yfinance silently drops
    tickers it can't fetch, and a missing ticker downstream would produce silently
    wrong P&L — so we raise loudly here with the missing set.
    """
    if ticker_returns is None:
        ticker_prices = fetch_weekly_prices(
            portfolio.tickers,
            end=end,
            lookback_weeks=lookback_weeks,
        )
        ticker_returns = compute_weekly_returns(ticker_prices)
    if factor_returns is None:
        factor_returns = fetch_factor_returns(end=end, lookback_weeks=lookback_weeks)

    betas, stats = estimate_betas_and_stats(
        ticker_returns, factor_returns, alpha=alpha, min_obs=min_obs
    )

    missing = set(portfolio.tickers) - set(betas.index)
    if missing:
        raise RuntimeError(
            f"yfinance returned no data for these portfolio tickers: {sorted(missing)}"
        )

    return betas, stats
