"""End-to-end assembly of public Quant V2 model inputs without network access."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from app.data.sample_portfolios import Portfolio


def _region_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    rng = np.random.default_rng(23)
    market = rng.normal(0.0002, 0.008, len(index))
    return pd.DataFrame(
        {
            "MKT_RF": market,
            "SMB": rng.normal(0, 0.003, len(index)),
            "HML": rng.normal(0, 0.003, len(index)),
            "RMW": rng.normal(0, 0.002, len(index)),
            "CMA": rng.normal(0, 0.002, len(index)),
            "MOM": rng.normal(0, 0.004, len(index)),
            "RF": np.full(len(index), 0.0001),
        },
        index=index,
    )


def test_prepare_quant_inputs_aligns_public_factors_state_and_exposures(monkeypatch) -> None:
    from app.data.quant_sources import QuantPublicInputs, SourceVersion
    from app.factors import quant_inputs
    from app.factors.quant_inputs import prepare_quant_inputs

    index = pd.date_range("2021-01-04", periods=900, freq="B")
    regional = {name: _region_frame(index) for name in quant_inputs.REGION_PREFIX}
    official_state = pd.DataFrame(
        {
            "VIX": 20 * np.exp(np.linspace(0, 0.2, len(index))),
            "US_10Y_YIELD": np.linspace(0.01, 0.04, len(index)),
            "BROAD_DOLLAR": np.linspace(90, 110, len(index)),
            "WTI": np.linspace(40, 80, len(index)),
        },
        index=index,
    )
    industries = pd.DataFrame({"BusEq": regional["north_america"]["MKT_RF"] + 0.001}, index=index)
    source = SourceVersion(
        "test-source", "https://example.test", "a" * 64, datetime(2024, 1, 1, tzinfo=UTC)
    )
    bundle = QuantPublicInputs(
        regional_factors=regional,
        us_industries=industries,
        state_levels=official_state,
        sources={source.dataset_id: source},
    )

    monkeypatch.setattr(quant_inputs, "load_quant_public_inputs", lambda **_kwargs: bundle)
    monkeypatch.setattr(
        quant_inputs,
        "ticker_metadata",
        lambda: {"AAPL": {"country": "United States", "sector": "Technology"}},
    )
    monkeypatch.setattr(
        quant_inputs,
        "convert_daily_returns_to_usd",
        lambda returns, **_kwargs: returns,
    )

    stock_returns = regional["north_america"]["RF"] + 1.2 * regional["north_america"]["MKT_RF"]
    stock_prices = 100 * (1 + stock_returns).cumprod()

    def _prices(tickers, **_kwargs):
        if set(tickers) == {"HYG", "SHY"}:
            return pd.DataFrame(
                {
                    "HYG": 80 * np.exp(np.linspace(0, 0.1, len(index))),
                    "SHY": 82 * np.exp(np.linspace(0, 0.02, len(index))),
                },
                index=index,
            )
        assert tickers == ["AAPL", "QQQ"]
        return pd.DataFrame({"AAPL": stock_prices, "QQQ": stock_prices}, index=index)

    monkeypatch.setattr(quant_inputs, "fetch_daily_prices", _prices)
    portfolio = Portfolio(name="Test", description="Test", holdings={"AAPL": 1.0})

    prepared = prepare_quant_inputs(portfolio, as_of=index[-1], benchmark_ticker="QQQ")

    assert list(prepared.betas.index) == ["AAPL"]
    assert set(prepared.factor_returns.columns) == set(prepared.betas.columns)
    assert set(prepared.state_levels.columns) == {
        "VIX",
        "US_10Y_YIELD",
        "BROAD_DOLLAR",
        "WTI",
        "HYG",
        "SHY",
    }
    assert prepared.exposures["AAPL"].tier == "estimated"
    assert prepared.exposures["AAPL"].industry_mapping == "coarse-sector-to-ff12-v1"
    assert prepared.benchmark_exposure is not None
    assert prepared.benchmark_exposure.region == "north_america"
    assert prepared.benchmark_beta is not None
    assert not any(name.startswith("DEV:") for name in prepared.benchmark_beta.index)
    assert prepared.sources == {"test-source": source}
