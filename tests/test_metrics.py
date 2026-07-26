"""Usage-metrics aggregation — pure, no network, no Cloud Logging client.

The aggregator is the whole feature: the endpoint is a thin shell around it. These
tests pin the properties that matter for correctness AND for privacy — most
importantly that no `ip_hash` value ever reaches the response payload.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.main import api
from app.data.firestore_store import InMemoryFirestoreStore
from app.observability.metrics import (
    MAX_LOG_ENTRIES,
    LogEntry,
    aggregate,
    log_filter,
    parse_entry,
)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("PASSCODE", "test-passcode")
    monkeypatch.setattr("app.api.main._firestore_store", InMemoryFirestoreStore())
    return TestClient(api)


@pytest.fixture
def admin_client(client: TestClient) -> TestClient:
    client.post("/api/auth/unlock", json={"passcode": "test-passcode"})
    return client


def _entry(**overrides) -> LogEntry:
    base = {
        "day": "2026-07-26",
        "path": "/api/scenarios/run",
        "status": 200,
        "latency_ms": 100.0,
        "ip_hash": "aaaa",
    }
    base.update(overrides)
    return LogEntry(**base)


def test_unique_visitors_are_distinct_across_the_window_not_summed():
    """One visitor returning on three days is ONE unique visitor overall.

    Summing the per-day figures would triple-count them, which is the classic way
    a traffic dashboard flatters itself.
    """
    entries = [
        _entry(day="2026-07-24", ip_hash="same"),
        _entry(day="2026-07-25", ip_hash="same"),
        _entry(day="2026-07-26", ip_hash="same"),
        _entry(day="2026-07-26", ip_hash="other"),
    ]
    window = aggregate(entries, days=7, include_synthetic=False)

    assert [d["unique_visitors"] for d in window.daily] == [1, 1, 2]
    assert window.totals["unique_visitors"] == 2
    assert window.totals["requests"] == 4


def test_response_never_contains_an_ip_hash():
    """ip_hash is a cardinality input only — it must not leave the server.

    The salt is a static, non-secret constant over a 32-bit IPv4 space, so the hash
    is pseudonymous rather than anonymous; shipping it to a client would be a real
    disclosure, not a cosmetic one.
    """
    entries = [_entry(ip_hash="deadbeefdeadbeef"), _entry(ip_hash="cafebabecafebabe")]
    window = aggregate(entries, days=7, include_synthetic=False)

    payload = json.dumps(asdict(window))
    assert "deadbeef" not in payload
    assert "cafebabe" not in payload
    assert window.totals["unique_visitors"] == 2


def test_synthetic_prewarm_traffic_is_excluded_but_disclosed():
    """The scheduled warm makes ~16 machine runs every weekday. Excluding it is
    right; hiding that it was excluded is not."""
    entries = [_entry(ip_hash="real"), *[_entry(ip_hash="bot", synthetic=True) for _ in range(16)]]

    excluded = aggregate(entries, days=7, include_synthetic=False)
    assert excluded.totals["requests"] == 1
    assert excluded.totals["unique_visitors"] == 1
    assert excluded.synthetic_excluded == 16

    included = aggregate(entries, days=7, include_synthetic=True)
    assert included.totals["requests"] == 17
    assert included.synthetic_excluded == 0


def test_feature_usage_counts_scenarios_books_and_mode():
    entries = [
        _entry(scenario_key="covid_pandemic", portfolio_key="msci_world", access_mode="visitor"),
        _entry(scenario_key="covid_pandemic", portfolio_key="japan_equity", access_mode="visitor"),
        _entry(scenario_key="china_tariffs", portfolio_key="msci_world", access_mode="admin"),
        # Not a run path — must not pollute the feature-usage tallies.
        _entry(path="/api/access", scenario_key="ignored"),
    ]
    window = aggregate(entries, days=7, include_synthetic=False)

    assert window.scenario_runs[0] == {"key": "covid_pandemic", "runs": 2}
    assert {r["key"] for r in window.portfolio_runs} == {"msci_world", "japan_equity"}
    assert window.totals["visitor_runs"] == 2
    assert window.totals["admin_runs"] == 1
    assert window.totals["runs"] == 3


def test_cache_hit_rate_uses_observed_runs_as_the_denominator():
    entries = [
        _entry(cache_hit=True),
        _entry(cache_hit=True),
        _entry(cache_hit=False),
        # Older lines predate the tag; they must not count either way.
        _entry(cache_hit=None),
    ]
    window = aggregate(entries, days=7, include_synthetic=False)

    assert window.totals["cache_observed"] == 3
    assert window.totals["cache_hits"] == 2
    assert window.totals["cache_hit_rate"] == round(2 / 3, 4)


def test_latency_excludes_the_sse_paths_that_log_time_to_first_byte():
    """`/run-stream` logs when headers are sent, not when the ~50s run finishes.

    Including it would report a fast lie, so it is excluded — and the exclusion is
    named in the payload rather than left implicit.
    """
    entries = [
        _entry(path="/api/scenarios/run", latency_ms=1000.0),
        _entry(path="/api/scenarios/run-stream", latency_ms=3.0),
    ]
    window = aggregate(entries, days=7, include_synthetic=False)

    assert window.totals["latency_p50_ms"] == 1000.0
    assert "/api/scenarios/run-stream" in window.totals["latency_excluded_paths"]


def test_errors_are_counted_by_path_and_status():
    entries = [
        _entry(status=200),
        _entry(status=429),
        _entry(status=429),
        _entry(path="/api/scenarios/adjust-shocks", status=503),
    ]
    window = aggregate(entries, days=7, include_synthetic=False)

    assert window.totals["errors"] == 3
    assert window.status_counts == {"200": 1, "429": 2, "503": 1}
    assert window.top_errors[0] == {"path": "/api/scenarios/run", "status": 429, "count": 2}


def test_truncation_is_disclosed():
    """A capped window must never read as a complete one."""
    small = aggregate([_entry()], days=7, include_synthetic=False)
    assert small.truncated is False

    capped = aggregate([_entry() for _ in range(MAX_LOG_ENTRIES)], days=7, include_synthetic=False)
    assert capped.truncated is True


def test_parse_entry_tolerates_lines_predating_the_tags():
    """Lines logged before this feature shipped still count toward traffic."""
    entry = parse_entry(
        {
            "message": "request",
            "path": "/api/access",
            "status": 200,
            "latency_ms": 4.2,
            "ip_hash": "abc",
        },
        datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
    )
    assert entry is not None
    assert entry.day == "2026-07-26"
    assert entry.scenario_key is None
    assert entry.cache_hit is None
    assert entry.synthetic is False


def test_parse_entry_rejects_non_access_lines():
    assert parse_entry({"message": "gemini call shape=structured", "path": None}, None) is None
    assert parse_entry({"message": "request"}, None) is None


def test_log_filter_uses_an_rfc3339_literal_not_relative_syntax():
    """The Logging API has no relative-time filter syntax — that's a gcloud flag."""
    built = log_filter(7, now=datetime(2026, 7, 26, 12, 0, tzinfo=UTC))
    assert 'timestamp>="2026-07-19T12:00:00Z"' in built
    assert 'jsonPayload.logger="nami.access"' in built


def test_metrics_endpoint_is_admin_only(client):
    """Usage metrics are operator data, not public."""
    assert client.get("/api/metrics").status_code == 403


def test_metrics_endpoint_degrades_when_logs_are_unavailable(admin_client, monkeypatch):
    """A missing roles/logging.viewer must dim ONE panel, not kill the console.

    The cost/quota half comes from Firestore and has to keep rendering.
    """

    def _denied(*args, **kwargs):
        raise PermissionError("caller lacks roles/logging.viewer")

    monkeypatch.setattr("app.api.main.fetch_access_entries", _denied)
    response = admin_client.get("/api/metrics?days=3")

    assert response.status_code == 200
    body = response.json()
    assert body["logs_available"] is False
    assert "logging.viewer" in body["logs_error"]
    assert len(body["cost_daily"]) == 3  # Firestore side still populated
    assert body["days"] == 3


def test_metrics_endpoint_aggregates_and_clamps_the_window(admin_client, monkeypatch):
    entries = [
        LogEntry(
            day="2026-07-26",
            path="/api/scenarios/run",
            status=200,
            latency_ms=50.0,
            ip_hash="visitor-one",
            access_mode="visitor",
            scenario_key="covid_pandemic",
            portfolio_key="msci_world",
            cache_hit=True,
        )
    ]
    monkeypatch.setattr("app.api.main.fetch_access_entries", lambda *a, **k: entries)

    # 999 days is beyond log retention and must be clamped, not silently honored.
    response = admin_client.get("/api/metrics?days=999")
    body = response.json()

    assert response.status_code == 200
    assert body["days"] == body["log_retention_days"] == 30
    assert body["logs_available"] is True
    assert body["scenario_runs"] == [{"key": "covid_pandemic", "runs": 1}]
    assert body["totals"]["visitor_runs"] == 1
    assert "visitor-one" not in response.text  # ip_hash never leaves the server
