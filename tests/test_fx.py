"""Unit tests for app.data.fx — synthetic data, injected fake fetch, no network."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.data import fx
from app.data.fx import convert_weekly_returns_to_usd
from app.data.marking import MarkingError

_W0 = pd.Timestamp("2024-01-01")
_W1 = pd.Timestamp("2024-01-08")
_W2 = pd.Timestamp("2024-01-15")


def test_all_usd_book_passes_through_with_zero_fx_fetches(monkeypatch):
    def _no_fetch(*args, **kwargs):
        raise AssertionError("FX fetch must not run for an all-USD book")

    monkeypatch.setattr(fx, "fetch_weekly_prices", _no_fetch)
    local = pd.DataFrame({"AAPL": [0.01], "MSFT": [-0.02]}, index=[_W1])

    out = convert_weekly_returns_to_usd(local)
    assert out is local  # identity, not a copy — zero-cost common case


def test_jpy_ticker_compounds_local_and_fx_returns(monkeypatch):
    # USDJPY=X quotes JPY per USD (invert=True). 1/rate moves 0.010 -> 0.0098,
    # i.e. the JPY loses 2% vs USD while the stock gains 1% locally:
    # (1 + 0.01) * (1 - 0.02) - 1 = -0.0102.
    def _fake_fetch(tickers, start=None, end=None, lookback_weeks=None, *, cache="default"):
        assert tickers == ["USDJPY=X"]
        return pd.DataFrame({"USDJPY=X": [100.0, 1.0 / 0.0098]}, index=[_W0, _W1])

    monkeypatch.setattr(fx, "fetch_weekly_prices", _fake_fetch)
    local = pd.DataFrame({"7203.T": [0.01]}, index=[_W1])

    out = convert_weekly_returns_to_usd(local)
    assert out.loc[_W1, "7203.T"] == pytest.approx(-0.0102, abs=1e-12)


def test_london_ticker_uses_gbpusd_directly_without_pence_scaling(monkeypatch):
    # GBp's 1/100 price scale cancels in pct_change, so pence returns convert
    # with GBPUSD (invert=False) and NO /100 anywhere.
    captured: dict[str, object] = {}

    def _fake_fetch(tickers, start=None, end=None, lookback_weeks=None, *, cache="default"):
        captured["tickers"] = list(tickers)
        return pd.DataFrame({"GBPUSD=X": [1.25, 1.25 * 0.98]}, index=[_W0, _W1])

    monkeypatch.setattr(fx, "fetch_weekly_prices", _fake_fetch)
    local = pd.DataFrame({"FOO.L": [0.01]}, index=[_W1])

    out = convert_weekly_returns_to_usd(local)
    assert captured["tickers"] == ["GBPUSD=X"]
    assert out.loc[_W1, "FOO.L"] == pytest.approx(1.01 * 0.98 - 1.0, abs=1e-12)


def test_missing_fx_bar_becomes_nan_not_silent_local_return(monkeypatch):
    def _fake_fetch(tickers, start=None, end=None, lookback_weeks=None, *, cache="default"):
        # FX has bars for W0/W1 only — the W2 local return has no FX return.
        return pd.DataFrame({"USDJPY=X": [100.0, 101.0]}, index=[_W0, _W1])

    monkeypatch.setattr(fx, "fetch_weekly_prices", _fake_fetch)
    local = pd.DataFrame({"7203.T": [0.01, 0.02]}, index=[_W1, _W2])

    out = convert_weekly_returns_to_usd(local)
    assert pd.notna(out.loc[_W1, "7203.T"])
    assert pd.isna(out.loc[_W2, "7203.T"])


def test_end_is_forwarded_to_the_fx_fetch(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_fetch(tickers, start=None, end=None, lookback_weeks=None, *, cache="default"):
        captured["end"] = end
        return pd.DataFrame({"USDJPY=X": [100.0, 101.0]}, index=[_W0, _W1])

    monkeypatch.setattr(fx, "fetch_weekly_prices", _fake_fetch)
    local = pd.DataFrame({"7203.T": [0.01]}, index=[_W1])

    convert_weekly_returns_to_usd(local, end=date(2024, 2, 1))
    assert captured["end"] == date(2024, 2, 1)


def test_entirely_missing_fx_series_fails_closed(monkeypatch):
    def _fake_fetch(tickers, start=None, end=None, lookback_weeks=None, *, cache="default"):
        return pd.DataFrame()  # yfinance returned nothing

    monkeypatch.setattr(fx, "fetch_weekly_prices", _fake_fetch)
    local = pd.DataFrame({"7203.T": [0.01]}, index=[_W1])

    with pytest.raises(MarkingError, match="FX series unavailable for JPY"):
        convert_weekly_returns_to_usd(local)
