"""Apply a factor shock vector (+ optional periphery shocks) to a beta matrix and a portfolio to compute P&L."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from app.data.sample_portfolios import Portfolio
from app.factors.attribution import (
    conditional_shapley_attribution,
    conditional_shapley_attribution_explicit,
    conditional_shapley_attribution_grouped,
    naive_attribution,
)
from app.factors.universe import FACTORS

logger = logging.getLogger(__name__)


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
    factor_returns_history: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Expected portfolio P&L under factor + (optional) periphery shocks, plus attribution.

    Returns a JSON-safe dict matching `app.llm.schemas.PortfolioPnL`:

        {
            "total_pnl": float,
            "by_factor_naive": dict[str, float],
            "by_factor_conditional_shapley":           dict[str, float] | None,
            "by_factor_conditional_shapley_explicit":  dict[str, float] | None,
            "by_factor_conditional_shapley_grouped":   dict[str, float] | None,
            "by_ticker_factor": dict[str, float],
            "by_ticker_periphery": dict[str, float],
            "by_ticker_total": dict[str, float],
        }

    Linearity gives `sum(by_factor_naive) + sum(by_ticker_periphery) == total_pnl`.
    Full and grouped Shapley sum to the factor-driven P&L by the efficiency axiom.
    Explicit-only Shapley sums to a sub-game total ≤ factor-driven P&L by design.

    `factor_returns_history` (demeaned, dropna'd) enables all three Conditional
    Shapley variants. When omitted or when shap fails, each variant is None
    independently and the engine degrades to whichever variants succeeded.
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

    by_factor_naive = naive_attribution(betas, shocks, weights)

    by_factor_conditional_shapley: dict[str, float] | None = None
    by_factor_conditional_shapley_explicit: dict[str, float] | None = None
    by_factor_conditional_shapley_grouped: dict[str, float] | None = None
    if factor_returns_history is not None:
        try:
            by_factor_conditional_shapley = conditional_shapley_attribution(
                betas, shocks, weights, factor_returns_history
            )
        except Exception as exc:  # noqa: BLE001 — Shapley failure must not break a scenario
            logger.warning("Conditional Shapley unavailable: %s", exc)
        try:
            by_factor_conditional_shapley_explicit = conditional_shapley_attribution_explicit(
                betas, shocks, weights, factor_returns_history
            )
        except Exception as exc:  # noqa: BLE001 — explicit-only is best-effort
            logger.warning("Explicit-only Shapley unavailable: %s", exc)
        try:
            factor_group_map = {name: f.group for name, f in FACTORS.items()}
            by_factor_conditional_shapley_grouped = conditional_shapley_attribution_grouped(
                betas, shocks, weights, factor_returns_history, factor_group_map
            )
        except Exception as exc:  # noqa: BLE001 — grouped is best-effort
            logger.warning("Grouped Shapley unavailable: %s", exc)

    total_pnl = float(by_ticker_total.sum())

    tickers_in_portfolio = list(portfolio.tickers)
    return {
        "total_pnl": total_pnl,
        "by_factor_naive": by_factor_naive,
        "by_factor_conditional_shapley": by_factor_conditional_shapley,
        "by_factor_conditional_shapley_explicit": by_factor_conditional_shapley_explicit,
        "by_factor_conditional_shapley_grouped": by_factor_conditional_shapley_grouped,
        "by_ticker_factor": {t: float(by_ticker_factor[t]) for t in tickers_in_portfolio},
        "by_ticker_periphery": {t: float(by_ticker_periphery[t]) for t in tickers_in_portfolio},
        "by_ticker_total": {t: float(by_ticker_total[t]) for t in tickers_in_portfolio},
    }
