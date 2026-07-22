"""Cache-key correctness tests — defends finding #1 from the v2 plan review."""

from __future__ import annotations

from datetime import date

from app.data.market_cache import market_cache_key
from app.utils.hashing import scenario_cache_key


def _base_kwargs(**overrides):
    base = {
        "scenario_text": "60% tariffs on China imports",
        "portfolio_key": "us_tech_growth",
        "portfolio_holdings": {"AAPL": 0.5, "MSFT": 0.5},
        "market_date": date(2026, 5, 25),
        "model_id": "gemini-3.6-flash",
        "prompt_version": "v1",
        "factor_universe_version": "abcdef012345",
        "events_version": "0123456789ab",
        "regression_spec": "ridge-std-v2|lookback=156|alpha=0.1|min_obs=40",
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


def test_scenario_cache_key_sensitive_to_regression_spec():
    # The regression spec is the engine-math invalidation lever: a different
    # estimator id, alpha, or lookback must never serve a stale cached result.
    base = _base_kwargs()
    k_default = scenario_cache_key(**base)
    k_alpha = scenario_cache_key(
        **{**base, "regression_spec": "ridge-std-v2|lookback=156|alpha=0.5|min_obs=40"}
    )
    k_lookback = scenario_cache_key(
        **{**base, "regression_spec": "ridge-std-v2|lookback=104|alpha=0.1|min_obs=40"}
    )
    k_estimator = scenario_cache_key(
        **{**base, "regression_spec": "ridge-raw-v1|lookback=156|alpha=0.1|min_obs=40"}
    )
    assert k_default != k_alpha
    assert k_default != k_lookback
    assert k_default != k_estimator


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


# --- Mark-to-market cache-key behavior ---


def test_scenario_cache_key_quantities_change_the_key():
    base = _base_kwargs()
    k_no = scenario_cache_key(**base)
    k_q = scenario_cache_key(**base, position_quantities={"AAPL": 10, "MSFT": 5})
    assert k_no != k_q, "MTM quantity inputs must produce a distinct cache key"


def test_scenario_cache_key_absent_quantities_is_byte_identical():
    # Back-compat guard: weight-only / NAV-scalar runs (no quantities) must hash
    # EXACTLY as before, so adding MTM did not invalidate any existing cache entry.
    base = _base_kwargs()
    assert scenario_cache_key(**base) == scenario_cache_key(**base, position_quantities=None)
    assert scenario_cache_key(**base) == scenario_cache_key(**base, position_quantities={})


def test_scenario_cache_key_quantities_order_independent():
    base = _base_kwargs()
    k1 = scenario_cache_key(**base, position_quantities={"AAPL": 10, "MSFT": 5})
    k2 = scenario_cache_key(**base, position_quantities={"MSFT": 5, "AAPL": 10})
    assert k1 == k2


def test_scenario_cache_key_pinned_event_ids_behavior():
    base = _base_kwargs()
    # Present -> distinct keyspace (fixed-context decomposition subset).
    assert scenario_cache_key(**base) != scenario_cache_key(**base, pinned_event_ids=["covid"])
    # Absent / empty -> byte-identical to a normal run (no invalidation).
    assert scenario_cache_key(**base) == scenario_cache_key(**base, pinned_event_ids=None)
    assert scenario_cache_key(**base) == scenario_cache_key(**base, pinned_event_ids=[])
    # Order-independent.
    assert scenario_cache_key(**base, pinned_event_ids=["a", "b"]) == scenario_cache_key(
        **base, pinned_event_ids=["b", "a"]
    )


def test_market_cache_key_distinguishes_raw_from_adjusted():
    adj = market_cache_key(["AAPL"], interval="1d", start="2024-01-01", end="2024-01-10")
    raw = market_cache_key(
        ["AAPL"], interval="1d", start="2024-01-01", end="2024-01-10", auto_adjust=False
    )
    assert adj != raw, "raw close and adjusted close must not collide in the market cache"
    # The default (adjusted) key is unchanged by the new param — no invalidation.
    assert adj == market_cache_key(
        ["AAPL"], interval="1d", start="2024-01-01", end="2024-01-10", auto_adjust=True
    )
