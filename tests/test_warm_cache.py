"""Warm-cache memoization semantics — healthy results cached, degraded never,
concurrent fetches single-flight."""

from __future__ import annotations

import threading
import time

import pandas as pd
import pytest

from app.factors import warm_cache
from app.factors.universe import FACTORS


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    warm_cache.clear()
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: None, raising=False)
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
    matrix = pd.DataFrame(
        -0.05,
        index=["covid-crash-2020", "q4-trade-war-2018"],
        columns=list(FACTORS),
    )
    matrix.loc["covid-crash-2020", "GLD"] = float("nan")
    if all_nan_row:
        matrix.loc["q4-trade-war-2018"] = float("nan")
    return matrix


class _PersistentMatrixCache:
    def __init__(self) -> None:
        self.store: dict[str, pd.DataFrame] = {}
        self.get_calls: list[tuple[str, int]] = []
        self.put_calls: list[str] = []

    def get(self, key: str, ttl_hours: int = 24) -> pd.DataFrame | None:
        self.get_calls.append((key, ttl_hours))
        value = self.store.get(key)
        return None if value is None else value.copy()

    def put(self, key: str, value: pd.DataFrame) -> None:
        self.put_calls.append(key)
        self.store[key] = value.copy()


def _patch_event_versions(monkeypatch, *, events: str = "events-v1") -> None:
    monkeypatch.setattr(warm_cache, "events_version", lambda: events)
    monkeypatch.setattr(warm_cache, "factor_universe_version", lambda: "factors-v1")
    monkeypatch.setattr(warm_cache, "MARKET_CACHE_VERSION", "market-v1")
    monkeypatch.setattr(
        warm_cache,
        "load_events",
        lambda: dict.fromkeys(_events_matrix().index),
    )


def test_event_matrix_memoized_per_events_version(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(event_ids, registry=None):
        calls["n"] += 1
        return _events_matrix()

    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", fake_fetch)
    monkeypatch.setattr(
        warm_cache,
        "load_events",
        lambda: dict.fromkeys(_events_matrix().index),
    )
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
    monkeypatch.setattr(
        warm_cache,
        "load_events",
        lambda: dict.fromkeys(_events_matrix().index),
    )
    monkeypatch.setattr(warm_cache, "events_version", lambda: "v-one")

    with pytest.raises(RuntimeError, match="event-return matrix"):
        warm_cache.get_event_returns_matrix()

    healed = warm_cache.get_event_returns_matrix()
    assert calls["n"] == 2
    assert not healed.isna().all(axis=1).any()

    cached = warm_cache.get_event_returns_matrix()
    assert calls["n"] == 2
    assert cached is healed


def test_factor_fetch_is_single_flight_under_concurrency(monkeypatch):
    """A request racing the background startup warm must WAIT for the in-flight
    fetch and reuse it — a concurrent duplicate fan-out contends on provider
    rate limits and made the racing request slower than no warm at all."""
    calls = {"n": 0}

    def slow_fetch(lookback_weeks=156):
        calls["n"] += 1
        time.sleep(0.15)
        return _frames()

    monkeypatch.setattr(warm_cache, "fetch_factor_returns_with_history", slow_fetch)

    results: list = []
    threads = [
        threading.Thread(
            target=lambda: results.append(warm_cache.get_factor_returns_with_history(156))
        )
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls["n"] == 1
    assert all(r is results[0] for r in results)


def test_event_matrix_fetch_is_single_flight_under_concurrency(monkeypatch):
    calls = {"n": 0}

    def slow_fetch(event_ids, registry=None):
        calls["n"] += 1
        time.sleep(0.15)
        return _events_matrix()

    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", slow_fetch)
    monkeypatch.setattr(
        warm_cache,
        "load_events",
        lambda: dict.fromkeys(_events_matrix().index),
    )
    monkeypatch.setattr(warm_cache, "events_version", lambda: "v-one")

    results: list = []
    threads = [
        threading.Thread(target=lambda: results.append(warm_cache.get_event_returns_matrix()))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls["n"] == 1
    assert all(r is results[0] for r in results)


def test_event_matrix_persists_for_30_days_across_process_cache_clears(monkeypatch):
    persistent = _PersistentMatrixCache()
    calls = {"n": 0}

    def fake_fetch(event_ids, registry=None):
        calls["n"] += 1
        return _events_matrix()

    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", fake_fetch)

    first = warm_cache.get_event_returns_matrix()
    assert calls["n"] == 1
    assert persistent.put_calls

    warm_cache.clear()
    second = warm_cache.get_event_returns_matrix()

    assert calls["n"] == 1
    pd.testing.assert_frame_equal(second, first)
    assert persistent.get_calls[-1][1] == 24 * 30


def test_event_matrix_cache_key_invalidates_on_each_version(monkeypatch):
    persistent = _PersistentMatrixCache()
    calls = {"n": 0}

    def fake_fetch(event_ids, registry=None):
        calls["n"] += 1
        return _events_matrix()

    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", fake_fetch)

    warm_cache.get_event_returns_matrix()
    first_key = persistent.put_calls[-1]

    for name, replacement in (
        ("events_version", lambda: "events-v2"),
        ("factor_universe_version", lambda: "factors-v2"),
    ):
        warm_cache.clear()
        monkeypatch.setattr(warm_cache, name, replacement)
        warm_cache.get_event_returns_matrix()

    warm_cache.clear()
    monkeypatch.setattr(warm_cache, "MARKET_CACHE_VERSION", "market-v2")
    warm_cache.get_event_returns_matrix()

    assert calls["n"] == 4
    assert len(set(persistent.put_calls)) == 4
    assert first_key != persistent.put_calls[-1]


@pytest.mark.parametrize("malformation", ["missing_row", "wrong_columns", "all_nan_row"])
def test_malformed_persistent_event_matrix_is_rejected_and_replaced(monkeypatch, malformation):
    persistent = _PersistentMatrixCache()
    healthy = _events_matrix()
    malformed = healthy.copy()
    if malformation == "missing_row":
        malformed = malformed.iloc[:1]
    elif malformation == "wrong_columns":
        malformed = malformed.drop(columns=[malformed.columns[-1]])
    else:
        malformed.iloc[0] = float("nan")

    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    key = warm_cache.event_matrix_cache_key()
    persistent.store[key] = malformed
    calls = {"n": 0}

    def fake_fetch(event_ids, registry=None):
        calls["n"] += 1
        return healthy

    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", fake_fetch)
    result = warm_cache.get_event_returns_matrix()

    assert calls["n"] == 1
    pd.testing.assert_frame_equal(result, healthy)
    pd.testing.assert_frame_equal(persistent.store[key], healthy)


def test_degraded_live_event_matrix_is_never_persisted(monkeypatch):
    persistent = _PersistentMatrixCache()
    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    monkeypatch.setattr(
        warm_cache,
        "fetch_event_returns_matrix",
        lambda event_ids, registry=None: _events_matrix(all_nan_row=True),
    )

    with pytest.raises(RuntimeError, match="event-return matrix"):
        warm_cache.get_event_returns_matrix()
    assert persistent.put_calls == []


def test_selected_events_reuse_persistent_full_matrix_without_live_fetch(monkeypatch):
    persistent = _PersistentMatrixCache()
    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    persistent.store[warm_cache.event_matrix_cache_key()] = _events_matrix()

    def unexpected_fetch(event_ids, registry=None):
        raise AssertionError("selected events should reuse the persistent full matrix")

    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", unexpected_fetch)
    selected = ["q4-trade-war-2018"]
    result = warm_cache.get_selected_event_returns_matrix(
        selected,
        registry=dict.fromkeys(selected),
    )

    assert list(result.index) == selected
    assert list(result.columns) == list(FACTORS)


def test_selected_events_fetch_only_selection_when_full_cache_misses(monkeypatch):
    persistent = _PersistentMatrixCache()
    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    captured: list[str] = []

    def fake_fetch(event_ids, registry=None):
        captured.extend(event_ids)
        return _events_matrix().loc[event_ids]

    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", fake_fetch)
    selected = ["covid-crash-2020"]
    result = warm_cache.get_selected_event_returns_matrix(
        selected,
        registry=dict.fromkeys(selected),
    )

    assert captured == selected
    assert list(result.index) == selected


@pytest.mark.parametrize("malformation", ["missing_row", "wrong_columns", "all_nan_row"])
def test_selected_event_fetch_rejects_malformed_matrix(monkeypatch, malformation):
    persistent = _PersistentMatrixCache()
    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    selected = ["covid-crash-2020", "q4-trade-war-2018"]
    malformed = _events_matrix()
    if malformation == "missing_row":
        malformed = malformed.iloc[:1]
    elif malformation == "wrong_columns":
        malformed = malformed.drop(columns=[malformed.columns[-1]])
    else:
        malformed.iloc[0] = float("nan")
    monkeypatch.setattr(
        warm_cache,
        "fetch_event_returns_matrix",
        lambda event_ids, registry=None: malformed,
    )

    with pytest.raises(RuntimeError, match="event-return matrix"):
        warm_cache.get_selected_event_returns_matrix(
            selected,
            registry=dict.fromkeys(selected),
        )


def test_selected_event_cache_hit_preserves_duplicate_validation(monkeypatch):
    persistent = _PersistentMatrixCache()
    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    persistent.store[warm_cache.event_matrix_cache_key()] = _events_matrix()
    duplicate = ["covid-crash-2020", "covid-crash-2020"]

    with pytest.raises(ValueError, match="duplicate event_ids"):
        warm_cache.get_selected_event_returns_matrix(
            duplicate,
            registry={"covid-crash-2020": None},
        )
