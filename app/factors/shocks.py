"""Apply a factor shock vector (+ optional periphery shocks) to a beta matrix and a portfolio to compute P&L."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import pandas as pd

from app.data.sample_portfolios import Portfolio
from app.factors.attribution import (
    conditional_shapley_attribution,
    conditional_shapley_attribution_explicit,
    grouped_attribution_from_full,
    naive_attribution,
)
from app.factors.regression import TickerRegressionStats
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


def analog_replay_pnl(
    portfolio: Portfolio,
    betas: pd.DataFrame,
    event_factor_returns: Mapping[str, float | None],
) -> tuple[float, int]:
    """Factor-only portfolio P&L if a historical event's realized factor moves replayed.

    Pushes an analog event's TOTAL window factor returns through the book's betas:
    `Σ_t w_t · Σ_f β_{t,f} · r_f`. None/NaN returns (an ETF that predates the event
    window) contribute exactly 0 and are excluded from the coverage count; keys not
    in `betas.columns` are ignored (vintage-subset betas in the replay harness).
    No periphery, no idiosyncratic term — replay is deliberately factor-only.

    Returns `(replay_pnl, n_factors_covered)`.
    """
    shocks = {
        factor: float(value)
        for factor, value in event_factor_returns.items()
        if factor in betas.columns and pd.notna(value)
    }
    weights = pd.Series(portfolio.holdings, name="weight").reindex(betas.index).fillna(0.0)
    per_ticker = apply_shocks(betas, shocks)
    return float((weights * per_ticker).sum()), len(shocks)


def portfolio_idio_band(
    stats: Mapping[str, TickerRegressionStats],
    holdings: Mapping[str, float],
    horizon_weeks: float,
) -> tuple[float, float]:
    """(weekly portfolio idio vol, ±1σ episode band) from per-name residual vols.

    `Var_weekly = Σ_i (w_i · σ_i,idio)²` under cross-name independence; the
    episode band scales by `√horizon_weeks` (independence across weeks). Both
    assumptions UNDERSTATE true dispersion (residual co-movement within sectors,
    autocorrelation under stress), so the band is a floor on idiosyncratic
    dispersion around the factor-driven point estimate — dispersion, not a
    confidence interval on the scenario. Names without a stats entry (the CASH
    sleeve — no regression runs for it) contribute zero.
    """
    variance = 0.0
    for ticker, weight in holdings.items():
        ticker_stats = stats.get(ticker)
        if ticker_stats is None:
            continue
        variance += (weight * ticker_stats.idio_vol_weekly) ** 2
    weekly = math.sqrt(variance)
    return weekly, weekly * math.sqrt(max(horizon_weeks, 0.0))


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
    Full, grouped, and explicit-only Shapley sum to the factor-driven P&L under
    nami's demeaned-background contract. Explicit-only's distinguishing property
    is that unshocked factors stay at exactly zero.

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
        factor_group_map = {name: f.group for name, f in FACTORS.items()}
        # Full and explicit are the only two explainer fits. Grouped attribution
        # is a deterministic redistribution of the full result, so fitting the
        # same full game a second time only adds latency. Both fits remain
        # best-effort and run concurrently because the numerical work releases
        # the GIL.
        with ThreadPoolExecutor(max_workers=2) as pool:
            full_future = pool.submit(
                conditional_shapley_attribution, betas, shocks, weights, factor_returns_history
            )
            explicit_future = pool.submit(
                conditional_shapley_attribution_explicit,
                betas,
                shocks,
                weights,
                factor_returns_history,
            )
            try:
                by_factor_conditional_shapley = full_future.result()
            except Exception as exc:  # noqa: BLE001 — Shapley failure must not break a scenario
                logger.warning("Conditional Shapley unavailable: %s", exc)
            if by_factor_conditional_shapley is not None:
                try:
                    by_factor_conditional_shapley_grouped = grouped_attribution_from_full(
                        by_factor_conditional_shapley,
                        betas,
                        shocks,
                        weights,
                        factor_group_map,
                    )
                except Exception as exc:  # noqa: BLE001 — grouped is best-effort
                    logger.warning("Grouped Shapley unavailable: %s", exc)
            try:
                by_factor_conditional_shapley_explicit = explicit_future.result()
            except Exception as exc:  # noqa: BLE001 — explicit-only is best-effort
                logger.warning("Explicit-only Shapley unavailable: %s", exc)

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
