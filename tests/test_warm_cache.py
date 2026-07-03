"""Warm-cache memoization semantics — healthy results cached, degraded never."""

from __future__ import annotations

import pandas as pd
import pytest

from app.factors import warm_cache


@pytest.fixture(autouse=True)
def _fresh_cache():
    warm_cache.clear()
    yield
    warm_cache.clear()


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.DataFrame({"SPY": [0.01, -0.02, 0.005]})
    return raw, raw - raw.mean()


def test_healthy_result_is_memoized(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(lookback_weeks=156):
        calls["n"] += 1
        return _frames()

    monkeypatch.setattr(warm_cache, "fetch_factor_returns_with_history", fake_fetch)
    first = warm_cache.get_factor_returns_with_history(156)
    second = warm_cache.get_factor_returns_with_history(156)
    assert calls["n"] == 1
    assert first is second


def test_degraded_result_is_returned_but_not_memoized(monkeypatch):
    calls = {"n": 0}
    raw, history = _frames()

    def fake_fetch(lookback_weeks=156):
        calls["n"] += 1
        if calls["n"] == 1:
            return raw, None  # transient failure: SHAP background unavailable
        return raw, history

    monkeypatch.setattr(warm_cache, "fetch_factor_returns_with_history", fake_fetch)

    degraded = warm_cache.get_factor_returns_with_history(156)
    assert degraded[1] is None

    healed = warm_cache.get_factor_returns_with_history(156)
    assert calls["n"] == 2
    assert healed[1] is not None

    cached = warm_cache.get_factor_returns_with_history(156)
    assert calls["n"] == 2  # healthy result now memoized
    assert cached is healed


def test_distinct_lookbacks_cache_independently(monkeypatch):
    calls: list[int] = []

    def fake_fetch(lookback_weeks=156):
        calls.append(lookback_weeks)
        return _frames()

    monkeypatch.setattr(warm_cache, "fetch_factor_returns_with_history", fake_fetch)
    warm_cache.get_factor_returns_with_history(156)
    warm_cache.get_factor_returns_with_history(104)
    warm_cache.get_factor_returns_with_history(156)
    assert calls == [156, 104]


def _events_matrix(*, all_nan_row: bool = False) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "SPY": [-0.3, float("nan") if all_nan_row else -0.1],
            "GLD": [float("nan"), float("nan") if all_nan_row else 0.02],
        },
        index=["covid-crash-2020", "q4-trade-war-2018"],
    )


def test_event_matrix_memoized_per_events_version(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(event_ids, registry=None):
        calls["n"] += 1
        return _events_matrix()

    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", fake_fetch)
    monkeypatch.setattr(warm_cache, "load_events", lambda: {"a": None, "b": None})
    monkeypatch.setattr(warm_cache, "events_version", lambda: "v-one")

    first = warm_cache.get_event_returns_matrix()
    second = warm_cache.get_event_returns_matrix()
    assert calls["n"] == 1
    assert first is second

    monkeypatch.setattr(warm_cache, "events_version", lambda: "v-two")
    warm_cache.get_event_returns_matrix()
    assert calls["n"] == 2  # registry edit invalidates


def test_event_matrix_with_all_nan_row_is_not_memoized(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(event_ids, registry=None):
        calls["n"] += 1
        return _events_matrix(all_nan_row=calls["n"] == 1)

    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", fake_fetch)
    monkeypatch.setattr(warm_cache, "load_events", lambda: {"a": None, "b": None})
    monkeypatch.setattr(warm_cache, "events_version", lambda: "v-one")

    degraded = warm_cache.get_event_returns_matrix()
    assert degraded.isna().all(axis=1).any()

    healed = warm_cache.get_event_returns_matrix()
    assert calls["n"] == 2
    assert not healed.isna().all(axis=1).any()

    cached = warm_cache.get_event_returns_matrix()
    assert calls["n"] == 2
    assert cached is healed
