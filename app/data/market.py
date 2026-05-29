"""yfinance wrapper returning adjusted close prices at weekly or daily granularity.

Wraps `yf.download` with a process-wide `CloudStorageCache` parquet layer (TTL 24h)
so the same ticker × window combination round-trips through GCS instead of yfinance
on subsequent calls. The cache is best-effort — any cache failure (missing GCS
credentials, parquet schema mismatch, etc.) silently falls back to yfinance.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable
from datetime import date, datetime

import pandas as pd
import yfinance as yf

from app.data.market_cache import (
    MARKET_CACHE_TTL_HOURS,
    MarketCacheProtocol,
    get_market_cache,
    market_cache_key,
)

# Per-request network timeout (seconds) for the yfinance HTTP fetch. Bounds the
# request so a stalled yfinance call cannot hang `run_scenario` /
# `adjust_scenario_shocks` / `compute_envelope` indefinitely — those wrap this
# helper in a ThreadPoolExecutor whose `with`-block shutdown(wait=True) would
# otherwise re-block on the hung worker. yfinance forwards `timeout=` to its
# requests session.
_YF_DOWNLOAD_TIMEOUT_SECONDS = 30


def _fetch_prices(
    tickers: Iterable[str],
    *,
    interval: str,
    start: date | datetime | str | None,
    end: date | datetime | str | None,
    lookback_periods: int | None,
    period_unit: str,
    auto_adjust: bool = True,
    cache: MarketCacheProtocol | None | str = "default",
) -> pd.DataFrame:
    """Shared implementation for fetch_weekly_prices and fetch_daily_prices.

    `period_unit` is the pandas Timedelta unit for `lookback_periods` ("W" or "D").
    `end` follows yfinance's convention: exclusive of the next bar. Callers needing
    inclusive-end semantics must add the appropriate offset before calling.

    `cache` defaults to the process-wide market cache singleton. Pass `cache=None`
    to bypass the cache layer entirely (unit tests; explicit fresh fetches). Pass
    an explicit `MarketCacheProtocol` instance to inject a fake.
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

    sorted_tickers = sorted(tickers)

    cache_instance: MarketCacheProtocol | None = (
        get_market_cache() if cache == "default" else cache  # type: ignore[assignment]
    )

    cache_key = market_cache_key(
        sorted_tickers, interval=interval, start=start, end=end, auto_adjust=auto_adjust
    )

    if cache_instance is not None:
        try:
            hit = cache_instance.get(cache_key, ttl_hours=MARKET_CACHE_TTL_HOURS)
        except Exception:  # noqa: BLE001 — cache read failure must not break a fetch
            hit = None
        if hit is not None and not hit.empty:
            return hit

    raw = yf.download(
        tickers=sorted_tickers,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=auto_adjust,
        progress=False,
        threads=True,
        timeout=_YF_DOWNLOAD_TIMEOUT_SECONDS,
    )

    if raw is None or raw.empty:
        raise RuntimeError(f"yfinance returned no data for {sorted_tickers!r}")

    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]].rename(columns={"Close": sorted_tickers[0]})

    closes = closes.dropna(how="all").sort_index()
    closes.columns.name = None

    if cache_instance is not None:
        # Cache write failure must not break a fetch.
        with contextlib.suppress(Exception):
            cache_instance.put(cache_key, closes)

    return closes


def fetch_weekly_prices(
    tickers: Iterable[str],
    start: date | datetime | str | None = None,
    end: date | datetime | str | None = None,
    lookback_weeks: int | None = None,
    *,
    cache: MarketCacheProtocol | None | str = "default",
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
        cache=cache,
    )


def fetch_daily_prices(
    tickers: Iterable[str],
    start: date | datetime | str | None = None,
    end: date | datetime | str | None = None,
    lookback_days: int | None = None,
    *,
    auto_adjust: bool = True,
    cache: MarketCacheProtocol | None | str = "default",
) -> pd.DataFrame:
    """Fetch daily close prices.

    Returns a DataFrame indexed by trading-day date, with one column per ticker.
    `end` is exclusive (yfinance convention) — pass end+1 day to include the
    end_date's closing bar. Tickers yfinance fails to return are silently dropped.

    `auto_adjust=True` (default) returns split/dividend-adjusted close for return
    modeling. Pass `auto_adjust=False` to get the RAW close — required for
    mark-to-market valuation of share quantities (shares × raw close = position
    market value); the cache keeps raw and adjusted in separate keyspaces.
    """
    return _fetch_prices(
        tickers,
        interval="1d",
        start=start,
        end=end,
        lookback_periods=lookback_days,
        period_unit="D",
        auto_adjust=auto_adjust,
        cache=cache,
    )


def compute_weekly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple percent-change weekly returns. First row is dropped."""
    return prices.pct_change(fill_method=None).dropna(how="all")
