"""Phase 1 sign-off tests for vintage-controlled backdated scenarios.

Each test maps to a criterion from the plan:
  1. Filter uses end_date, not start_date
  2. yfinance end= threads through, warm cache bypassed
  3. Backdated never calls Google Search
  4. (adjust_scenario_shocks vintage tested separately in test_adjust_backdating.py)
  5. (saved record inline-ness tested in test_api_saved.py)
  6. Cache namespace isolation
  7. Graceful 422 on insufficient analogs / factor rows
"""

from __future__ import annotations

from datetime import date

import pytest

from app.llm.scenario import (
    MIN_ELIGIBLE_ANALOG_EVENTS,
    compute_scenario_cache_key,
    run_scenario,
)
from tests.conftest import InMemoryCache
from tests.test_scenario import _config, _MockGeminiClient, _patch_market_layer


def test_backdated_run_sets_narrative_mode_analog_only(monkeypatch):
    captured = _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    result = run_scenario(
        scenario_text="historical-style stress",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2020, 6, 1),  # well in the past
    )

    assert result.narrative_mode == "analog_only"
    assert result.citations == []
    assert type(gemini).last_analog_grounded is True
    # yfinance end= threaded through (criterion 2). yfinance end is exclusive,
    # so we pass effective_as_of + 1 day. 2020-06-01 is a Monday (trading day),
    # so effective_as_of == requested.
    expected_end = date(2020, 6, 2)
    assert captured["weekly_prices_end"] == expected_end
    assert captured["factor_history_end"] == expected_end
    # Warm cache must NOT be used on the backdated path (criterion 2).
    assert "warm_cache_called" not in captured


def test_live_run_uses_warm_cache_and_grounded_path(monkeypatch):
    """Symmetry check: when market_date is today, the live path is taken."""
    captured = _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    result = run_scenario(
        scenario_text="live current-news scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date.today(),
    )

    assert result.narrative_mode == "grounded"
    assert result.citations  # mock returns one for live runs
    assert type(gemini).last_analog_grounded is False
    assert captured["weekly_prices_end"] is None
    assert captured.get("warm_cache_called") is True


def test_backdated_run_resolves_weekend_to_friday(monkeypatch):
    """The effective_as_of date used in the cache key and yfinance end is the
    last NYSE trading day on or before the user's requested date."""
    captured = _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    # 2020-06-13 is a Saturday -> effective Friday 2020-06-12.
    result = run_scenario(
        scenario_text="weekend-anchored backdated scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2020, 6, 13),
    )

    assert result.market_date == date(2020, 6, 12)
    assert result.requested_as_of_date == date(2020, 6, 13)
    assert captured["weekly_prices_end"] == date(2020, 6, 13)  # +1 day exclusive


def test_backdated_cache_namespace_disjoint_from_live(monkeypatch):
    """Same (text, portfolio) at different as-of dates produces different cache keys."""
    _patch_market_layer(monkeypatch)
    config = _config()

    live_key = compute_scenario_cache_key(
        "same text", "us_tech_growth", config=config, market_date=date.today()
    )
    back_key = compute_scenario_cache_key(
        "same text", "us_tech_growth", config=config, market_date=date(2020, 6, 1)
    )
    assert live_key != back_key


def test_backdated_too_few_analogs_raises(monkeypatch):
    """Criterion 7: backdating to a date before most analogs ended must raise
    a ValueError that the API layer translates to 422.
    """
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    # Date in 2007 — before nearly every event in historical_events.yaml.
    with pytest.raises(ValueError, match="eligible historical analogs"):
        run_scenario(
            scenario_text="ancient scenario",
            portfolio_key="us_tech_growth",
            config=_config(),
            gemini=gemini,
            cache=cache,
            market_date=date(2006, 1, 1),
        )

    assert MIN_ELIGIBLE_ANALOG_EVENTS >= 2  # sanity
