"""Apply a factor shock vector (+ optional periphery shocks) to a beta matrix and a portfolio to compute P&L."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.data.sample_portfolios import Portfolio


def apply_shocks(betas: pd.DataFrame, shocks: dict[str, float]) -> pd.Series:
    """Per-ticker expected return given a factor shock vector.

    `shocks` keys must be a subset of `betas.columns`. Missing factors default to 0
    (no-shock semantic). Unknown keys raise loudly to catch LLM typos / stale factor
    names that would otherwise silently become zero-risk no-ops.
    """
    unknown = set(shocks) - set(betas.columns)
    if unknown:
        raise ValueError(
            f"Unknown factors in shock dict: {sorted(unknown)}. "
            f"Valid factors: {list(betas.columns)}"
        )

    shock_vec = np.array([shocks.get(col, 0.0) for col in betas.columns])
    return pd.Series(betas.to_numpy() @ shock_vec, index=betas.index, name="expected_return")


def portfolio_pnl(
    portfolio: Portfolio,
    betas: pd.DataFrame,
    shocks: dict[str, float],
    periphery_shocks: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Expected portfolio P&L under factor + (optional) periphery shocks, plus attribution.

    Returns a JSON-safe dict matching `app.llm.schemas.PortfolioPnL`:

        {
            "total_pnl": float,
            "by_factor": dict[str, float],          # per-factor portfolio attribution
            "by_ticker_factor": dict[str, float],   # per-ticker factor-driven contribution
            "by_ticker_periphery": dict[str, float],# per-ticker periphery contribution
            "by_ticker_total": dict[str, float],    # factor + periphery, per ticker
        }

    Linearity gives `sum(by_factor) + sum(by_ticker_periphery) == total_pnl`.
    """
    missing = set(portfolio.tickers) - set(betas.index)
    if missing:
        raise RuntimeError(
            f"Beta matrix is missing rows for these portfolio tickers: {sorted(missing)}"
        )

    periphery_shocks = periphery_shocks or {}
    unknown_periphery = set(periphery_shocks) - set(portfolio.holdings)
    if unknown_periphery:
        raise ValueError(
            f"Periphery shocks for tickers not in portfolio: {sorted(unknown_periphery)}"
        )

    weights = pd.Series(portfolio.holdings, name="weight").reindex(betas.index).fillna(0.0)

    factor_returns_per_ticker = apply_shocks(betas, shocks)
    periphery_per_ticker = pd.Series(
        {t: periphery_shocks.get(t, 0.0) for t in betas.index},
        name="periphery",
    )

    by_ticker_factor = (weights * factor_returns_per_ticker).rename("by_ticker_factor")
    by_ticker_periphery = (weights * periphery_per_ticker).rename("by_ticker_periphery")
    by_ticker_total = (by_ticker_factor + by_ticker_periphery).rename("by_ticker_total")

    weighted_betas = betas.T @ weights
    shock_vec = pd.Series({col: shocks.get(col, 0.0) for col in betas.columns})
    by_factor = weighted_betas * shock_vec

    total_pnl = float(by_ticker_total.sum())

    tickers_in_portfolio = list(portfolio.tickers)
    return {
        "total_pnl": total_pnl,
        "by_factor": {f: float(v) for f, v in by_factor.items()},
        "by_ticker_factor": {t: float(by_ticker_factor[t]) for t in tickers_in_portfolio},
        "by_ticker_periphery": {t: float(by_ticker_periphery[t]) for t in tickers_in_portfolio},
        "by_ticker_total": {t: float(by_ticker_total[t]) for t in tickers_in_portfolio},
    }
