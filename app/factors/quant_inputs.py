"""Assemble vintage-bounded public inputs for the optional Quant V2 engine."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.data.fx import convert_daily_returns_to_usd
from app.data.market import fetch_daily_prices
from app.data.quant_sources import (
    PublicDataClient,
    QuantPublicInputs,
    SourceVersion,
    load_quant_public_inputs,
)
from app.data.sample_portfolios import CASH_TICKER, Portfolio, ticker_metadata
from app.factors.quant_exposure import ExposureEstimate, estimate_portfolio_exposures

REGION_PREFIX = {
    "north_america": "NA",
    "developed_ex_us": "DMX",
    "japan": "JP",
    "generic": "DEV",
}
REGIONAL_FACTOR_COLUMNS = ("MKT_RF", "SMB", "HML", "RMW", "CMA", "MOM")
QUANT_STATE_PRICE_START = date(2007, 4, 1)
QUANT_STOCK_HISTORY_YEARS = 5
_BUILTIN_BENCHMARK_METADATA: dict[str, dict[str, str]] = {
    "URTH": {"country": "Global developed", "sector": ""},
    "QQQ": {"country": "United States", "sector": ""},
    "SPLV": {"country": "United States", "sector": ""},
    "EWJ": {"country": "Japan", "sector": ""},
}


@dataclass(frozen=True)
class QuantPreparedInputs:
    factor_returns: pd.DataFrame
    state_levels: pd.DataFrame
    betas: pd.DataFrame
    exposures: dict[str, ExposureEstimate]
    sources: dict[str, SourceVersion]
    benchmark_beta: pd.Series | None = None
    benchmark_exposure: ExposureEstimate | None = None


def _factor_return_union(
    public: QuantPublicInputs,
    estimates: dict[str, ExposureEstimate],
    required_columns: list[str],
) -> pd.DataFrame:
    regions = sorted({estimate.region for estimate in estimates.values()})
    frames: list[pd.DataFrame] = []
    for region in regions:
        if region not in public.regional_factors:
            raise ValueError(f"regional factor history is unavailable for {region!r}")
        prefix = REGION_PREFIX[region]
        frame = (
            public.regional_factors[region]
            .loc[:, list(REGIONAL_FACTOR_COLUMNS)]
            .rename(columns={name: f"{prefix}:{name}" for name in REGIONAL_FACTOR_COLUMNS})
        )
        frames.append(frame)

    industries = sorted(
        {
            estimate.industry_factor
            for estimate in estimates.values()
            if estimate.industry_factor is not None
        }
    )
    if industries:
        north_america = public.regional_factors["north_america"]
        industry_frame = pd.DataFrame(index=public.us_industries.index)
        for industry in industries:
            assert industry is not None
            total_market = (north_america["MKT_RF"] + north_america["RF"]).reindex(
                industry_frame.index
            )
            industry_frame[f"US_IND:{industry}"] = public.us_industries[industry] - total_market
        frames.append(industry_frame)

    if not frames:
        raise ValueError("no regional factor histories were selected")
    combined = pd.concat(frames, axis=1, join="inner").sort_index().dropna(how="any")
    missing = set(required_columns) - set(combined.columns)
    if missing:
        raise ValueError(f"factor history is missing estimated columns: {sorted(missing)}")
    result = combined.loc[:, required_columns]
    if result.empty:
        raise ValueError("selected regional factor histories have no complete overlap")
    return result


def prepare_quant_inputs(
    portfolio: Portfolio,
    *,
    as_of: object,
    benchmark_ticker: str | None = None,
    public_client: PublicDataClient | None = None,
) -> QuantPreparedInputs:
    """Fetch and align public factors, market states, prices, and exposure estimates."""
    cutoff = pd.Timestamp(as_of).tz_localize(None)
    yf_end = (cutoff + pd.Timedelta(days=1)).date()
    stock_start = (
        cutoff - pd.DateOffset(years=QUANT_STOCK_HISTORY_YEARS) - pd.Timedelta(days=14)
    ).date()
    market_tickers = [ticker for ticker in portfolio.tickers if ticker != CASH_TICKER]
    analysis_tickers = list(
        dict.fromkeys([*market_tickers, *([benchmark_ticker] if benchmark_ticker else [])])
    )
    if not analysis_tickers:
        raise ValueError("Quant V2 requires at least one market holding")

    with ThreadPoolExecutor(max_workers=3) as pool:
        public_future = pool.submit(
            load_quant_public_inputs,
            client=public_client,
            end=cutoff,
        )
        stock_future = pool.submit(
            fetch_daily_prices,
            analysis_tickers,
            start=stock_start,
            end=yf_end,
        )
        state_future = pool.submit(
            fetch_daily_prices,
            ["HYG", "SHY"],
            start=QUANT_STATE_PRICE_START,
            end=yf_end,
        )
        public = public_future.result()
        stock_prices = stock_future.result()
        state_prices = state_future.result()

    missing_stocks = set(analysis_tickers) - set(stock_prices.columns)
    if missing_stocks:
        raise ValueError(f"daily price history is unavailable for {sorted(missing_stocks)}")
    missing_states = {"HYG", "SHY"} - set(state_prices.columns)
    if missing_states:
        raise ValueError(f"credit-state price history is unavailable for {sorted(missing_states)}")

    local_returns = (
        stock_prices.loc[:, analysis_tickers].pct_change(fill_method=None).dropna(how="all")
    )
    ticker_returns = convert_daily_returns_to_usd(local_returns, end=yf_end)
    metadata_snapshot = ticker_metadata()
    metadata = {
        ticker: metadata_snapshot.get(ticker, _BUILTIN_BENCHMARK_METADATA.get(ticker, {}))
        for ticker in analysis_tickers
    }
    all_betas, estimates = estimate_portfolio_exposures(
        ticker_returns,
        metadata=metadata,
        regional_factors=public.regional_factors,
        us_industries=public.us_industries,
        end=cutoff,
    )
    factor_returns = _factor_return_union(public, estimates, list(all_betas.columns))

    betas = all_betas.reindex(index=portfolio.tickers, columns=factor_returns.columns).fillna(0.0)
    benchmark_beta = (
        all_betas.loc[benchmark_ticker, factor_returns.columns].copy()
        if benchmark_ticker is not None
        else None
    )
    benchmark_exposure = estimates.get(benchmark_ticker) if benchmark_ticker else None
    states = (
        public.state_levels.join(state_prices.loc[:, ["HYG", "SHY"]], how="outer")
        .sort_index()
        .loc[lambda frame: frame.index <= cutoff]
    )
    return QuantPreparedInputs(
        factor_returns=factor_returns,
        state_levels=states,
        betas=betas,
        exposures={ticker: estimates[ticker] for ticker in market_tickers},
        sources=public.sources,
        benchmark_beta=benchmark_beta,
        benchmark_exposure=benchmark_exposure,
    )
