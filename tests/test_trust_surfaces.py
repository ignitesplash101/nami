from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import api
from app.data.firestore_store import InMemoryFirestoreStore
from tests.test_firestore_store import _fake_record


@pytest.fixture
def store():
    return InMemoryFirestoreStore()


@pytest.fixture
def admin_client(monkeypatch, store):
    monkeypatch.setenv("PASSCODE", "test-passcode")
    monkeypatch.setattr("app.api.main._firestore_store", store)
    c = TestClient(api)
    c.post("/api/auth/unlock", json={"passcode": "test-passcode"})
    return c


@pytest.fixture
def visitor_client(monkeypatch, store):
    monkeypatch.setenv("PASSCODE", "test-passcode")
    monkeypatch.setattr("app.api.main._firestore_store", store)
    return TestClient(api)


def _save_payload() -> dict:
    rec = _fake_record()
    return {
        "name": rec.name,
        "tags": rec.tags,
        "notes": rec.notes,
        "owner_label": rec.owner_label,
        "result": rec.result.model_dump(mode="json"),
        "analog_events_snapshot": {
            k: v.model_dump(mode="json") for k, v in rec.analog_events_snapshot.items()
        },
        "reproducibility": rec.reproducibility.model_dump(mode="json"),
        "portfolio_snapshot_ref": None,
    }


def test_audit_records_mutations_and_is_admin_only(admin_client, visitor_client):
    admin_client.post("/api/saved-scenarios", json=_save_payload())
    entries = admin_client.get("/api/audit").json()
    actions = {e["action"] for e in entries}
    assert "scenario.save" in actions
    assert "auth.unlock" in actions
    assert visitor_client.get("/api/audit").status_code == 403


def test_export_includes_snapshot_subcollections(admin_client):
    pid = admin_client.post("/api/portfolios", json={"name": "Book", "description": ""}).json()[
        "id"
    ]
    admin_client.post(
        f"/api/portfolios/{pid}/snapshots",
        json={"as_of_date": "2026-01-05", "holdings": {"AAPL": 1.0}, "notes": ""},
    )
    export = admin_client.get("/api/export").json()
    assert export["portfolios"][0]["snapshots"]
    assert export["portfolios"][0]["snapshots"][0]["holdings"] == {"AAPL": 1.0}


def test_purge_requires_confirm_token_and_is_admin_only(admin_client, visitor_client):
    admin_client.post("/api/saved-scenarios", json=_save_payload())
    assert visitor_client.post("/api/admin/purge", json={"confirm": "DELETE"}).status_code == 403
    assert admin_client.post("/api/admin/purge", json={"confirm": "nope"}).status_code == 400

    resp = admin_client.post("/api/admin/purge", json={"confirm": "DELETE"})
    assert resp.status_code == 200
    assert resp.json()["scenarios"] >= 1
    assert admin_client.get("/api/saved-scenarios").json() == []
    # Audit trail survives the purge and records the purge event.
    actions = {e["action"] for e in admin_client.get("/api/audit").json()}
    assert "admin.purge" in actions


def test_status_hides_cost_from_visitor(visitor_client, admin_client):
    pub = visitor_client.get("/api/status").json()
    assert pub["service"] == "nami"
    assert pub["disclaimer"]
    assert pub["est_cost_today_usd"] is None
    assert "llm" in pub["rate_limits"]

    adm = admin_client.get("/api/status").json()
    assert adm["est_cost_today_usd"] is not None


def test_usage_is_admin_only(visitor_client, admin_client):
    assert visitor_client.get("/api/usage").status_code == 403
    body = admin_client.get("/api/usage").json()
    assert body["cost_cap_usd"] > 0
    assert "tokens_in" in body
