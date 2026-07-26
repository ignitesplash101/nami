"""Cloud Storage cache for both parquet (market data) and JSON (LLM scenario responses).

TTL is enforced on read via the blob's `updated` timestamp. Two instances are typically
constructed: one with prefix="market_data" for parquet, one with prefix="scenario_cache"
for JSON.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import pandas as pd
from google.cloud import storage


class CacheProtocol(Protocol):
    """Minimal contract used by `app.llm.scenario.run_scenario`.

    The orchestrator only needs JSON I/O; tests pass an in-memory fake matching this
    Protocol instead of constructing a real `storage.Client()`.
    """

    def get_json(self, key: str, ttl_hours: int = ...) -> dict[str, Any] | None: ...

    def put_json(self, key: str, data: dict[str, Any]) -> None: ...


class CloudStorageCache:
    def __init__(self, bucket_name: str, prefix: str = "market_data") -> None:
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)
        self._prefix = prefix.strip("/")

    def _path(self, key: str, ext: str = "parquet") -> str:
        return f"{self._prefix}/{key}.{ext}"

    def _read_with_ttl(self, path: str, ttl_hours: int) -> bytes | None:
        """Blob bytes if the object exists and is inside its TTL, else None.

        `get_blob` returns a METADATA-POPULATED blob (or None when absent) in a
        single round trip, where the previous `exists()` + `reload()` pair took
        two. Every cache read goes through here — scenario hits, each market
        parquet, the event matrix — so this removes a third of the network calls
        on the hot path for identical semantics: `blob.updated` is populated by
        `get_blob`, so the TTL comparison is unchanged.
        """
        blob = self._bucket.get_blob(path)
        if blob is None or blob.updated is None:
            return None
        if datetime.now(UTC) - blob.updated > timedelta(hours=ttl_hours):
            return None
        return blob.download_as_bytes()

    def get(self, key: str, ttl_hours: int = 24) -> pd.DataFrame | None:
        data = self._read_with_ttl(self._path(key, ext="parquet"), ttl_hours)
        if data is None:
            return None
        return pd.read_parquet(io.BytesIO(data))

    def put(self, key: str, df: pd.DataFrame) -> None:
        buf = io.BytesIO()
        df.to_parquet(buf, index=True)
        buf.seek(0)
        blob = self._bucket.blob(self._path(key, ext="parquet"))
        blob.upload_from_file(buf, content_type="application/octet-stream")

    def get_json(self, key: str, ttl_hours: int = 24 * 7) -> dict[str, Any] | None:
        data = self._read_with_ttl(self._path(key, ext="json"), ttl_hours)
        if data is None:
            return None
        return json.loads(data)

    def put_json(self, key: str, data: dict[str, Any]) -> None:
        blob = self._bucket.blob(self._path(key, ext="json"))
        blob.upload_from_string(
            json.dumps(data, sort_keys=True),
            content_type="application/json",
        )

    def delete(self, key: str) -> None:
        for ext in ("parquet", "json"):
            blob = self._bucket.blob(self._path(key, ext=ext))
            if blob.exists(self._client):
                blob.delete()
