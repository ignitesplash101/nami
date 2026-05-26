"""Endpoint tests for /api/saved-scenarios and /api/portfolios.

Uses the InMemoryFirestoreStore via monkeypatch of the module-level singleton.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.main import api
from app.data.firestore_store import InMemoryFirestoreStore
from tests.test_firestore_store import _fake_record


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PASSCODE", "test-passcode")
    store = InMemoryFirestoreStore()
    monkeypatch.setattr("app.api.main._firestore_store", store)
    c = TestClient(api)
    c.post("/api/auth/unlock", json={"passcode": "test-passcode"})
    return c


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


def test_save_and_get_roundtrip(client):
    resp = client.post("/api/saved-scenarios", json=_save_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    sid = body["id"]
    assert sid

    # Inline-holdings + inline-analog-events invariant.
    assert body["portfolio_holdings"] == {"AAPL": 0.6, "MSFT": 0.4}
    assert "evt" in body["analog_events_snapshot"]

    # Get by id round-trips.
    got = client.get(f"/api/saved-scenarios/{sid}")
    assert got.status_code == 200
    assert got.json()["name"] == "Pandemic stress 2024-06-28"


def test_list_with_tag_filter(client):
    client.post("/api/saved-scenarios", json=_save_payload())
    payload = _save_payload()
    payload["name"] = "Different one"
    payload["tags"] = ["other"]
    client.post("/api/saved-scenarios", json=payload)

    all_resp = client.get("/api/saved-scenarios")
    assert all_resp.status_code == 200
    assert len(all_resp.json()) == 2

    filtered = client.get("/api/saved-scenarios?tag=other")
    assert filtered.status_code == 200
    names = [item["name"] for item in filtered.json()]
    assert names == ["Different one"]


def test_delete_removes_record(client):
    sid = client.post("/api/saved-scenarios", json=_save_payload()).json()["id"]
    del_resp = client.delete(f"/api/saved-scenarios/{sid}")
    assert del_resp.status_code == 204
    not_found = client.get(f"/api/saved-scenarios/{sid}")
    assert not_found.status_code == 404


def test_json_download_endpoint_sets_filename(client):
    sid = client.post("/api/saved-scenarios", json=_save_payload()).json()["id"]
    dl = client.get(f"/api/saved-scenarios/{sid}/json")
    assert dl.status_code == 200
    assert "attachment" in dl.headers["content-disposition"]
    assert sid in dl.headers["content-disposition"]


def test_save_requires_admin(monkeypatch):
    """Without unlocking, the save endpoint must return 403."""
    monkeypatch.setenv("PASSCODE", "test-passcode")
    store = InMemoryFirestoreStore()
    monkeypatch.setattr("app.api.main._firestore_store", store)
    raw = TestClient(api)  # NOT unlocked
    resp = raw.post("/api/saved-scenarios", json=_save_payload())
    assert resp.status_code == 403


def test_portfolio_snapshot_lifecycle(client):
    create = client.post(
        "/api/portfolios",
        json={"name": "Active book", "description": "Main", "owner_label": "rs"},
    )
    assert create.status_code == 200
    pid = create.json()["id"]

    snap = client.post(
        f"/api/portfolios/{pid}/snapshots",
        json={
            "as_of_date": "2024-06-28",
            "holdings": {"AAPL": 0.5, "MSFT": 0.5},
            "notes": "Q2",
            "owner_label": "rs",
        },
    )
    assert snap.status_code == 200, snap.text
    sid = snap.json()["id"]

    listing = client.get(f"/api/portfolios/{pid}/snapshots")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    one = client.get(f"/api/portfolios/{pid}/snapshots/{sid}")
    assert one.status_code == 200
    assert one.json()["holdings"] == {"AAPL": 0.5, "MSFT": 0.5}


def test_future_dated_snapshot_rejected(client):
    pid = client.post("/api/portfolios", json={"name": "Active book"}).json()["id"]
    # 2099-01-01 is reliably future.
    snap = client.post(
        f"/api/portfolios/{pid}/snapshots",
        json={"as_of_date": "2099-01-01", "holdings": {"AAPL": 1.0}, "notes": ""},
    )
    assert snap.status_code == 422
    assert "future" in snap.json()["detail"].lower()


def test_backdated_scenario_run_includes_reproducibility(client, monkeypatch):
    """Wire-level: /api/scenarios/run with as_of_date returns reproducibility
    metadata indicating analog-only narrative mode."""
    from tests.test_api import _fake_result

    def _fake_run_scenario(scenario_text, portfolio, *, market_date=None, **kwargs):
        # Mock returns a result keyed to the requested market_date.
        result = _fake_result(scenario_text)
        # Override fields the endpoint reads.
        return result.model_copy(
            update={
                "market_date": market_date or date.today(),
                "requested_as_of_date": market_date or date.today(),
                "narrative_mode": (
                    "analog_only" if market_date and market_date < date.today() else "grounded"
                ),
                "selected_event_ids": ["evt"],
            }
        )

    monkeypatch.setattr("app.api.main.run_scenario", _fake_run_scenario)
    monkeypatch.setattr("app.api.main.compute_scenario_cache_key", lambda *a, **kw: "test-key")

    resp = client.post(
        "/api/scenarios/run",
        json={
            "sample_scenario_key": "china_tariffs",
            "portfolio_key": "us_tech_growth",
            "as_of_date": "2020-06-01",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    repro = body["reproducibility"]
    assert repro is not None
    assert repro["narrative_mode"] == "analog_only"
    assert repro["requested_as_of_date"] == "2020-06-01"
    assert repro["selected_event_ids"] == ["evt"]
