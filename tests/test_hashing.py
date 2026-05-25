"""Cache-key correctness tests — defends finding #1 from the v2 plan review."""

from __future__ import annotations

from datetime import date

from app.utils.hashing import scenario_cache_key


def _base_kwargs(**overrides):
    base = {
        "scenario_text": "60% tariffs on China imports",
        "portfolio_key": "us_tech_growth",
        "portfolio_holdings": {"AAPL": 0.5, "MSFT": 0.5},
        "market_date": date(2026, 5, 25),
        "model_id": "gemini-3.5-flash",
        "prompt_version": "v1",
        "factor_universe_version": "abcdef012345",
        "events_version": "0123456789ab",
    }
    base.update(overrides)
    return base


def test_scenario_cache_key_is_deterministic():
    k1 = scenario_cache_key(**_base_kwargs())
    k2 = scenario_cache_key(**_base_kwargs())
    assert k1 == k2


def test_scenario_cache_key_sensitive_to_weights():
    k1 = scenario_cache_key(**_base_kwargs(portfolio_holdings={"AAPL": 0.5, "MSFT": 0.5}))
    k2 = scenario_cache_key(**_base_kwargs(portfolio_holdings={"AAPL": 0.6, "MSFT": 0.4}))
    assert k1 != k2, "Same tickers + different weights must produce different cache keys"


def test_scenario_cache_key_sensitive_to_model_and_prompt_version():
    base = _base_kwargs()
    k_default = scenario_cache_key(**base)
    k_model_bump = scenario_cache_key(**{**base, "model_id": "gemini-4-pro"})
    k_prompt_bump = scenario_cache_key(**{**base, "prompt_version": "v2"})
    k_universe_bump = scenario_cache_key(**{**base, "factor_universe_version": "ffffffffffff"})
    k_events_bump = scenario_cache_key(**{**base, "events_version": "ffffffffffff"})

    assert k_default != k_model_bump
    assert k_default != k_prompt_bump
    assert k_default != k_universe_bump
    assert k_default != k_events_bump


def test_scenario_cache_key_order_independent_on_holdings():
    k1 = scenario_cache_key(**_base_kwargs(portfolio_holdings={"AAPL": 0.5, "MSFT": 0.5}))
    k2 = scenario_cache_key(**_base_kwargs(portfolio_holdings={"MSFT": 0.5, "AAPL": 0.5}))
    assert k1 == k2, "Holdings dict iteration order must not affect the cache key"


def test_scenario_cache_key_sensitive_to_text_case_only_via_normalization():
    # Text is lowercased + stripped before hashing, so case/whitespace should NOT change the key.
    k1 = scenario_cache_key(**_base_kwargs(scenario_text="China Tariffs Scenario"))
    k2 = scenario_cache_key(**_base_kwargs(scenario_text="  china tariffs scenario  "))
    assert k1 == k2

    # But genuinely different text DOES change the key.
    k3 = scenario_cache_key(**_base_kwargs(scenario_text="Different scenario entirely"))
    assert k1 != k3
