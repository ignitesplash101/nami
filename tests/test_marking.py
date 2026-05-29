"""Mark-to-market valuation tests — fail-closed, FX inversion, pence, staleness."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.data import marking
from app.data.marking import (
    MarkingError,
    currency_for_ticker,
    fetch_fx_to_usd,
    fetch_marks,
    mark_book,
    mark_positions,
)


def _df(index_dates: list[str], columns: dict[str, list[float]]) -> pd.DataFrame:
    return pd.DataFrame(columns, index=pd.to_datetime(index_dates))


def test_currency_for_ticker_suffix_map():
    assert currency_for_ticker("AAPL") == "USD"
    assert currency_for_ticker("7203.T") == "JPY"
    assert currency_for_ticker("BP.L") == "GBp"  # London quoted in pence
    assert currency_for_ticker("AIR.PA") == "EUR"
    assert currency_for_ticker("FOO.ZZ") == "USD"  # unknown suffix -> USD


def test_mark_positions_usd_only():
    marks = {"AAPL": (200.0, date(2024, 1, 5)), "MSFT": (400.0, date(2024, 1, 5))}
    fx = {"USD": (1.0, date(2024, 1, 5))}
    mr = mark_positions({"AAPL": 10, "MSFT": 5}, marks, fx)
    assert mr.nav == pytest.approx(200 * 10 + 400 * 5)  # 4000
    assert mr.weights["AAPL"] == pytest.approx(2000 / 4000)
    assert sum(mr.weights.values()) == pytest.approx(1.0)
    assert mr.reporting_currency == "USD"


def test_mark_positions_jpy_fx_conversion():
    marks = {"7203.T": (3000.0, date(2024, 1, 5))}
    fx = {"JPY": (0.0064, date(2024, 1, 5))}  # USD per JPY
    mr = mark_positions({"7203.T": 100}, marks, fx)
    assert mr.nav == pytest.approx(100 * 3000 * 0.0064)


def test_mark_positions_gbp_pence_divides_by_100():
    marks = {"BP.L": (500.0, date(2024, 1, 5))}  # 500 pence = £5.00
    fx = {"GBP": (1.25, date(2024, 1, 5))}  # USD per GBP
    mr = mark_positions({"BP.L": 10}, marks, fx)
    assert mr.nav == pytest.approx(10 * 500 * 0.01 * 1.25)  # 62.50


def test_mark_positions_missing_mark_fails_closed():
    with pytest.raises(MarkingError):
        mark_positions({"AAPL": 10}, {}, {"USD": (1.0, date(2024, 1, 5))})


def test_mark_positions_missing_fx_fails_closed():
    marks = {"7203.T": (3000.0, date(2024, 1, 5))}
    with pytest.raises(MarkingError):
        mark_positions({"7203.T": 100}, marks, {"USD": (1.0, date(2024, 1, 5))})


def test_fetch_marks_uses_last_valid_close(monkeypatch):
    captured: dict = {}

    def fake(tickers, *, start, end, auto_adjust, cache):
        captured["auto_adjust"] = auto_adjust
        return _df(["2024-01-03", "2024-01-04", "2024-01-05"], {"AAPL": [100.0, 101.0, 102.0]})

    monkeypatch.setattr(marking, "fetch_daily_prices", fake)
    out = fetch_marks(["AAPL"], as_of=date(2024, 1, 5), cache=None)
    assert captured["auto_adjust"] is False, "MTM must mark on RAW close, not adjusted"
    assert out["AAPL"] == (102.0, date(2024, 1, 5))


def test_fetch_marks_stale_fails_closed(monkeypatch):
    monkeypatch.setattr(
        marking, "fetch_daily_prices", lambda *a, **k: _df(["2024-01-01"], {"AAPL": [100.0]})
    )
    with pytest.raises(MarkingError, match="Stale"):
        fetch_marks(["AAPL"], as_of=date(2024, 1, 20), cache=None)


def test_fetch_fx_inversion_and_direction(monkeypatch):
    monkeypatch.setattr(
        marking,
        "fetch_daily_prices",
        lambda *a, **k: _df(["2024-01-05"], {"USDJPY=X": [156.25], "EURUSD=X": [1.09]}),
    )
    out = fetch_fx_to_usd({"JPY", "EUR"}, as_of=date(2024, 1, 5), cache=None)
    assert out["JPY"][0] == pytest.approx(1 / 156.25)  # USDJPY inverted -> USD per JPY
    assert out["EUR"][0] == pytest.approx(1.09)  # EURUSD already USD per EUR
    assert out["USD"][0] == 1.0


def test_fetch_fx_unsupported_currency_fails_closed(monkeypatch):
    monkeypatch.setattr(marking, "fetch_daily_prices", lambda *a, **k: _df(["2024-01-05"], {}))
    with pytest.raises(MarkingError, match="No FX pair"):
        fetch_fx_to_usd({"BRL"}, as_of=date(2024, 1, 5), cache=None)


def test_mark_book_end_to_end_mixed_currency(monkeypatch):
    def fake(tickers, *, start, end, auto_adjust, cache):
        cols: dict[str, list[float]] = {}
        for ticker in tickers:
            if ticker == "AAPL":
                cols[ticker] = [200.0]
            elif ticker == "7203.T":
                cols[ticker] = [3000.0]
            elif ticker == "USDJPY=X":
                cols[ticker] = [156.25]
        return _df(["2024-01-05"], cols)

    monkeypatch.setattr(marking, "fetch_daily_prices", fake)
    mr = mark_book({"AAPL": 10, "7203.T": 100}, as_of=date(2024, 1, 5), cache=None)
    expected = 200 * 10 + 3000 * 100 * (1 / 156.25)
    assert mr.nav == pytest.approx(expected)
    assert set(mr.weights) == {"AAPL", "7203.T"}
    assert sum(mr.weights.values()) == pytest.approx(1.0)
    assert mr.fx_rates["JPY"] == pytest.approx(1 / 156.25)
