from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.main import api
from app.data.firestore_store import InMemoryFirestoreStore
from app.data.sample_portfolios import get_portfolio
from app.factors.regression import InsufficientHistoryError
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
            by_factor_conditional_shapley={"SPY": -0.01},
            by_ticker_factor={
                ticker: (-0.01 if ticker == first_ticker else 0.0) for ticker in portfolio.tickers
            },
            by_ticker_periphery=dict.fromkeys(portfolio.tickers, 0.0),
            by_ticker_total={
                ticker: (-0.01 if ticker == first_ticker else 0.0) for ticker in portfolio.tickers
            },
        ),
    )


def test_access_unlock_and_lock(client):
    assert client.get("/api/access").json()["access_mode"] == "visitor"

    bad = client.post("/api/auth/unlock", json={"passcode": "wrong"})
    assert bad.status_code == 401

    good = client.post("/api/auth/unlock", json={"passcode": "test-passcode"})
    assert good.status_code == 200
    assert good.json()["access_mode"] == "admin"
    assert client.get("/api/access").json()["access_mode"] == "admin"

    locked = client.post("/api/auth/lock")
    assert locked.status_code == 200
    assert client.get("/api/access").json()["access_mode"] == "visitor"


def test_unlock_brute_force_lockout(client, monkeypatch):
    monkeypatch.setenv("UNLOCK_MAX_FAILURES", "2")
    assert client.post("/api/auth/unlock", json={"passcode": "wrong"}).status_code == 401
    assert client.post("/api/auth/unlock", json={"passcode": "wrong"}).status_code == 401
    # Locked after MAX failures — even the correct passcode is refused with 429.
    assert client.post("/api/auth/unlock", json={"passcode": "wrong"}).status_code == 429
    assert client.post("/api/auth/unlock", json={"passcode": "test-passcode"}).status_code == 429


def test_visitor_can_run_custom_text_on_sample_portfolio(client, monkeypatch):
    def _fake_run_scenario(scenario_text, portfolio, **kwargs):
        assert scenario_text == "Custom visitor stress"
        assert portfolio == "us_tech_growth"
        return _fake_result(scenario_text)

    monkeypatch.setattr("app.api.main.run_scenario", _fake_run_scenario)

    response = client.post(
        "/api/scenarios/run",
        json={
            "scenario_text": "Custom visitor stress",
            "portfolio_key": "us_tech_growth",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["scenario_text"] == "Custom visitor stress"


def test_run_maps_insufficient_history_to_422(client, monkeypatch):
    """InsufficientHistoryError subclasses RuntimeError, which /run does not
    catch — without the explicit clause it would surface as a 500."""

    def _raise(*args, **kwargs):
        raise InsufficientHistoryError(
            "Insufficient weekly history for beta estimation: NEWIPO (n=12); "
            "minimum 40 non-NaN weeks overlapping the factor matrix required"
        )

    monkeypatch.setattr("app.api.main.run_scenario", _raise)
    response = client.post(
        "/api/scenarios/run",
        json={"scenario_text": "Custom visitor stress", "portfolio_key": "us_tech_growth"},
    )
    assert response.status_code == 422
    assert "NEWIPO" in response.json()["detail"]


def test_run_reproducibility_carries_regression_spec(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.main.run_scenario", lambda text, portfolio, **kwargs: _fake_result(text)
    )
    response = client.post(
        "/api/scenarios/run",
        json={"scenario_text": "Custom visitor stress", "portfolio_key": "us_tech_growth"},
    )
    assert response.status_code == 200
    spec = response.json()["reproducibility"]["regression_spec"]
    assert spec.startswith("ridge-std-v2|lookback=")
    assert "alpha=" in spec and "min_obs=" in spec


def test_run_forwards_quant_horizon_and_severity(client, monkeypatch):
    captured = {}

    def _fake_run_scenario(text, portfolio, **kwargs):
        captured.update(kwargs)
        return _fake_result(text)

    monkeypatch.setattr("app.api.main.run_scenario", _fake_run_scenario)
    response = client.post(
        "/api/scenarios/run",
        json={
            "scenario_text": "Custom visitor stress",
            "portfolio_key": "us_tech_growth",
            "horizon": 63,
            "severity": 2.0,
        },
    )
    assert response.status_code == 200
    assert captured["horizon"] == 63
    assert captured["severity"] == 2.0


def test_quant_reproducibility_names_all_market_data_sources(client, monkeypatch):
    quant_result = _fake_result("Custom visitor stress").model_copy(
        update={
            "engine_mode": "quant_v2",
            "engine_version": "quant-v2-test",
            "methodology": "joint_historical_neighbors",
            "horizon_trading_days": 21,
            "severity_multiplier": 1.0,
        }
    )
    monkeypatch.setattr("app.api.main.run_scenario", lambda *args, **kwargs: quant_result)
    response = client.post(
        "/api/scenarios/run",
        json={"scenario_text": "Custom visitor stress", "portfolio_key": "us_tech_growth"},
    )
    assert response.status_code == 200
    assert (
        response.json()["reproducibility"]["market_data_source"]
        == "French Data Library + FRED + yfinance"
    )


def test_visitor_rejects_admin_only_run_inputs(client):
    custom_portfolio = client.post(
        "/api/scenarios/run",
        json={
            "sample_scenario_key": "china_tariffs",
            "portfolio_holdings": {"AAPL": 1.0},
        },
    )
    assert custom_portfolio.status_code == 403

    benchmark_override = client.post(
        "/api/scenarios/run",
        json={
            "scenario_text": "Custom visitor stress",
            "portfolio_key": "us_tech_growth",
            "benchmark": "SPY",
        },
    )
    assert benchmark_override.status_code == 403

    backdated = client.post(
        "/api/scenarios/run",
        json={
            "scenario_text": "Custom visitor stress",
            "portfolio_key": "us_tech_growth",
            "as_of_date": "2026-01-02",
        },
    )
    assert backdated.status_code == 403

    mtm = client.post(
        "/api/scenarios/run",
        json={
            "scenario_text": "Custom visitor stress",
            "portfolio_key": "us_tech_growth",
            "portfolio_nav": 100000,
        },
    )
    assert mtm.status_code == 403


def test_visitor_can_run_sample_scenario(client, monkeypatch):
    def _fake_run_scenario(scenario_text, portfolio, **kwargs):
        assert scenario_text.startswith("US announces 60% tariffs")
        assert portfolio == "us_tech_growth"
        return _fake_result(scenario_text)

    monkeypatch.setattr("app.api.main.run_scenario", _fake_run_scenario)

    response = client.post(
        "/api/scenarios/run",
        json={
            "sample_scenario_key": "china_tariffs",
            "portfolio_key": "us_tech_growth",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["portfolio_key"] == "us_tech_growth"
    assert "q4-trade-war-2018" in body["analog_events"]


def test_factor_metadata_endpoint_is_public_and_complete(client):
    response = client.get("/api/factors")
    assert response.status_code == 200
    factors = {item["key"]: item for item in response.json()}
    assert factors["SPY"]["display_name"] == "US large-cap equities"
    assert factors["ACWI"]["short_label"] == "Global equities"
    assert factors["TNX"]["ticker"] == "^TNX"


def test_admin_can_run_custom_scenario_and_portfolio(client, monkeypatch):
    client.post("/api/auth/unlock", json={"passcode": "test-passcode"})

    def _fake_run_scenario(scenario_text, portfolio, **kwargs):
        assert scenario_text == "Custom shock"
        assert portfolio.name == "Custom Book"
        assert portfolio.holdings == {"AAPL": 0.6, "MSFT": 0.4}
        return _fake_result(scenario_text)

    monkeypatch.setattr("app.api.main.run_scenario", _fake_run_scenario)

    response = client.post(
        "/api/scenarios/run",
        json={
            "scenario_text": "Custom shock",
            "portfolio_name": "Custom Book",
            "portfolio_holdings": {"aapl": 0.6, "msft": 0.4},
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["scenario_text"] == "Custom shock"


def test_decomposition_is_admin_only(client):
    result = _fake_result("x").model_dump(mode="json")
    response = client.post("/api/scenarios/decompose", json={"result": result})
    assert response.status_code == 403


def test_quant_decomposition_is_rejected_before_compute(client, monkeypatch):
    client.post("/api/auth/unlock", json={"passcode": "test-passcode"})
    result = _fake_result("quant result").model_copy(update={"engine_mode": "quant_v2"})

    def _unexpected(*args, **kwargs):
        raise AssertionError("Quant V2 must not start narrative Shapley")

    monkeypatch.setattr("app.api.main.compute_narrative_shapley", _unexpected)
    response = client.post(
        "/api/scenarios/decompose", json={"result": result.model_dump(mode="json")}
    )
    assert response.status_code == 422
    assert "unavailable for Quant V2" in response.json()["detail"]


def test_portfolio_validation_matches_weight_rules(client):
    invalid = client.post("/api/portfolio/validate", json={"holdings": {"AAPL": 0.7}})
    assert invalid.status_code == 200
    assert not invalid.json()["ok"]

    valid = client.post(
        "/api/portfolio/validate",
        json={"holdings": {"aapl": 60, "msft": 40}},
    )
    assert valid.status_code == 200
    body = valid.json()
    assert body["ok"]
    assert body["normalized_holdings"] == {"AAPL": 0.6, "MSFT": 0.4}
