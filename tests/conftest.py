"""Shared test helpers — primarily an in-memory cache implementing `CacheProtocol`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """Rate limiting is per-process stateful; disable it by default so unrelated
    tests that make several requests don't trip limits. The dedicated rate-limit
    test re-enables it explicitly."""
    from app.api.ratelimit import limiter

    previously = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previously


@dataclass
class InMemoryCache:
    """Drop-in `CacheProtocol` implementation for tests. Stores dicts in a plain dict.

    Ignores TTL on read (always returns the stored value if the key exists) — tests
    that care about TTL semantics should test `CloudStorageCache` directly.
    """

    store: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get_json(self, key: str, ttl_hours: int = 24 * 7) -> dict[str, Any] | None:
        return self.store.get(key)

    def put_json(self, key: str, data: dict[str, Any]) -> None:
        self.store[key] = data
