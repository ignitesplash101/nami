"""Warm-cache memoization semantics — healthy results cached, degraded never,
concurrent fetches single-flight."""

from __future__ import annotations

import threading
import time
from datetime import date

import pandas as pd
import pytest

from app.factors import warm_cache
from app.factors.analogs import HistoricalEvent
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


def test_warm_uses_the_configured_lookback_not_the_default(monkeypatch):
    """The startup warm must populate the key REQUESTS read.

    Requests pass `config.beta_lookback_weeks`; `warm()` used to hardcode the 156
    default, so setting BETA_LOOKBACK_WEEKS would have made the warm populate a
    key nothing reads — a silent multi-minute no-op at boot.
    """
    calls: list[int] = []

    def fake_fetch(lookback_weeks=156):
        calls.append(lookback_weeks)
        return _frames()

    monkeypatch.setenv("BETA_LOOKBACK_WEEKS", "104")
    monkeypatch.setattr(warm_cache, "fetch_factor_returns_with_history", fake_fetch)
    warm_cache.warm()
    assert calls == [104]


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


# Registry order below is deliberately NOT chronological order: `_transient_hole_events`
# must sort by start_date, and an index-order implementation would pass by accident.
_EVENT_DATES = {
    "covid-crash-2020": (date(2020, 2, 19), date(2020, 3, 23)),
    "q4-trade-war-2018": (date(2018, 10, 1), date(2018, 12, 24)),
}


def _events_registry() -> dict[str, HistoricalEvent]:
    return {
        event_id: HistoricalEvent(
            id=event_id,
            name=event_id,
            start_date=start,
            end_date=end,
            tags=(),
            description="",
        )
        for event_id, (start, end) in _EVENT_DATES.items()
    }


def _events_matrix(*, all_nan_row: bool = False, transient_hole: bool = False) -> pd.DataFrame:
    matrix = pd.DataFrame(
        -0.05,
        index=list(_EVENT_DATES),
        columns=list(FACTORS),
    )
    # Legitimate pre-launch gap: the factor is missing from the CHRONOLOGICALLY
    # FIRST window only, i.e. it is never observed before it goes absent.
    matrix.loc["q4-trade-war-2018", "GLD"] = float("nan")
    if transient_hole:
        # Provider failure: GLD traded in the 2018 window but is absent from the
        # LATER 2020 one — monotonically impossible for a real ETF.
        matrix.loc["q4-trade-war-2018", "GLD"] = -0.05
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
    monkeypatch.setattr(warm_cache, "load_events", _events_registry)


def test_event_matrix_memoized_per_events_version(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(event_ids, registry=None):
        calls["n"] += 1
        return _events_matrix()

    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", fake_fetch)
    monkeypatch.setattr(warm_cache, "load_events", _events_registry)
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
    monkeypatch.setattr(warm_cache, "load_events", _events_registry)
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
    monkeypatch.setattr(warm_cache, "load_events", _events_registry)
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


def test_transient_hole_matrix_is_served_but_never_cached(monkeypatch):
    """A factor missing from a window LATER than one it already traded in is a
    provider failure, not a pre-launch gap. Caching it would bake a rate limit
    into the 30-day parquet and thin every analog envelope built from it."""
    persistent = _PersistentMatrixCache()
    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    calls = {"n": 0}

    def fake_fetch(event_ids, registry=None):
        calls["n"] += 1
        return _events_matrix(transient_hole=calls["n"] == 1)

    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", fake_fetch)

    degraded = warm_cache.get_event_returns_matrix()
    assert bool(degraded.isna().loc["covid-crash-2020", "GLD"])
    assert persistent.put_calls == []

    healed = warm_cache.get_event_returns_matrix()
    assert calls["n"] == 2  # the poisoned result was not memoized, so this re-fetched
    assert not bool(healed.isna().loc["covid-crash-2020", "GLD"])
    assert persistent.put_calls  # only the clean matrix persists

    cached = warm_cache.get_event_returns_matrix()
    assert calls["n"] == 2
    assert cached is healed


def test_pre_launch_gap_matrix_still_caches(monkeypatch):
    """The complement of the test above: a NaN that no later observation
    contradicts is a genuine pre-launch gap and must NOT block caching."""
    persistent = _PersistentMatrixCache()
    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    monkeypatch.setattr(
        warm_cache,
        "fetch_event_returns_matrix",
        lambda event_ids, registry=None: _events_matrix(),
    )

    matrix = warm_cache.get_event_returns_matrix()
    assert bool(matrix.isna().loc["q4-trade-war-2018", "GLD"])
    assert persistent.put_calls == [warm_cache.event_matrix_cache_key()]


def test_poisoned_persistent_matrix_is_rejected_on_read_and_replaced(monkeypatch):
    """Self-healing: a blob poisoned before this gate existed would otherwise keep
    serving for the remainder of its 30-day TTL."""
    persistent = _PersistentMatrixCache()
    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    key = warm_cache.event_matrix_cache_key()
    persistent.store[key] = _events_matrix(transient_hole=True)
    healthy = _events_matrix()
    calls = {"n": 0}

    def fake_fetch(event_ids, registry=None):
        calls["n"] += 1
        return healthy

    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", fake_fetch)
    result = warm_cache.get_event_returns_matrix()

    assert calls["n"] == 1
    pd.testing.assert_frame_equal(result, healthy)
    pd.testing.assert_frame_equal(persistent.store[key], healthy)


def test_selected_event_cache_hit_enforces_registry_membership(monkeypatch):
    """Backdated runs pass an as-of-filtered registry. Serving out of the warm
    full-registry matrix must not bypass the look-ahead guard."""
    persistent = _PersistentMatrixCache()
    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    persistent.store[warm_cache.event_matrix_cache_key()] = _events_matrix()

    def unexpected_fetch(event_ids, registry=None):
        raise AssertionError("must reject before fetching")

    monkeypatch.setattr(warm_cache, "fetch_event_returns_matrix", unexpected_fetch)

    with pytest.raises(KeyError, match="unknown event_ids"):
        warm_cache.get_selected_event_returns_matrix(
            ["covid-crash-2020"],
            registry={"q4-trade-war-2018": None},
        )


def test_selected_events_preserve_requested_order_on_cache_hit(monkeypatch):
    persistent = _PersistentMatrixCache()
    _patch_event_versions(monkeypatch)
    monkeypatch.setattr(warm_cache, "get_event_matrix_cache", lambda: persistent)
    persistent.store[warm_cache.event_matrix_cache_key()] = _events_matrix()
    # Reverse of the full matrix's index order, so a plain filter would not match.
    selected = ["q4-trade-war-2018", "covid-crash-2020"]

    result = warm_cache.get_selected_event_returns_matrix(
        selected,
        registry=dict.fromkeys(selected),
    )
    assert list(result.index) == selected
