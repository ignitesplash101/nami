"""Process-wide market-data cache wrapper.

Provides a small `MarketCacheProtocol` (parquet get/put) and a lazy singleton
`get_market_cache()` that returns the production `CloudStorageCache` instance under
the `market_data/` prefix. Tests pass a fake (or `None`) so they stay offline.

The cache wraps `_fetch_prices` in `app.data.market`. Cache key inputs:

- `sorted(tickers)` — set ordering must be stable
- `interval` ("1wk" or "1d")
- `start` (ISO date) — already resolved from `lookback_periods` by the caller
- `end` (ISO date) — passthrough; None encodes as "open"
- `MARKET_CACHE_VERSION` — bump when parquet schema or yfinance normalization changes

The key intentionally does NOT include `lookback_*` — `_fetch_prices` resolves those
into a concrete `start` before calling us, so equivalent windows from different call
sites collide on the same cache entry.
"""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Iterable
from datetime import date, datetime
from typing import Protocol

import pandas as pd

from app.data.cache import CloudStorageCache

MARKET_CACHE_VERSION = "v1"
MARKET_CACHE_TTL_HOURS = 24
MARKET_CACHE_PREFIX = "market_data"


class MarketCacheProtocol(Protocol):
    """Parquet I/O surface used by `_fetch_prices`. `CloudStorageCache` matches it;
    tests pass an in-memory fake."""

    def get(self, key: str, ttl_hours: int = ...) -> pd.DataFrame | None:
        ...

    def put(self, key: str, df: pd.DataFrame) -> None:
        ...


def _normalize_date(value: date | datetime | str | None) -> str:
    if value is None:
        return "open"
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def market_cache_key(
    tickers: Iterable[str],
    *,
    interval: str,
    start: date | datetime | str | None,
    end: date | datetime | str | None,
    auto_adjust: bool = True,
) -> str:
    """Stable SHA256-derived key, short enough for a GCS blob name.

    Tickers are sorted before hashing — callers can pass sets/lists in any order
    and still collide on the same cache entry.

    `auto_adjust` distinguishes split/dividend-adjusted close (return modeling) from
    RAW close (mark-to-market valuation of share quantities) — the two must never
    collide. The flag is appended only for raw fetches so existing adjusted-close
    cache entries keep their keys (no invalidation of the common path).
    """
    parts = [
        MARKET_CACHE_VERSION,
        interval,
        _normalize_date(start),
        _normalize_date(end),
        ",".join(sorted(tickers)),
    ]
    if not auto_adjust:
        parts.append("raw")
    payload = "|".join(parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"{interval}_{digest}"


@functools.lru_cache(maxsize=1)
def get_market_cache() -> CloudStorageCache | None:
    """Lazy singleton. Returns None if `GCS_BUCKET` is unset (local dev / tests).

    The CloudStorageCache constructor calls `storage.Client()` at instantiation,
    which requires ADC — so we defer construction past import time and tolerate
    missing config by returning None (callers treat None as "no cache layer").
    """
    try:
        from app.config import load_config

        config = load_config()
    except Exception:  # noqa: BLE001 — config missing in unit tests is expected
        return None
    if not config.gcs_bucket:
        return None
    try:
        return CloudStorageCache(config.gcs_bucket, prefix=MARKET_CACHE_PREFIX)
    except Exception:  # noqa: BLE001 — no ADC available locally is fine
        return None
