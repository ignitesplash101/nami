"""yfinance wrapper returning adjusted close prices at weekly or daily granularity."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

import pandas as pd
import yfinance as yf


def _fetch_prices(
    tickers: Iterable[str],
    *,
    interval: str,
    start: date | datetime | str | None,
    end: date | datetime | str | None,
    lookback_periods: int | None,
    period_unit: str,
) -> pd.DataFrame:
    """Shared implementation for fetch_weekly_prices and fetch_daily_prices.

    `period_unit` is the pandas Timedelta unit for `lookback_periods` ("W" or "D").
    `end` follows yfinance's convention: exclusive of the next bar. Callers needing
    inclusive-end semantics must add the appropriate offset before calling.
    """
    tickers = list(tickers)
    if not tickers:
        raise ValueError("tickers must be a non-empty iterable")

    if lookback_periods is not None and start is None:
        if end is not None:
            anchor = pd.Timestamp(end).normalize()
        else:
            anchor = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        start = (anchor - pd.Timedelta(value=lookback_periods, unit=period_unit)).date()

    raw = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    if raw is None or raw.empty:
        raise RuntimeError(f"yfinance returned no data for {tickers!r}")

    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]].rename(columns={"Close": tickers[0]})

    closes = closes.dropna(how="all").sort_index()
    closes.columns.name = None
    return closes


def fetch_weekly_prices(
    tickers: Iterable[str],
    start: date | datetime | str | None = None,
    end: date | datetime | str | None = None,
    lookback_weeks: int | None = None,
) -> pd.DataFrame:
    """Fetch weekly adjusted close prices.

    Returns a DataFrame indexed by week-ending date, with one column per ticker.
    Tickers yfinance fails to return are silently dropped — check the column set
    against the input if completeness matters.
    """
    return _fetch_prices(
        tickers,
        interval="1wk",
        start=start,
        end=end,
        lookback_periods=lookback_weeks,
        period_unit="W",
    )


def fetch_daily_prices(
    tickers: Iterable[str],
    start: date | datetime | str | None = None,
    end: date | datetime | str | None = None,
    lookback_days: int | None = None,
) -> pd.DataFrame:
    """Fetch daily adjusted close prices.

    Returns a DataFrame indexed by trading-day date, with one column per ticker.
    `end` is exclusive (yfinance convention) — pass end+1 day to include the
    end_date's closing bar. Tickers yfinance fails to return are silently dropped.
    """
    return _fetch_prices(
        tickers,
        interval="1d",
        start=start,
        end=end,
        lookback_periods=lookback_days,
        period_unit="D",
    )


def compute_weekly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple percent-change weekly returns. First row is dropped."""
    return prices.pct_change(fill_method=None).dropna(how="all")
