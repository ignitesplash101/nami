from __future__ import annotations

import threading

import pytest

from app.config import Config
from app.data.firestore_store import InMemoryFirestoreStore
from app.llm.gemini_client import GeminiClient, call_shape, usage_tokens
from app.observability.metering import (
    BudgetExceededError,
    MeteredGeminiClient,
    RunTelemetry,
    cost_usd,
    enforce_run_cap,
)

DAY = "2026-06-06"


def _config(**overrides) -> Config:
    base = {
        "google_cloud_project": "x",
        "vertex_ai_location": "global",
        "gcs_bucket": "x",
    }
    base.update(overrides)
    return Config(**base)


class _FakeResponse:
    def __init__(self, tokens_in: int, tokens_out: int) -> None:
        self.usage_metadata = type(
            "U",
            (),
            {"prompt_token_count": tokens_in, "candidates_token_count": tokens_out},
        )()


def _metered(store, monkeypatch, *, response=None, raises=None, cap=25.0):
    client = MeteredGeminiClient(
        _config(daily_llm_cost_cap_usd=cap),
        store=store,
        telemetry=RunTelemetry(),
        day=DAY,
    )

    def _base(self, *, contents, config):  # noqa: ANN001
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(GeminiClient, "_generate_content", _base)
    return client


def test_usage_tokens_reports_thinking_as_a_component_of_output():
    """Thinking is INSIDE tokens_out (Google bills both at the output rate) and is
    surfaced separately only so it can be attributed — never added on top."""
    response = _FakeResponse(1000, 200)
    response.usage_metadata.thoughts_token_count = 300
    assert usage_tokens(response) == (1000, 500, 300)


def test_usage_tokens_tolerates_a_response_without_metadata():
    assert usage_tokens(object()) == (0, 0, 0)


@pytest.mark.parametrize(
    ("tools", "schema", "expected"),
    [
        ([object()], None, "grounded"),
        ([object()], object(), "grounded"),  # tools win: grounding is the cost driver
        (None, object(), "structured"),
        (None, None, "plain"),
    ],
)
def test_call_shape_classifies_by_request_config(tools, schema, expected):
    config = type("Cfg", (), {"tools": tools, "response_schema": schema})()
    assert call_shape(config) == expected


def test_cost_usd_uses_config_prices():
    cfg = _config(price_input_per_mtok=1.0, price_output_per_mtok=2.0)
    assert cost_usd(1_000_000, 500_000, cfg) == pytest.approx(2.0)


def test_telemetry_accumulates():
    t = RunTelemetry()
    t.record(tokens_in=10, tokens_out=5, cost=0.1)
    t.record(tokens_in=20, tokens_out=5, cost=0.2)
    assert t.calls == 2
    assert t.tokens_in == 30
    assert t.est_cost_usd == pytest.approx(0.3)


def test_fanout_meters_every_call(monkeypatch):
    store = InMemoryFirestoreStore()
    client = _metered(store, monkeypatch, response=_FakeResponse(1000, 200))
    for _ in range(5):
        client._generate_content(contents="x", config=None)
    assert client._telemetry.calls == 5
    usage = store.usage_daily(DAY)
    assert usage["calls"] == 5
    assert usage["spent"] > 0


def test_thinking_tokens_book_at_output_rate(monkeypatch):
    store = InMemoryFirestoreStore()
    response = _FakeResponse(1000, 200)
    response.usage_metadata.thoughts_token_count = 300
    client = _metered(store, monkeypatch, response=response)
    client._generate_content(contents="x", config=None)
    # 200 response + 300 thinking tokens — Google bills both at the output rate.
    assert client._telemetry.tokens_in == 1000
    assert client._telemetry.tokens_out == 500
    assert store.usage_daily(DAY)["tokens_out"] == 500


def test_budget_cap_blocks_call(monkeypatch):
    store = InMemoryFirestoreStore()
    # Pre-spend right up to a tiny cap so the next reservation cannot fit.
    store.settle_budget(DAY, reserved=0.0, actual=1.0, tokens_in=0, tokens_out=0)
    client = _metered(store, monkeypatch, response=_FakeResponse(10, 10), cap=0.5)
    with pytest.raises(BudgetExceededError):
        client._generate_content(contents="x", config=None)


def test_failure_books_estimate_conservatively(monkeypatch):
    store = InMemoryFirestoreStore()
    client = _metered(store, monkeypatch, raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        client._generate_content(contents="x", config=None)
    # Failed call still counts (conservative reconcile) so it can't escape the cap.
    assert client._telemetry.calls == 1
    assert store.usage_daily(DAY)["spent"] > 0


def test_concurrent_reserves_cannot_exceed_cap():
    store = InMemoryFirestoreStore()
    cap = 1.0
    granted = []

    def worker():
        granted.append(store.reserve_budget(DAY, 0.4, cap=cap))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 0.4 * n <= 1.0 -> at most 2 reservations succeed.
    assert sum(1 for g in granted if g) == 2
    assert store.usage_daily(DAY)["reserved"] == pytest.approx(0.8)


def test_enforce_run_cap_raises_past_cap():
    """Check-then-charge: the gate reads the counter, the metered client books it.

    Exactly `cap` paid runs must still be admitted, as under the old
    increment-then-compare form.
    """
    store = InMemoryFirestoreStore()
    cfg = _config(daily_llm_run_cap=2)
    enforce_run_cap(store, cfg, DAY)
    store.increment_daily_run(DAY)
    enforce_run_cap(store, cfg, DAY)
    store.increment_daily_run(DAY)
    with pytest.raises(BudgetExceededError):
        enforce_run_cap(store, cfg, DAY)


def test_enforce_run_cap_does_not_book_a_run():
    """A cache hit calls the gate and no model call — it must stay free.

    Counting endpoint hits made the cap throttle free cached traffic while the
    cost breaker, not this, is what actually bounds spend."""
    store = InMemoryFirestoreStore()
    cfg = _config(daily_llm_run_cap=2)
    for _ in range(5):
        enforce_run_cap(store, cfg, DAY)
    assert store.usage_daily(DAY).get("runs", 0) == 0


def test_paid_call_books_exactly_one_run_per_request(monkeypatch):
    """Internal fan-out (retries, 2^N decomposition subsets) is still ONE run."""
    store = InMemoryFirestoreStore()
    client = _metered(store, monkeypatch, response=_FakeResponse(10, 5))
    client._generate_content(contents="x", config=None)
    client._generate_content(contents="x", config=None)
    client._generate_content(contents="x", config=None)
    assert store.usage_daily(DAY)["runs"] == 1
    assert store.usage_daily(DAY)["calls"] == 3


def test_budget_blocked_request_books_no_run(monkeypatch):
    store = InMemoryFirestoreStore()
    # Pre-spend right up to a tiny cap so the next reservation cannot fit.
    store.settle_budget(DAY, reserved=0.0, actual=1.0, tokens_in=0, tokens_out=0)
    client = _metered(store, monkeypatch, response=_FakeResponse(10, 5), cap=0.5)
    with pytest.raises(BudgetExceededError):
        client._generate_content(contents="x", config=None)
    assert store.usage_daily(DAY).get("runs", 0) == 0


def test_unlock_lockout_counter_windows_and_clears():
    store = InMemoryFirestoreStore()
    assert store.unlock_failure_count("ip1", window_seconds=900) == 0
    assert store.record_failed_unlock("ip1", window_seconds=900) == 1
    assert store.record_failed_unlock("ip1", window_seconds=900) == 2
    assert store.unlock_failure_count("ip1", window_seconds=900) == 2
    store.clear_unlock_failures("ip1")
    assert store.unlock_failure_count("ip1", window_seconds=900) == 0
