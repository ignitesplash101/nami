"""Rolling-window beta estimation via mean-centered ridge OLS."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

from app.data.market import compute_weekly_returns, fetch_weekly_prices
from app.data.sample_portfolios import Portfolio
from app.factors.universe import factor_name_by_ticker, factor_tickers


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
    complete = raw.dropna(how="any")
    if len(complete) < min_complete_rows:
        raise RuntimeError(
            f"Conditional Shapley background needs ≥{min_complete_rows} complete rows; "
            f"got {len(complete)} after dropna across {len(raw.columns)} factors. "
            "Try a more recent date range or a smaller factor universe."
        )
    return complete - complete.mean(axis=0)


def estimate_betas(
    ticker_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
    alpha: float = 0.1,
) -> pd.DataFrame:
    """Mean-centered ridge OLS beta estimation.

    Returns a (tickers × factors) DataFrame. Indices are aligned to the intersection of
    the two inputs and any rows with NaN are dropped before the solve. Centering both X
    and Y removes the through-origin bias that would otherwise creep in whenever
    historical returns have nonzero means.
    """
    if alpha < 0:
        raise ValueError(f"alpha must be non-negative; got {alpha}")

    common_idx = factor_returns.index.intersection(ticker_returns.index)
    if len(common_idx) == 0:
        raise RuntimeError("No overlapping dates between factor_returns and ticker_returns")

    F = factor_returns.loc[common_idx]
    Y = ticker_returns.loc[common_idx]
    valid = ~(F.isna().any(axis=1) | Y.isna().any(axis=1))
    F = F[valid]
    Y = Y[valid]
    if F.empty:
        raise RuntimeError("All overlapping rows contained NaN; nothing to regress")

    X = F.to_numpy()
    Yn = Y.to_numpy()

    X_centered = X - X.mean(axis=0, keepdims=True)
    Y_centered = Yn - Yn.mean(axis=0, keepdims=True)

    n_factors = X_centered.shape[1]
    A = X_centered.T @ X_centered + alpha * np.eye(n_factors)
    B = X_centered.T @ Y_centered
    betas = np.linalg.solve(A, B)  # F × N

    return pd.DataFrame(betas.T, index=Y.columns, columns=F.columns)


def estimate_betas_for_portfolio(
    portfolio: Portfolio,
    lookback_weeks: int = 156,
    alpha: float = 0.1,
    end: date | datetime | str | None = None,
) -> pd.DataFrame:
    """Convenience wrapper: fetch portfolio + factor returns and run estimate_betas.

    Validates that every portfolio holding has a beta row. yfinance silently drops
    tickers it can't fetch, and a missing ticker downstream would produce silently
    wrong P&L — so we raise loudly here with the missing set.
    """
    ticker_prices = fetch_weekly_prices(
        portfolio.tickers,
        end=end,
        lookback_weeks=lookback_weeks,
    )
    ticker_returns = compute_weekly_returns(ticker_prices)
    factor_returns = fetch_factor_returns(end=end, lookback_weeks=lookback_weeks)

    betas = estimate_betas(ticker_returns, factor_returns, alpha=alpha)

    missing = set(portfolio.tickers) - set(betas.index)
    if missing:
        raise RuntimeError(
            f"yfinance returned no data for these portfolio tickers: {sorted(missing)}"
        )

    return betas
