"""Phase 30 long-haul reliability: SSE keepalives, stream headers, Gemini
timeout mapping, and the non-blocking startup warm."""

from __future__ import annotations

import asyncio
import queue
import time

import httpx
import pytest

from app.api import main as api_main
from app.llm.gemini_client import GeminiClient, _is_timeout_error


def _drain_frames(response) -> list[str]:
    """StreamingResponse wraps the sync generator into an async iterator."""

    async def collect() -> list[str]:
        return [chunk async for chunk in response.body_iterator]

    return asyncio.run(collect())


def test_sse_generator_emits_keepalives_during_quiet_stages(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "_SSE_HEARTBEAT_SECONDS", 0.05)
    events_q: queue.Queue = queue.Queue()
    sentinel = object()

    def worker() -> None:
        time.sleep(0.25)
        events_q.put({"stage": "market", "status": "start"})
        events_q.put(sentinel)

    response = api_main._sse_stream_response(worker, events_q, sentinel)
    frames = _drain_frames(response)

    keepalives = [f for f in frames if f == ": keepalive\n\n"]
    data_frames = [f for f in frames if f.startswith("data: ")]
    assert keepalives, "expected at least one keepalive during the quiet stage"
    assert len(data_frames) == 1 and '"stage": "market"' in data_frames[0]
    assert frames.index(keepalives[0]) < frames.index(data_frames[0])


def test_sse_stream_response_headers_and_media_type() -> None:
    events_q: queue.Queue = queue.Queue()
    sentinel = object()
    events_q.put(sentinel)

    response = api_main._sse_stream_response(lambda: None, events_q, sentinel)
    _drain_frames(response)

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


def test_is_timeout_error_variants() -> None:
    assert _is_timeout_error(TimeoutError())
    assert _is_timeout_error(httpx.ReadTimeout("deadline"))
    assert _is_timeout_error(httpx.ConnectTimeout("deadline"))
    assert not _is_timeout_error(ValueError("not a timeout"))


class _TimeoutModels:
    def generate_content(self, **_kwargs: object) -> object:
        raise httpx.ReadTimeout("deadline exceeded")


class _ValueErrorModels:
    def generate_content(self, **_kwargs: object) -> object:
        raise ValueError("schema mismatch")


class _StubClient:
    def __init__(self, models: object) -> None:
        self.models = models


def _client_with(models: object) -> GeminiClient:
    client = GeminiClient.__new__(GeminiClient)
    client._client = _StubClient(models)
    client._model = "test-model"
    return client


def test_generate_content_maps_timeout_to_runtime_error() -> None:
    client = _client_with(_TimeoutModels())
    with pytest.raises(RuntimeError, match="timed out"):
        client._generate_content(contents="x", config=None)


def test_generate_content_passes_non_timeout_errors_through() -> None:
    client = _client_with(_ValueErrorModels())
    with pytest.raises(ValueError, match="schema mismatch"):
        client._generate_content(contents="x", config=None)


def test_background_warm_swallows_provider_failures(monkeypatch) -> None:
    def boom() -> None:
        raise RuntimeError("provider down")

    monkeypatch.setattr(api_main.warm_cache, "warm", boom)
    monkeypatch.setattr(api_main.warm_cache, "get_event_returns_matrix", boom)
    api_main._background_warm()
