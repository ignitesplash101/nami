"""Quant V2 orchestration, cache, and legacy-compatibility contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from app.config import Config
from app.data.quant_sources import SourceVersion
from app.data.sample_portfolios import Portfolio
from app.factors.quant_exposure import ExposureEstimate
from app.factors.quant_inputs import QuantPreparedInputs
from app.llm.schemas import (
    AnalogSelection,
    AnalogSelectionOutput,
    Citation,
    StateDirection,
)
from tests.conftest import InMemoryCache


class _QuantGemini:
    def __init__(self) -> None:
        self.selection_calls = 0
        self.narrative_calls = 0

    def select_analogs(self, scenario_text, event_summaries):
        self.selection_calls += 1
        assert scenario_text
        assert event_summaries
        return AnalogSelectionOutput(
            selected_events=[
                AnalogSelection(event_id="lehman-gfc-2008", why_relevant="credit seizure"),
                AnalogSelection(event_id="covid-crash-2020", why_relevant="sudden stop"),
            ],
            reasoning="joint stress",
            state_directions=[
                StateDirection(state=state, direction="neutral", reasoning="unconstrained")
                for state in ("volatility", "rates", "dollar", "oil", "credit")
            ],
        )

    def select_quant_analogs(self, scenario_text, event_summaries):
        return self.select_analogs(scenario_text, event_summaries)

    def narrate_quant_scenario(self, **kwargs):
        self.narrative_calls += 1
        assert kwargs["factor_ranges"]
        assert kwargs["support"]["effective_sample_size"] >= 20
        return "Grounded Quant V2 narrative.", [
            Citation(url="https://www.federalreserve.gov/example", title="Official source")
        ]


class _DuplicateAnalogGemini(_QuantGemini):
    def select_analogs(self, scenario_text, event_summaries):
        output = super().select_analogs(scenario_text, event_summaries)
        return output.model_copy(
            update={"selected_events": [output.selected_events[0], output.selected_events[0]]}
        )


def _config() -> Config:
    return Config(
        google_cloud_project="test-project",
        vertex_ai_location="global",
        gcs_bucket="test-bucket",
        engine_mode="quant_v2",
    )


def _prepared() -> QuantPreparedInputs:
    rng = np.random.default_rng(31)
    index = pd.date_range("2007-01-02", periods=4100, freq="B")
    factor_returns = pd.DataFrame({"NA:MKT_RF": rng.normal(0, 0.01, len(index))}, index=index)
    state_levels = pd.DataFrame(
        {
            "VIX": 20 * np.exp(np.cumsum(rng.normal(0, 0.01, len(index)))),
            "US_10Y_YIELD": 0.03 + np.cumsum(rng.normal(0, 0.0001, len(index))),
            "BROAD_DOLLAR": 100 * np.exp(np.cumsum(rng.normal(0, 0.001, len(index)))),
            "WTI": 60 + np.cumsum(rng.normal(0, 0.3, len(index))),
            "HYG": 80 * np.exp(np.cumsum(rng.normal(0, 0.001, len(index)))),
            "SHY": 82 * np.exp(np.cumsum(rng.normal(0, 0.0002, len(index)))),
        },
        index=index,
    )
    exposure = ExposureEstimate(
        ticker="AAPL",
        region="north_america",
        tier="estimated",
        n_obs=156,
        coefficients={"NA:MKT_RF": 1.1},
        prior={"NA:MKT_RF": 1.0},
        data_weight=1.0,
        industry_factor=None,
        industry_mapping=None,
    )
    benchmark_exposure = ExposureEstimate(
        ticker="QQQ",
        region="north_america",
        tier="estimated",
        n_obs=156,
        coefficients={"NA:MKT_RF": 1.0},
        prior={"NA:MKT_RF": 1.0},
        data_weight=1.0,
        industry_factor=None,
        industry_mapping=None,
    )
    source = SourceVersion(
        "north_america_five_daily",
        "https://example.test/factors.zip",
        "a" * 64,
        datetime(2022, 12, 30, tzinfo=UTC),
    )
    return QuantPreparedInputs(
        factor_returns=factor_returns,
        state_levels=state_levels,
        betas=pd.DataFrame({"NA:MKT_RF": [1.1]}, index=["AAPL"]),
        exposures={"AAPL": exposure},
        sources={source.dataset_id: source},
        benchmark_beta=pd.Series({"NA:MKT_RF": 1.0}),
        benchmark_exposure=benchmark_exposure,
    )


def test_quant_v2_run_uses_direct_history_not_numeric_llm_shocks(monkeypatch) -> None:
    import app.llm.scenario as scenario_module

    monkeypatch.setattr(scenario_module, "latest_market_date", lambda: date(2022, 12, 30))
    monkeypatch.setattr(
        scenario_module, "prepare_quant_inputs", lambda *args, **kwargs: _prepared()
    )
    cache = InMemoryCache()
    gemini = _QuantGemini()
    portfolio = Portfolio(name="Test", description="Test", holdings={"AAPL": 1.0})
    progress_events: list[tuple[str, str]] = []

    result = scenario_module.run_scenario(
        "A synchronized global shutdown and credit seizure",
        portfolio,
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2022, 12, 30),
        horizon=21,
        severity=1.5,
        benchmark="QQQ",
        progress=lambda stage, status: progress_events.append((stage, status)),
    )

    assert result.engine_mode == "quant_v2"
    assert result.methodology == "joint_historical_neighbors"
    assert result.horizon_trading_days == 21
    assert result.severity_multiplier == 1.5
    assert result.historical_model_range is not None
    assert result.quant_support is not None
    assert result.quant_support.neighbor_count <= 50
    assert result.portfolio_pnl.by_factor_conditional_shapley is None
    assert result.portfolio_pnl.by_factor_conditional_shapley_grouped is None
    assert result.periphery_shocks == []
    assert result.quant_exposures["AAPL"].tier == "estimated"
    assert result.quant_source_versions["north_america_five_daily"].sha256 == "a" * 64
    assert result.benchmark_ticker == "QQQ"
    assert result.benchmark_pnl is not None
    assert result.active_return == pytest.approx(
        result.portfolio_pnl.total_pnl - result.benchmark_pnl.total_pnl
    )
    assert gemini.selection_calls == 1
    assert gemini.narrative_calls == 1
    assert len(cache.store) == 1
    assert [stage for stage, status in progress_events if status == "start"] == [
        "cache_check",
        "market",
        "analogs",
        "attribution",
        "narrative",
    ]

    cached = scenario_module.run_scenario(
        "A synchronized global shutdown and credit seizure",
        portfolio,
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2022, 12, 30),
        horizon=21,
        severity=1.5,
        benchmark="QQQ",
    )
    assert cached.model_dump() == result.model_dump()
    assert gemini.selection_calls == 1
    assert gemini.narrative_calls == 1


def test_quant_v2_rejects_duplicate_analog_ids(monkeypatch) -> None:
    import app.llm.scenario as scenario_module

    monkeypatch.setattr(scenario_module, "latest_market_date", lambda: date(2022, 12, 30))
    monkeypatch.setattr(
        scenario_module, "prepare_quant_inputs", lambda *args, **kwargs: _prepared()
    )

    with pytest.raises(ValueError, match="duplicate"):
        scenario_module.run_scenario(
            "A synchronized global shutdown and credit seizure",
            Portfolio(name="Test", description="Test", holdings={"AAPL": 1.0}),
            config=_config(),
            gemini=_DuplicateAnalogGemini(),
            cache=InMemoryCache(),
            market_date=date(2022, 12, 30),
        )
