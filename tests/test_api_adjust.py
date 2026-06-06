"""Endpoint tests for /api/scenarios/adjust-shocks and /api/scenarios/run-stream."""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.main import api
from app.data.firestore_store import InMemoryFirestoreStore
from app.data.sample_portfolios import get_portfolio
from app.llm.schemas import (
    AnalogSelection,
    Citation,
    FactorShock,
    PortfolioPnL,
    ScenarioResult,
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PASSCODE", "test-passcode")
    monkeypatch.setattr("app.api.main._firestore_store", InMemoryFirestoreStore())
    return TestClient(api)


def _fake_result(scenario_text: str, portfolio_key: str = "us_tech_growth") -> ScenarioResult:
    portfolio = get_portfolio(portfolio_key)
    first_ticker = portfolio.tickers[0]
    return ScenarioResult(
        scenario_text=scenario_text,
        market_date=date(2026, 5, 25),
        portfolio_key=portfolio_key,
        portfolio_name=portfolio.name,
        portfolio_holdings=dict(portfolio.holdings),
        analogs_selected=[
            AnalogSelection(event_id="q4-trade-war-2018", why_relevant="trade stress")
        ],
        factor_shocks=[FactorShock(factor="SPY", shock=-0.05, reasoning="risk-off")],
        periphery_shocks=[],
        narrative="A concise mocked narrative.",
        citations=[Citation(url="https://example.com", title="Example")],
        factor_envelope={"SPY": {"mean": -0.02, "p10": -0.1, "p90": 0.05, "count": 3}},
        portfolio_pnl=PortfolioPnL(
            total_pnl=-0.01,
            by_factor_naive={"SPY": -0.01},
            by_ticker_factor={
                ticker: (-0.01 if ticker == first_ticker else 0.0) for ticker in portfolio.tickers
            },
            by_ticker_periphery=dict.fromkeys(portfolio.tickers, 0.0),
            by_ticker_total={
                ticker: (-0.01 if ticker == first_ticker else 0.0) for ticker in portfolio.tickers
            },
        ),
    )


def test_adjust_shocks_requires_admin(client):
    response = client.post(
        "/api/scenarios/adjust-shocks",
        json={"cache_key": "abc", "overrides": {"SPY": 0.0}},
    )
    assert response.status_code == 403


def test_adjust_shocks_rejects_both_args(client):
    client.post("/api/auth/unlock", json={"passcode": "test-passcode"})
    response = client.post(
        "/api/scenarios/adjust-shocks",
        json={
            "cache_key": "abc",
            "overrides": {"SPY": 0.0},
            "adjustment_text": "remove SPY",
        },
    )
    assert response.status_code == 400


def test_adjust_shocks_rejects_neither_arg(client):
    client.post("/api/auth/unlock", json={"passcode": "test-passcode"})
    response = client.post(
        "/api/scenarios/adjust-shocks",
        json={"cache_key": "abc"},
    )
    assert response.status_code == 400


def test_adjust_shocks_returns_410_on_expired_key(client, monkeypatch):
    client.post("/api/auth/unlock", json={"passcode": "test-passcode"})

    def _raise_lookup(*args, **kwargs):
        raise LookupError("Scenario result not found for cache_key='gone'.")

    monkeypatch.setattr("app.api.main.adjust_scenario_shocks", _raise_lookup)

    response = client.post(
        "/api/scenarios/adjust-shocks",
        json={"cache_key": "gone", "overrides": {"SPY": 0.0}},
    )
    assert response.status_code == 410


def test_adjust_shocks_returns_422_on_rerun_required(client, monkeypatch):
    client.post("/api/auth/unlock", json={"passcode": "test-passcode"})

    def _raise_rerun(*args, **kwargs):
        raise RuntimeError("That asks for a new mechanism not in the analogs.")

    monkeypatch.setattr("app.api.main.adjust_scenario_shocks", _raise_rerun)

    response = client.post(
        "/api/scenarios/adjust-shocks",
        json={"cache_key": "abc", "adjustment_text": "add oil shock"},
    )
    assert response.status_code == 422
    assert "new mechanism" in response.json()["detail"]


def test_adjust_shocks_returns_400_on_validation_error(client, monkeypatch):
    client.post("/api/auth/unlock", json={"passcode": "test-passcode"})

    def _raise_validation(*args, **kwargs):
        raise ValueError("Override is missing factors that exist in the canonical scenario.")

    monkeypatch.setattr("app.api.main.adjust_scenario_shocks", _raise_validation)

    response = client.post(
        "/api/scenarios/adjust-shocks",
        json={"cache_key": "abc", "overrides": {"SPY": 0.0}},
    )
    assert response.status_code == 400


def test_adjust_shocks_happy_path_returns_envelope(client, monkeypatch):
    client.post("/api/auth/unlock", json={"passcode": "test-passcode"})

    fake_result = _fake_result("scenario")

    def _fake_adjust(cache_key, **kwargs):
        assert cache_key == "abc"
        return fake_result

    monkeypatch.setattr("app.api.main.adjust_scenario_shocks", _fake_adjust)

    response = client.post(
        "/api/scenarios/adjust-shocks",
        json={"cache_key": "abc", "overrides": {"SPY": 0.0}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cache_key"] == "abc"
    assert body["result"]["narrative"] == "A concise mocked narrative."


def test_run_endpoint_returns_cache_key(client, monkeypatch):
    def _fake_run_scenario(scenario_text, portfolio, **kwargs):
        return _fake_result(scenario_text)

    monkeypatch.setattr("app.api.main.run_scenario", _fake_run_scenario)
    monkeypatch.setattr(
        "app.api.main.compute_scenario_cache_key", lambda *a, **kw: "deterministic-key"
    )

    response = client.post(
        "/api/scenarios/run",
        json={"sample_scenario_key": "china_tariffs", "portfolio_key": "us_tech_growth"},
    )
    assert response.status_code == 200
    assert response.json()["cache_key"] == "deterministic-key"


def _parse_sse(body: str) -> list[dict]:
    events = []
    for frame in body.split("\n\n"):
        line = next((line for line in frame.splitlines() if line.startswith("data: ")), None)
        if line:
            events.append(json.loads(line[len("data: ") :]))
    return events


def test_run_stream_emits_progress_then_done(client, monkeypatch):
    fake_result = _fake_result("scenario")

    def _fake_run_scenario(scenario_text, portfolio, *, progress=None, **kwargs):
        if progress is not None:
            progress("analogs", "start")
            progress("analogs", "done")
            progress("attribution", "start")
            progress("attribution", "done")
        return fake_result

    monkeypatch.setattr("app.api.main.run_scenario", _fake_run_scenario)
    monkeypatch.setattr("app.api.main.compute_scenario_cache_key", lambda *a, **kw: "key")

    response = client.post(
        "/api/scenarios/run-stream",
        json={"sample_scenario_key": "china_tariffs", "portfolio_key": "us_tech_growth"},
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    stages = [e["stage"] for e in events]
    assert "analogs" in stages
    assert "attribution" in stages
    assert stages[-1] == "done"
    assert events[-1]["result"]["cache_key"] == "key"


def test_run_stream_cache_hit_emits_cache_hit_then_done(client, monkeypatch):
    fake_result = _fake_result("scenario")

    def _fake_run_scenario(scenario_text, portfolio, *, progress=None, **kwargs):
        if progress is not None:
            progress("cache_hit", "done")
        return fake_result

    monkeypatch.setattr("app.api.main.run_scenario", _fake_run_scenario)
    monkeypatch.setattr("app.api.main.compute_scenario_cache_key", lambda *a, **kw: "key")

    response = client.post(
        "/api/scenarios/run-stream",
        json={"sample_scenario_key": "china_tariffs", "portfolio_key": "us_tech_growth"},
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    stages = [e["stage"] for e in events]
    assert stages == ["cache_hit", "done"]


def test_run_stream_emits_error_event_on_exception(client, monkeypatch):
    def _fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.api.main.run_scenario", _fail)
    monkeypatch.setattr("app.api.main.compute_scenario_cache_key", lambda *a, **kw: "key")

    response = client.post(
        "/api/scenarios/run-stream",
        json={"sample_scenario_key": "china_tariffs", "portfolio_key": "us_tech_growth"},
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[-1]["stage"] == "error"
    assert "boom" in events[-1]["message"]
