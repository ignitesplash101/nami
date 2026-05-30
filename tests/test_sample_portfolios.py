"""Tests for the frozen cap-weight snapshot loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.data import sample_portfolios as sp


def test_all_samples_load_and_sum_to_one():
    for key, _name in sp.list_portfolios():
        portfolio = sp.get_portfolio(key)
        assert abs(sum(portfolio.holdings.values()) - 1.0) < 1e-6
        assert portfolio.holdings  # non-empty


def test_weights_are_not_equal_weight():
    """Guards against a regression back to naive equal-weighting."""
    for key, _name in sp.list_portfolios():
        weights = list(sp.get_portfolio(key).holdings.values())
        spread = max(weights) - min(weights)
        assert spread > 1e-3, f"{key} looks equal-weighted (spread={spread})"


def test_samples_have_benchmarks():
    assert sp.get_portfolio("us_tech_growth").benchmark == "QQQ"
    assert sp.get_portfolio("msci_world").benchmark == "URTH"
    assert sp.get_portfolio("defensive_mix").benchmark == "SPLV"
    assert sp.get_portfolio("japan_equity").benchmark == "EWJ"


def test_ticker_metadata_includes_cash_and_real_tags():
    meta = sp.ticker_metadata()
    assert meta["CASH"] == {"sector": "Cash", "country": "Cash"}
    # A real US name carries a sector/country tag from the snapshot.
    assert "AAPL" in meta
    assert meta["AAPL"]["country"] == "United States"


def test_missing_snapshot_raises(monkeypatch):
    monkeypatch.setattr(sp, "_WEIGHTS_PATH", Path("does-not-exist-snapshot.json"))
    sp._load_snapshot.cache_clear()
    with pytest.raises(RuntimeError, match="snapshot missing"):
        sp._load_snapshot()
    # Restore the real cache for downstream tests.
    sp._load_snapshot.cache_clear()
    sp._build_portfolios.cache_clear()
