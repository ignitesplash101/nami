"""X-Error-Code contract tests.

The header (and the SSE `code` field) is the machine-readable error channel;
detail strings stay display-only. These tests pin the coded raise sites so a
refactor can't silently drop a code the frontend dispatches on.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.errors import ERROR_CODE_HEADER
from app.api.main import api
from app.data.firestore_store import InMemoryFirestoreStore
from app.data.marking import MarkingError
from app.data.sample_portfolios import get_portfolio
from app.llm.schemas import (
    AnalogSelection,
    Citation,
    FactorShock,
    PortfolioPnL,
    ScenarioResult,
)
from app.observability.metering import BudgetExceededError


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PASSCODE", "test-passcode")
    monkeypatch.setattr("app.api.main._firestore_store", InMemoryFirestoreStore())
    return TestClient(api)


@pytest.fixture
def admin_client(client):
    client.post("/api/auth/unlock", json={"passcode": "test-passcode"})
    return client


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


_RUN_BODY = {"scenario_text": "Custom visitor stress", "portfolio_key": "us_tech_growth"}


def test_run_cap_429_carries_run_cap_code(client, monkeypatch):
    monkeypatch.setenv("DAILY_LLM_RUN_CAP", "0")
    response = client.post("/api/scenarios/run", json=_RUN_BODY)
    assert response.status_code == 429
    assert response.headers[ERROR_CODE_HEADER] == "run_cap"
    assert response.json()["detail"] == "Daily scenario run cap reached; try again tomorrow."


def test_budget_429_carries_budget_code(client, monkeypatch):
    def _raise_budget(*args, **kwargs):
        raise BudgetExceededError("Daily LLM budget cap reached; try again tomorrow.")

    monkeypatch.setattr("app.api.main.run_scenario", _raise_budget)
    response = client.post("/api/scenarios/run", json=_RUN_BODY)
    assert response.status_code == 429
    assert response.headers[ERROR_CODE_HEADER] == "budget_exhausted"
    assert response.json()["detail"] == "Daily LLM budget cap reached; try again tomorrow."


def test_marking_503_carries_code(client, monkeypatch):
    def _raise_marking(*args, **kwargs):
        raise MarkingError("No usable close for 7203.T on or before 2026-05-25.")

    monkeypatch.setattr("app.api.main.run_scenario", _raise_marking)
    response = client.post("/api/scenarios/run", json=_RUN_BODY)
    assert response.status_code == 503
    assert response.headers[ERROR_CODE_HEADER] == "marking_unavailable"


def test_adjust_rerun_required_carries_code(admin_client, monkeypatch):
    # The detail deliberately does NOT contain the word "rerun" — the rejection
    # reason is LLM free text, so only the header can classify it reliably.
    def _raise_rerun(*args, **kwargs):
        raise RuntimeError("That asks for a new transmission mechanism.")

    monkeypatch.setattr("app.api.main.adjust_scenario_shocks", _raise_rerun)
    response = admin_client.post(
        "/api/scenarios/adjust-shocks",
        json={"cache_key": "abc", "adjustment_text": "add an oil shock"},
    )
    assert response.status_code == 422
    assert response.headers[ERROR_CODE_HEADER] == "rerun_required"
    assert "rerun" not in response.json()["detail"].lower()


def test_unlock_lockout_429_carries_rate_limited_code(client, monkeypatch):
    monkeypatch.setenv("UNLOCK_MAX_FAILURES", "1")
    assert client.post("/api/auth/unlock", json={"passcode": "wrong"}).status_code == 401
    locked = client.post("/api/auth/unlock", json={"passcode": "wrong"})
    assert locked.status_code == 429
    assert locked.headers[ERROR_CODE_HEADER] == "rate_limited"


def test_sse_error_event_carries_code(client, monkeypatch):
    def _raise_marking(*args, **kwargs):
        raise MarkingError("FX rate unavailable for JPY.")

    monkeypatch.setattr("app.api.main.run_scenario", _raise_marking)
    response = client.post("/api/scenarios/run-stream", json=_RUN_BODY)
    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    error_events = [event for event in events if event.get("stage") == "error"]
    assert error_events, f"no error event in stream: {events}"
    assert error_events[0]["code"] == "marking_unavailable"
    assert error_events[0]["message"] == "FX rate unavailable for JPY."


def test_decompose_budget_exceeded_mid_compute_is_429(admin_client, monkeypatch):
    # The metered client raises DURING the 2^N subset calls — the endpoint must
    # map that to a coded 429, not let it escape as a 500.
    def _raise_budget(*args, **kwargs):
        raise BudgetExceededError("Daily LLM budget cap reached; try again tomorrow.")

    # The endpoint constructs CloudStorageCache (eager storage.Client) before the
    # compute call — stub it; the mocked compute never touches the caches.
    monkeypatch.setattr("app.api.main.CloudStorageCache", lambda *a, **kw: object())
    monkeypatch.setattr("app.api.main.compute_narrative_shapley", _raise_budget)
    response = admin_client.post(
        "/api/scenarios/decompose",
        json={"result": _fake_result("decompose me").model_dump(mode="json")},
    )
    assert response.status_code == 429
    assert response.headers[ERROR_CODE_HEADER] == "budget_exhausted"
