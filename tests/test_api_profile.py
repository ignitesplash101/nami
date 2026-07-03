"""Free book-profile endpoint — access rules, math wiring, error mapping."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api.main import api
from app.data.firestore_store import InMemoryFirestoreStore
from app.data.sample_portfolios import get_portfolio
from app.factors.regression import InsufficientHistoryError, TickerRegressionStats


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PASSCODE", "test-passcode")
    monkeypatch.setattr("app.api.main._firestore_store", InMemoryFirestoreStore())
    return TestClient(api)


FACTORS3 = ["SPY", "ACWI", "GLD"]


def _patch_profile_market(monkeypatch, *, beta_value: float = 0.5) -> None:
    def fake_fetch_weekly_prices(tickers, *args, **kwargs):
        return pd.DataFrame(
            {t: [100.0, 101.0, 102.0] for t in tickers},
            index=pd.date_range("2026-05-01", periods=3, freq="W"),
        )

    def fake_get_factor_returns_with_history(lookback_weeks=156):
        idx = pd.date_range("2024-01-01", periods=60, freq="W")
        raw = pd.DataFrame({f: np.linspace(-0.01, 0.01, 60) for f in FACTORS3}, index=idx)
        return raw, raw - raw.mean(axis=0)

    def fake_estimate(portfolio, lookback_weeks=156, alpha=0.1, end=None, **kwargs):
        tickers = portfolio.tickers
        betas = pd.DataFrame(beta_value, index=tickers, columns=FACTORS3)
        stats = {
            t: TickerRegressionStats(r2=0.5, n_obs=60, idio_vol_weekly=0.02, r2_adj=0.4, p_eff=3.0)
            for t in tickers
        }
        return betas, stats

    monkeypatch.setattr("app.llm.scenario.fetch_weekly_prices", fake_fetch_weekly_prices)
    monkeypatch.setattr(
        "app.llm.scenario.get_factor_returns_with_history",
        fake_get_factor_returns_with_history,
    )
    monkeypatch.setattr("app.llm.scenario.estimate_betas_for_portfolio", fake_estimate)
    monkeypatch.setattr("app.llm.scenario.convert_weekly_returns_to_usd", lambda r, **k: r)


def test_visitor_sample_profile(client, monkeypatch):
    _patch_profile_market(monkeypatch)
    resp = client.post("/api/portfolios/profile", json={"portfolio_key": "us_tech_growth"})
    assert resp.status_code == 200
    body = resp.json()
    book = get_portfolio("us_tech_growth")
    # uniform betas of 0.5 and weights summing to 1 -> exposure 0.5 per factor
    for factor in FACTORS3:
        assert body["factor_exposures"][factor] == pytest.approx(0.5)
    assert body["n_factors"] == 3
    weights = [row["weight"] for row in body["per_name"]]
    assert weights == sorted(weights, reverse=True)
    expected_band = sum((w * 0.02) ** 2 for w in book.holdings.values()) ** 0.5
    assert body["idio_band_weekly"] == pytest.approx(expected_band)
    assert body["per_name"][0]["r2_adj"] == pytest.approx(0.4)
    assert body["portfolio_name"] == book.name


def test_visitor_custom_holdings_forbidden(client, monkeypatch):
    _patch_profile_market(monkeypatch)
    resp = client.post("/api/portfolios/profile", json={"portfolio_holdings": {"AAPL": 1.0}})
    assert resp.status_code == 403


def test_visitor_unknown_key_forbidden(client, monkeypatch):
    _patch_profile_market(monkeypatch)
    resp = client.post("/api/portfolios/profile", json={"portfolio_key": "nope"})
    assert resp.status_code == 403


def test_admin_custom_holdings(client, monkeypatch):
    _patch_profile_market(monkeypatch)
    unlock = client.post("/api/auth/unlock", json={"passcode": "test-passcode"})
    assert unlock.status_code == 200
    resp = client.post(
        "/api/portfolios/profile",
        json={"portfolio_holdings": {"AAPL": 0.6, "MSFT": 0.4}, "portfolio_name": "Two names"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [row["ticker"] for row in body["per_name"]] == ["AAPL", "MSFT"]
    assert body["factor_exposures"]["SPY"] == pytest.approx(0.5)
    assert body["portfolio_name"] == "Two names"


def test_insufficient_history_maps_to_422(client, monkeypatch):
    _patch_profile_market(monkeypatch)

    def raiser(*args, **kwargs):
        raise InsufficientHistoryError(
            "Insufficient weekly history for beta estimation: AAPL (n=10)"
        )

    monkeypatch.setattr("app.llm.scenario.estimate_betas_for_portfolio", raiser)
    resp = client.post("/api/portfolios/profile", json={"portfolio_key": "us_tech_growth"})
    assert resp.status_code == 422
    assert "AAPL" in resp.json()["detail"]


def test_transient_market_failure_maps_to_coded_503(client, monkeypatch):
    _patch_profile_market(monkeypatch)

    def raiser(*args, **kwargs):
        raise RuntimeError("yfinance returned no data for tickers=['AAPL']")

    monkeypatch.setattr("app.llm.scenario.fetch_weekly_prices", raiser)
    resp = client.post("/api/portfolios/profile", json={"portfolio_key": "us_tech_growth"})
    assert resp.status_code == 503
    assert resp.headers.get("X-Error-Code") == "unavailable"
