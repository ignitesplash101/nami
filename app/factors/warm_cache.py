"""Process-lifetime in-memory cache for universe-level fetches.

Sits on top of the Tier-1 GCS market-data cache. Within a single Cloud Run
instance, repeated scenarios reuse the cached return tuple without even hitting
GCS. Across instances or after a restart, the underlying GCS cache (24h TTL)
absorbs the cold-start cost.

Universe-level only — do NOT cache portfolio-keyed fetches here, since the Portfolio
dataclass + custom holdings would explode the cache key space and risk dataclass-hash
subtleties.

Degraded results are NOT memoized. `fetch_factor_returns_with_history` returns
`(raw, None)` when a transient market-data failure (e.g. a provider rate limit
at instance boot) leaves fewer than the required complete rows for the SHAP
background. Memoizing that tuple would silently downgrade every subsequent
scenario in the process to naive-only attribution until the instance recycles —
so a `(raw, None)` result is returned to the caller but never cached, and the
next call retries the fetch.

FastAPI integration note: this module exposes functions that can be called from a
`lifespan` startup hook to warm the cache before the first request.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import logging
import threading
from typing import Protocol

import pandas as pd

from app.data.cache import CloudStorageCache
from app.data.market_cache import MARKET_CACHE_VERSION
from app.factors.analogs import (
    HistoricalEvent,
    events_version,
    fetch_event_returns_matrix,
    load_events,
)
from app.factors.regression import fetch_factor_returns_with_history
from app.factors.universe import FACTORS, factor_universe_version

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 4  # covers a handful of distinct lookback_weeks values

EVENT_MATRIX_CACHE_PREFIX = "event_returns"
EVENT_MATRIX_CACHE_TTL_HOURS = 24 * 30
EVENT_MATRIX_CACHE_VERSION = "v1"

_lock = threading.Lock()
_cache: dict[int, tuple[pd.DataFrame, pd.DataFrame]] = {}
# Single-flight guard: held across the WHOLE fetch so a request racing the
# background startup warm (or another request) waits for the in-flight fan-out
# and reuses its result instead of launching a duplicate ~26-ticker download —
# concurrent duplicates contend on provider rate limits and made the racing
# request SLOWER than no warm at all (observed live: 150s events-replay).
_fetch_lock = threading.Lock()

_events_lock = threading.Lock()
_events_matrix_cache: dict[str, pd.DataFrame] = {}
_events_fetch_lock = threading.Lock()


class EventMatrixCacheProtocol(Protocol):
    """Parquet cache surface used by the persistent full event matrix."""

    def get(self, key: str, ttl_hours: int = ...) -> pd.DataFrame | None: ...

    def put(self, key: str, df: pd.DataFrame) -> None: ...


@functools.lru_cache(maxsize=1)
def get_event_matrix_cache() -> EventMatrixCacheProtocol | None:
    """Lazy persistent cache; local/test environments without config use none."""
    try:
        from app.config import load_config

        config = load_config()
    except Exception:  # noqa: BLE001 — missing local config is expected
        return None
    if not config.gcs_bucket:
        return None
    try:
        return CloudStorageCache(config.gcs_bucket, prefix=EVENT_MATRIX_CACHE_PREFIX)
    except Exception:  # noqa: BLE001 — missing local ADC is expected
        return None


def event_matrix_cache_key() -> str:
    """Version-keyed identity for the complete registry × factor matrix."""
    payload = "|".join(
        (
            EVENT_MATRIX_CACHE_VERSION,
            events_version(),
            factor_universe_version(),
            MARKET_CACHE_VERSION,
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"full_{digest}"


def _healthy_event_matrix(matrix: pd.DataFrame, event_ids: list[str]) -> bool:
    """Structural gate: reject shape drift, missing events, or an all-NaN row.

    Deliberately tolerant of NaN holes — a factor ETF that did not exist during an
    event window legitimately has no return. Distinguishing those from provider
    failures needs the whole registry, so that check lives in
    `_transient_hole_events` and gates CACHING only (see `_cacheable_event_matrix`).
    """
    return (
        isinstance(matrix, pd.DataFrame)
        and list(matrix.index) == event_ids
        and list(matrix.columns) == list(FACTORS)
        and not matrix.index.has_duplicates
        and not matrix.columns.has_duplicates
        and not matrix.isna().all(axis=1).any()
    )


def _transient_hole_events(
    matrix: pd.DataFrame,
    registry: dict[str, HistoricalEvent],
) -> list[str]:
    """Event ids whose NaNs cannot be explained by a factor pre-dating its ETF.

    An ETF that traded during one window still trades in every LATER one, so a NaN
    appearing after a factor's first observation is provably a provider failure
    (rate limit, outage) rather than a pre-launch gap — `app/data/market.py` drops
    tickers it fails to fetch, making the two indistinguishable cell-by-cell but
    trivially separable across a chronologically ordered registry.

    This matters because the full matrix is persisted for 30 days AND (since the
    selected-event path started reusing it) grounds the LLM's shock proposal: one
    flaked window would otherwise thin `count` and shift `p10`/`p90` for a month.

    Known residual: a flake on the EARLIEST window covering a factor is
    indistinguishable from pre-launch and is accepted. Closing that needs true
    per-ETF inception dates; monotonicity needs no external data and cannot be wrong.
    """
    if any(event_id not in registry for event_id in matrix.index):
        return list(matrix.index)
    chronological = sorted(matrix.index, key=lambda event_id: registry[event_id].start_date)
    observed = matrix.loc[chronological].notna()
    # True from each factor's first observation onward (inclusive).
    live = observed.cumsum(axis=0) > 0
    holes = live & ~observed
    return [event_id for event_id in chronological if bool(holes.loc[event_id].any())]


def _cacheable_event_matrix(
    matrix: pd.DataFrame,
    registry: dict[str, HistoricalEvent],
) -> bool:
    """Full-registry gate: structurally healthy AND free of transient NaN holes.

    Structure is checked FIRST — `_transient_hole_events` indexes by event id and
    assumes a well-formed frame.
    """
    return _healthy_event_matrix(matrix, list(registry)) and not _transient_hole_events(
        matrix, registry
    )


def _require_healthy_event_matrix(
    matrix: pd.DataFrame,
    event_ids: list[str],
) -> None:
    if not _healthy_event_matrix(matrix, event_ids):
        raise RuntimeError("Fetched event-return matrix is incomplete or malformed")


def _remember_event_matrix(key: str, matrix: pd.DataFrame) -> None:
    with _events_lock:
        _events_matrix_cache.clear()
        _events_matrix_cache[key] = matrix


def _read_persistent_event_matrix(
    key: str,
    registry: dict[str, HistoricalEvent],
) -> pd.DataFrame | None:
    cache = get_event_matrix_cache()
    if cache is None:
        return None
    try:
        matrix = cache.get(key, ttl_hours=EVENT_MATRIX_CACHE_TTL_HOURS)
    except Exception:  # noqa: BLE001 — persistence is a best-effort speed layer
        return None
    # Re-gate on read, not just on write: a blob poisoned by an earlier release (or
    # by a fetch that flaked before this check existed) would otherwise keep serving
    # for the rest of its 30-day TTL. Rejecting it here re-fetches and self-heals.
    if matrix is None or not _cacheable_event_matrix(matrix, registry):
        return None
    _remember_event_matrix(key, matrix)
    return matrix


def get_cached_event_returns_matrix() -> pd.DataFrame | None:
    """Return the complete matrix only when already process- or GCS-cached.

    This never starts the expensive full-registry fetch. Scenario runs use it
    before falling back to their 2–5 selected events, so a normal cold run never
    waits for background population of all historical windows.
    """
    key = event_matrix_cache_key()
    with _events_lock:
        hit = _events_matrix_cache.get(key)
    if hit is not None:
        return hit
    return _read_persistent_event_matrix(key, load_events())


def get_selected_event_returns_matrix(
    event_ids: list[str],
    *,
    registry: dict[str, HistoricalEvent] | None = None,
) -> pd.DataFrame:
    """Reuse the complete cache when present; otherwise fetch selected events only.

    `registry` narrows the admissible events — backdated runs pass an as-of-filtered
    registry, and an id outside it is a look-ahead leak. The check is applied on BOTH
    paths: the miss path gets it from `fetch_event_returns_matrix`, the hit path
    needs it here, because serving out of the full-registry cache would otherwise
    bypass the only enforcement point whenever the warm matrix happens to be present.

    Deliberately NOT single-flight, unlike every other getter here: the sibling
    fetch lock is held across the ~31-event full-registry fan-out, so sharing it
    would make a cold scenario run wait on background warming — exactly what
    `get_cached_event_returns_matrix` exists to avoid. Concurrent duplicate
    selections are deduplicated a layer down by the 24h GCS market cache instead.

    Raises:
        ValueError: empty or duplicate `event_ids`.
        KeyError: an id outside `registry`.
        RuntimeError: the fetched matrix is structurally unusable (transient
            provider failure) — surfaces as a coded 503.
    """
    if not event_ids:
        raise ValueError("event_ids must be non-empty")
    duplicates = {event_id for event_id in event_ids if event_ids.count(event_id) > 1}
    if duplicates:
        raise ValueError(f"duplicate event_ids: {sorted(duplicates)}")
    if registry is not None:
        unknown = [event_id for event_id in event_ids if event_id not in registry]
        if unknown:
            raise KeyError(f"unknown event_ids: {unknown}")
    full = get_cached_event_returns_matrix()
    if full is not None and all(event_id in full.index for event_id in event_ids):
        return full.loc[event_ids].copy()
    matrix = fetch_event_returns_matrix(event_ids, registry=registry)
    _require_healthy_event_matrix(matrix, event_ids)
    return matrix


def get_event_returns_matrix() -> pd.DataFrame:
    """Process-cached events × factors matrix for the FULL registry.

    Historical event windows never change, so the matrix is deterministic per
    `events_version` (the registry content hash) modulo provider data revisions
    — safe to hold for the process lifetime. This matters operationally: deep
    -vintage windows contain pre-launch ETFs, making those batches uncacheable
    in the GCS market cache (complete batches only), so an uncached full-registry
    fetch re-fires ~20+ live provider downloads every time. Same degraded-result
    rule as the factor cache, at two strengths: a row that is ENTIRELY NaN means
    the provider returned nothing for that event (transient failure, e.g. a rate
    limit) and the matrix is REJECTED outright; a matrix carrying transient NaN
    holes (a factor absent from a window later than one it already traded in — see
    `_transient_hole_events`) is returned to the caller but never memoized, so the
    next call retries instead of baking a provider outage into the 30-day parquet.
    Only genuine pre-launch gaps cache. Fetches are single-flight (see
    `_fetch_lock` note); a degraded fetch releases the lock and the next caller
    retries serially.
    """
    key = event_matrix_cache_key()
    registry = load_events()
    event_ids = list(registry)
    with _events_lock:
        hit = _events_matrix_cache.get(key)
    if hit is not None:
        return hit

    with _events_fetch_lock:
        with _events_lock:
            hit = _events_matrix_cache.get(key)
        if hit is not None:
            return hit
        persistent = _read_persistent_event_matrix(key, registry)
        if persistent is not None:
            return persistent

        matrix = fetch_event_returns_matrix(event_ids, registry=registry)
        _require_healthy_event_matrix(matrix, event_ids)
        holes = _transient_hole_events(matrix, registry)
        if holes:
            logger.warning(
                "Event-return matrix has transient provider gaps for %s — serving uncached",
                ", ".join(holes),
            )
            return matrix
        _remember_event_matrix(key, matrix)
        cache = get_event_matrix_cache()
        if cache is not None:
            with contextlib.suppress(Exception):
                cache.put(key, matrix)
        return matrix


def get_factor_returns_with_history(
    lookback_weeks: int = 156,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Cached `fetch_factor_returns_with_history` — see that function for semantics.

    Keyed only on `lookback_weeks`; `end` defaults to None (today) in the
    underlying call. Callers that need an explicit `end` should bypass this
    cache and call `fetch_factor_returns_with_history` directly. A degraded
    `(raw, None)` result (SHAP background unavailable) is passed through but
    never memoized, so a healthy later fetch can repopulate it. Fetches are
    single-flight (see `_fetch_lock` note).
    """
    with _lock:
        hit = _cache.get(lookback_weeks)
    if hit is not None:
        return hit

    with _fetch_lock:
        with _lock:
            hit = _cache.get(lookback_weeks)
        if hit is not None:
            return hit
        result = fetch_factor_returns_with_history(lookback_weeks=lookback_weeks)
        if result[1] is not None:
            with _lock:
                if lookback_weeks not in _cache and len(_cache) >= _MAX_ENTRIES:
                    _cache.pop(next(iter(_cache)))
                _cache[lookback_weeks] = result
        return result


def warm() -> None:
    """Optional startup hook — pre-populate the cache before the first scenario.

    FastAPI lifespan example:

        @asynccontextmanager
        async def lifespan(app):
            warm()
            yield
    """
    # Warming must never break startup.
    with contextlib.suppress(Exception):
        get_factor_returns_with_history()


def clear() -> None:
    """Test helper — drop the in-process caches."""
    with _lock:
        _cache.clear()
    with _events_lock:
        _events_matrix_cache.clear()
