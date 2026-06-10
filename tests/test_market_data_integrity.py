"""Market-layer integrity: transient yfinance failures must not poison the
24h GCS cache or masquerade as 'insufficient history'.

A ticker yfinance flakes on (rate limit, outage) comes back as an all-NaN
COLUMN in the batch. Before these guards, that column survived the row-wise
dropna, was written to the cache, and every run on the window then failed with
`InsufficientHistoryError: TICKER (n=0)` for the TTL.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data import market
from app.factors.regression import InsufficientHistoryError, estimate_betas_and_stats


class RecordingCache:
    """MarketCacheProtocol fake that records puts and serves a fixed hit."""

    def __init__(self) -> None:
        self.puts: list[tuple[str, pd.DataFrame]] = []

    def get(self, key: str, ttl_hours: int = 24) -> pd.DataFrame | None:
        return None

    def put(self, key: str, frame: pd.DataFrame) -> None:
        self.puts.append((key, frame))


def _yf_frame(columns: dict[str, list[float]]) -> pd.DataFrame:
    index = pd.date_range("2026-01-05", periods=3, freq="W-MON")
    closes = pd.DataFrame(columns, index=index)
    return pd.concat({"Close": closes}, axis=1)


def test_all_nan_column_is_dropped_and_batch_not_cached(monkeypatch):
    nan = float("nan")
    monkeypatch.setattr(
        market.yf,
        "download",
        lambda **kwargs: _yf_frame({"AAPL": [1.0, 2.0, 3.0], "NVDA": [nan, nan, nan]}),
    )
    cache = RecordingCache()

    prices = market.fetch_weekly_prices(["AAPL", "NVDA"], lookback_weeks=3, cache=cache)

    # The flaked ticker is DROPPED (the documented contract), not kept as NaNs
    # that downstream regression would read as n=0.
    assert list(prices.columns) == ["AAPL"]
    # And the incomplete batch is NEVER cached — caching it would poison every
    # run on this window for the 24h TTL.
    assert cache.puts == []


def test_complete_batch_is_cached(monkeypatch):
    monkeypatch.setattr(
        market.yf,
        "download",
        lambda **kwargs: _yf_frame({"AAPL": [1.0, 2.0, 3.0], "MSFT": [4.0, 5.0, 6.0]}),
    )
    cache = RecordingCache()

    prices = market.fetch_weekly_prices(["AAPL", "MSFT"], lookback_weeks=3, cache=cache)

    assert sorted(prices.columns) == ["AAPL", "MSFT"]
    assert len(cache.puts) == 1


def test_all_tickers_flaked_raises_loudly(monkeypatch):
    nan = float("nan")
    monkeypatch.setattr(
        market.yf,
        "download",
        lambda **kwargs: _yf_frame({"AAPL": [nan, nan, nan]}),
    )
    with pytest.raises(RuntimeError, match="no usable data"):
        market.fetch_weekly_prices(["AAPL"], lookback_weeks=3, cache=None)


def test_n_zero_error_message_names_the_transient_fetch_cause():
    rng = np.random.default_rng(7)
    index = pd.date_range("2023-01-02", periods=60, freq="W-MON")
    factors = pd.DataFrame(rng.normal(0, 0.02, size=(60, 2)), index=index, columns=["SPY", "VIX"])
    tickers = pd.DataFrame(
        {"AAPL": rng.normal(0, 0.03, size=60), "NVDA": np.full(60, np.nan)}, index=index
    )

    with pytest.raises(InsufficientHistoryError) as excinfo:
        estimate_betas_and_stats(tickers, factors, min_obs=40)

    message = str(excinfo.value)
    assert "NVDA (n=0)" in message
    assert "transient" in message
    assert "retry" in message
