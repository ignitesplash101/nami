"""Orchestrator tests using injected mocks — no network, no GCS, no Vertex AI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.config import Config
from app.data.sample_portfolios import Portfolio, get_portfolio
from app.factors.universe import FACTORS
from app.llm.gemini_client import GeminiClient
from app.llm.scenario import run_scenario
from app.llm.schemas import (
    AnalogSelection,
    AnalogSelectionOutput,
    Citation,
    FactorShock,
    PeripheryShock,
    ShockProposalOutput,
)
from tests.conftest import InMemoryCache


@dataclass
class _MockGeminiClient:
    """Records calls and returns canned outputs."""

    analog_calls: int = 0
    shock_calls: int = 0
    citations: list[Citation] = field(
        default_factory=lambda: [Citation(url="https://example.com", title="Sample")]
    )

    def select_analogs(self, scenario_text, event_summaries) -> AnalogSelectionOutput:
        self.analog_calls += 1
        return AnalogSelectionOutput(
            selected_events=[
                AnalogSelection(event_id="covid-crash-2020", why_relevant="pandemic stress"),
                AnalogSelection(event_id="lehman-gfc-2008", why_relevant="liquidity freeze"),
            ],
            reasoning="picked two stress analogs",
        )

    def propose_shocks_with_retry(
        self,
        *,
        scenario_text,
        portfolio,
        factor_universe_descriptions,
        envelope,
        events_registry,
        max_retries=1,
    ):
        self.shock_calls += 1
        # Pick the first 3 factors so they line up with the real envelope
        factor_names = list(FACTORS.keys())[:3]
        return (
            ShockProposalOutput(
                factor_shocks=[
                    FactorShock(factor=factor_names[0], shock=-0.05, reasoning="r0"),
                    FactorShock(factor=factor_names[1], shock=-0.03, reasoning="r1"),
                    FactorShock(factor=factor_names[2], shock=-0.02, reasoning="r2"),
                ],
                periphery_shocks=[
                    PeripheryShock(
                        ticker=next(iter(portfolio.holdings)),
                        shock=-0.10,
                        reasoning="periphery on first holding",
                    )
                ],
                narrative="A test narrative grounded in current events.",
            ),
            self.citations,
        )


def _config() -> Config:
    return Config(
        google_cloud_project="test-project",
        vertex_ai_location="global",
        gcs_bucket="test-bucket",
        vertex_model_id="gemini-3.5-flash",
        llm_temperature=0.0,
        market_data_cache_ttl_hours=24,
        llm_cache_ttl_days=7,
        beta_lookback_weeks=104,
        ridge_alpha=0.1,
        log_level="INFO",
        environment="test",
    )


def _patch_market_layer(monkeypatch):
    """Replace yfinance-backed pieces with synthetic deterministic data."""
    factor_names = list(FACTORS.keys())

    def _fake_fetch_event_returns(event):
        # Return a simple pattern: each factor's "event return" = -0.05.
        return pd.Series(dict.fromkeys(factor_names, -0.05), name=event.id)

    def _fake_estimate_betas(portfolio, lookback_weeks=156, alpha=0.1, end=None):
        # Beta of 1.0 to first factor, 0 elsewhere.
        data = np.zeros((len(portfolio.tickers), len(factor_names)))
        data[:, 0] = 1.0
        return pd.DataFrame(data, index=portfolio.tickers, columns=factor_names)

    monkeypatch.setattr("app.factors.analogs.fetch_event_returns", _fake_fetch_event_returns)
    monkeypatch.setattr("app.llm.scenario.estimate_betas_for_portfolio", _fake_estimate_betas)


def test_run_scenario_calls_gemini_and_assembles_result(monkeypatch):
    _patch_market_layer(monkeypatch)

    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    result = run_scenario(
        scenario_text="A pandemic-like risk-off",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )

    assert gemini.analog_calls == 1
    assert gemini.shock_calls == 1
    assert result.scenario_text == "A pandemic-like risk-off"
    assert len(result.analogs_selected) == 2
    assert len(result.factor_shocks) == 3
    assert len(result.periphery_shocks) == 1
    assert result.citations  # mock returns one
    assert result.portfolio_pnl.total_pnl != 0  # SPY beta=1, shock=-0.05 → negative
    assert len(cache.store) == 1


def test_run_scenario_cache_hit_skips_gemini(monkeypatch):
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    run_scenario(
        scenario_text="Same scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    first_calls = (gemini.analog_calls, gemini.shock_calls)

    # Second run — should hit cache and not call gemini.
    run_scenario(
        scenario_text="Same scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    assert (gemini.analog_calls, gemini.shock_calls) == first_calls


def test_run_scenario_cache_key_changes_when_market_date_changes(monkeypatch):
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    run_scenario(
        scenario_text="Same scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    run_scenario(
        scenario_text="Same scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 26),
    )

    assert len(cache.store) == 2, "Different market_date must produce a fresh cache entry"


def test_run_scenario_skip_cache_forces_fresh_call(monkeypatch):
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    run_scenario(
        scenario_text="x",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )

    # skip_cache=True should re-call gemini even though cache has the entry
    run_scenario(
        scenario_text="x",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
        skip_cache=True,
    )

    assert gemini.analog_calls == 2
    assert gemini.shock_calls == 2


def test_get_portfolio_smoke():
    # Sanity check the imports work; placeholder for future portfolio-tests file.
    assert get_portfolio("us_tech_growth") is not None


def test_run_scenario_accepts_portfolio_object_positional(monkeypatch):
    """Passing a Portfolio object as the second positional arg uses 'custom' as resolved_key
    and populates portfolio_name + portfolio_holdings on the result."""
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    custom = Portfolio(
        name="My Custom",
        description="test custom",
        holdings={"AAPL": 0.6, "MSFT": 0.4},
    )

    result = run_scenario(
        "stress",
        custom,
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )

    assert result.portfolio_key == "custom"
    assert result.portfolio_name == "My Custom"
    assert result.portfolio_holdings == {"AAPL": 0.6, "MSFT": 0.4}


def test_run_scenario_rejects_both_portfolio_and_portfolio_key():
    with pytest.raises(ValueError, match="not both"):
        run_scenario(
            "x",
            "us_tech_growth",
            portfolio_key="msci_world",
            config=_config(),
            gemini=_MockGeminiClient(),
            cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
        )


def test_run_scenario_rejects_neither_portfolio_nor_portfolio_key():
    with pytest.raises(ValueError, match="Must pass"):
        run_scenario(
            "x",
            config=_config(),
            gemini=_MockGeminiClient(),
            cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
        )


def test_propose_shocks_raises_when_grounded_narrative_returns_no_citations(monkeypatch):
    """Production guard: do not proceed when Google Search grounding did not fire."""
    client = GeminiClient.__new__(GeminiClient)
    portfolio = get_portfolio("us_tech_growth")
    envelope = pd.DataFrame(
        {"mean": [-0.05], "p10": [-0.10], "p90": [0.0], "count": [2]},
        index=["SPY"],
    )

    def _grounded_narrative_without_citations(**kwargs):
        return "A current-market narrative with no citation metadata.", []

    def _extract_should_not_run(**kwargs):
        raise AssertionError("structured extraction should not run without citations")

    monkeypatch.setattr(client, "_grounded_narrative", _grounded_narrative_without_citations)
    monkeypatch.setattr(client, "_extract_structured_shocks", _extract_should_not_run)

    with pytest.raises(RuntimeError, match="no citations|Google Search"):
        client.propose_shocks_with_retry(
            scenario_text="latest market news",
            portfolio=portfolio,
            factor_universe_descriptions=[],
            envelope=envelope,
            events_registry={},
        )
