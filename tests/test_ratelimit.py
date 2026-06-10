from __future__ import annotations

import contextlib

import pytest
from fastapi.testclient import TestClient

from app.api.main import api
from app.api.ratelimit import limiter
from app.data.firestore_store import InMemoryFirestoreStore


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PASSCODE", "test-passcode")
    monkeypatch.setattr("app.api.main._firestore_store", InMemoryFirestoreStore())
    return TestClient(api)


def test_unlock_is_rate_limited(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_UNLOCK", "3/minute")
    limiter.enabled = True
    with contextlib.suppress(Exception):
        limiter.reset()
    # A unique public source IP so this test's counter starts fresh.
    headers = {"X-Forwarded-For": "9.9.9.9"}
    responses = [
        client.post("/api/auth/unlock", json={"passcode": "wrong"}, headers=headers)
        for _ in range(5)
    ]
    codes = [r.status_code for r in responses]
    # First 3 reach the handler (401 wrong passcode); subsequent ones are throttled.
    assert codes[:3] == [401, 401, 401]
    assert 429 in codes[3:]
    throttled = next(r for r in responses if r.status_code == 429)
    assert throttled.headers["X-Error-Code"] == "rate_limited"


def test_health_and_static_are_not_rate_limited(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_LLM", "1/minute")
    limiter.enabled = True
    with contextlib.suppress(Exception):
        limiter.reset()
    headers = {"X-Forwarded-For": "9.9.9.10"}
    for _ in range(8):
        assert client.get("/api/health", headers=headers).status_code == 200
