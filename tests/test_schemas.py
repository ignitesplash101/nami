"""Pydantic schema sanity tests for the cache round-trip."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.llm.schemas import (
    AnalogSelection,
    Citation,
    FactorShock,
    PeripheryShock,
    PortfolioPnL,
    ScenarioResult,
)


def _sample_pnl() -> PortfolioPnL:
    return PortfolioPnL(
        total_pnl=-0.05,
        by_factor_naive={"SPY": -0.03, "VIX": -0.02},
        by_factor_conditional_shapley={"SPY": -0.025, "VIX": -0.025},
        by_ticker_factor={"AAPL": -0.02, "MSFT": -0.03},
        by_ticker_periphery={"AAPL": 0.0, "MSFT": 0.0},
        by_ticker_total={"AAPL": -0.02, "MSFT": -0.03},
    )


def _sample_result() -> ScenarioResult:
    return ScenarioResult(
        scenario_text="test scenario",
        market_date=date(2026, 5, 25),
        portfolio_key="us_tech_growth",
        analogs_selected=[
            AnalogSelection(event_id="covid-crash-2020", why_relevant="pandemic shock")
        ],
        factor_shocks=[FactorShock(factor="SPY", shock=-0.07, reasoning="equities sell off")],
        periphery_shocks=[
            PeripheryShock(ticker="AAPL", shock=-0.05, reasoning="China supply chain")
        ],
        narrative="A test narrative.",
        citations=[Citation(url="https://example.com", title="Source")],
        factor_envelope={"SPY": {"mean": -0.05, "p10": -0.10, "p90": 0.0, "count": 3.0}},
        portfolio_pnl=_sample_pnl(),
    )


def test_factor_shock_rejects_unknown_field():
    with pytest.raises(ValidationError):
        FactorShock(factor="SPY", shock=-0.07, reasoning="x", extra_field="boom")


def test_scenario_result_json_roundtrip():
    original = _sample_result()
    dumped = original.model_dump(mode="json")
    rehydrated = ScenarioResult.model_validate(dumped)
    assert rehydrated == original


def test_portfolio_pnl_model_from_portfolio_pnl_dict():
    # Mirrors the shape `app.factors.shocks.portfolio_pnl` returns.
    raw = {
        "total_pnl": -0.05,
        "by_factor_naive": {"SPY": -0.03, "VIX": -0.02},
        "by_factor_conditional_shapley": None,
        "by_ticker_factor": {"AAPL": -0.02, "MSFT": -0.03},
        "by_ticker_periphery": {"AAPL": 0.0, "MSFT": 0.0},
        "by_ticker_total": {"AAPL": -0.02, "MSFT": -0.03},
    }
    pnl = PortfolioPnL(**raw)
    assert pnl.total_pnl == -0.05
    assert pnl.by_factor_naive["SPY"] == -0.03
    assert pnl.by_factor_conditional_shapley is None
