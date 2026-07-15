"""Lazy process singleton for the Quant V2 public-data parquet cache."""

from __future__ import annotations

from functools import lru_cache

from app.config import load_config
from app.data.cache import CloudStorageCache


@lru_cache(maxsize=1)
def get_public_data_cache() -> CloudStorageCache:
    """Return the shared 30-day public-data cache client for this process."""
    return CloudStorageCache(load_config().gcs_bucket, prefix="quant_public_data")
