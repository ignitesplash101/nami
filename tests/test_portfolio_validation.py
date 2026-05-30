"""Tests for holdings/quantity validation, incl. the CASH sentinel."""

from __future__ import annotations

from app.api.portfolio_validation import validate_holdings, validate_quantities


def test_cash_sleeve_accepted_with_market_holding():
    holdings, errors = validate_holdings({"AAPL": 0.6, "CASH": 0.4})
    assert errors == []
    assert holdings == {"AAPL": 0.6, "CASH": 0.4}


def test_all_cash_book_rejected():
    _holdings, errors = validate_holdings({"CASH": 1.0})
    assert any("non-cash" in e for e in errors)


def test_all_cash_quantities_rejected():
    _qty, errors = validate_quantities({"CASH": 1000})
    assert any("non-cash" in e for e in errors)


def test_cash_quantity_accepted_with_a_share_position():
    qty, errors = validate_quantities({"AAPL": 10, "CASH": 5000})
    assert errors == []
    assert qty == {"AAPL": 10.0, "CASH": 5000.0}


def test_percentages_still_autonormalize_with_cash():
    holdings, errors = validate_holdings({"AAPL": 60, "MSFT": 30, "CASH": 10})
    assert errors == []
    assert abs(sum(holdings.values()) - 1.0) < 1e-9
    assert holdings["CASH"] == 0.10
