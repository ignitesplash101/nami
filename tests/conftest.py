"""Shared test helpers — primarily an in-memory cache implementing `CacheProtocol`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
