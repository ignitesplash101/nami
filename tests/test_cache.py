"""CloudStorageCache read semantics.

The read path was collapsed from `exists()` + `reload()` + `download_as_bytes()`
(three GCS round trips) to `get_blob()` + `download_as_bytes()` (two). Every cache
read in the app goes through it — scenario hits, each market parquet, the event
matrix — so these tests pin that the TTL contract survived the change AND that an
expired or absent object costs no download.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.data import cache as cache_module


class _FakeBlob:
    def __init__(self, payload: bytes, updated: datetime) -> None:
        self._payload = payload
        self.updated = updated
        self.downloads = 0

    def download_as_bytes(self) -> bytes:
        self.downloads += 1
        return self._payload


class _FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, _FakeBlob] = {}
        self.get_blob_calls: list[str] = []

    def get_blob(self, path: str) -> _FakeBlob | None:
        self.get_blob_calls.append(path)
        return self.objects.get(path)


class _FakeClient:
    def __init__(self) -> None:
        self.bucket_obj = _FakeBucket()

    def bucket(self, _name: str) -> _FakeBucket:
        return self.bucket_obj


@pytest.fixture
def cache(monkeypatch) -> cache_module.CloudStorageCache:
    """A CloudStorageCache with the GCS client stubbed out."""
    monkeypatch.setattr(cache_module.storage, "Client", _FakeClient)
    return cache_module.CloudStorageCache("test-bucket", prefix="unit")


def _fresh(payload: bytes) -> _FakeBlob:
    return _FakeBlob(payload, datetime.now(UTC) - timedelta(minutes=5))


def test_json_round_trip_within_ttl_takes_one_lookup(cache):
    blob = _fresh(json.dumps({"total_pnl": -0.25}).encode("utf-8"))
    cache._bucket.objects["unit/key.json"] = blob

    assert cache.get_json("key", ttl_hours=24) == {"total_pnl": -0.25}
    # One metadata lookup, one download — the point of the change.
    assert cache._bucket.get_blob_calls == ["unit/key.json"]
    assert blob.downloads == 1


def test_expired_object_is_a_miss_and_is_never_downloaded(cache):
    blob = _FakeBlob(b"{}", datetime.now(UTC) - timedelta(hours=30))
    cache._bucket.objects["unit/key.json"] = blob

    assert cache.get_json("key", ttl_hours=24) is None
    assert blob.downloads == 0  # TTL is decided from get_blob's metadata alone


def test_absent_object_is_a_miss(cache):
    assert cache.get_json("nope", ttl_hours=24) is None
    assert cache.get("nope", ttl_hours=24) is None


def test_blob_without_an_updated_timestamp_is_a_miss(cache):
    """Defensive: a blob whose metadata lacks `updated` cannot be TTL-checked."""
    blob = _FakeBlob(b"{}", datetime.now(UTC))
    blob.updated = None  # type: ignore[assignment]
    cache._bucket.objects["unit/key.json"] = blob

    assert cache.get_json("key", ttl_hours=24) is None
    assert blob.downloads == 0


def test_parquet_round_trip_within_ttl(cache):
    frame = pd.DataFrame({"SPY": [0.01, -0.02]}, index=pd.Index([1, 2], name="i"))
    import io

    buf = io.BytesIO()
    frame.to_parquet(buf, index=True)
    cache._bucket.objects["unit/prices.parquet"] = _fresh(buf.getvalue())

    got = cache.get("prices", ttl_hours=24)
    assert got is not None
    pd.testing.assert_frame_equal(got, frame)
