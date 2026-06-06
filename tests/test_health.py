from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import api
from app.data.firestore_store import InMemoryFirestoreStore


@pytest.fixture
def client():
    return TestClient(api)


def test_health_is_always_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_returns_200_when_all_checks_pass(client, monkeypatch):
    monkeypatch.setattr("app.api.main._firestore_store", InMemoryFirestoreStore())
    monkeypatch.setattr(main, "_check_gcs", lambda config: None)
    monkeypatch.setattr(main, "_check_gemini", lambda config: None)
    resp = client.get("/api/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["checks"] == {"firestore": "ok", "gcs": "ok", "gemini": "ok"}


def test_ready_returns_503_when_a_dependency_fails(client, monkeypatch):
    monkeypatch.setattr("app.api.main._firestore_store", InMemoryFirestoreStore())
    monkeypatch.setattr(main, "_check_gcs", lambda config: None)

    def _boom(config):
        raise RuntimeError("vertex down")

    monkeypatch.setattr(main, "_check_gemini", _boom)
    resp = client.get("/api/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ready"] is False
    assert body["checks"]["gemini"] == "unavailable"
    assert body["checks"]["firestore"] == "ok"
