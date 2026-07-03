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
import threading

import pandas as pd

from app.factors.analogs import events_version, fetch_event_returns_matrix, load_events
from app.factors.regression import fetch_factor_returns_with_history

_MAX_ENTRIES = 4  # covers a handful of distinct lookback_weeks values

_lock = threading.Lock()
_cache: dict[int, tuple[pd.DataFrame, pd.DataFrame]] = {}

_events_lock = threading.Lock()
_events_matrix_cache: dict[str, pd.DataFrame] = {}


def get_event_returns_matrix() -> pd.DataFrame:
    """Process-cached events × factors matrix for the FULL registry.

    Historical event windows never change, so the matrix is deterministic per
    `events_version` (the registry content hash) modulo provider data revisions
    — safe to hold for the process lifetime. This matters operationally: deep
    -vintage windows contain pre-launch ETFs, making those batches uncacheable
    in the GCS market cache (complete batches only), so an uncached full-registry
    fetch re-fires ~20+ live provider downloads every time. Same degraded-result
    rule as the factor cache: a row that is ENTIRELY NaN means the provider
    returned nothing for that event (transient failure, e.g. a rate limit) —
    such a matrix is returned to the caller but never memoized. Legitimate
    pre-launch NaN holes are partial rows and cache fine.
    """
    version = events_version()
    with _events_lock:
        hit = _events_matrix_cache.get(version)
    if hit is not None:
        return hit

    matrix = fetch_event_returns_matrix(list(load_events()))
    if not matrix.isna().all(axis=1).any():
        with _events_lock:
            _events_matrix_cache.clear()  # a registry edit obsoletes prior versions
            _events_matrix_cache[version] = matrix
    return matrix


def get_factor_returns_with_history(
    lookback_weeks: int = 156,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Cached `fetch_factor_returns_with_history` — see that function for semantics.

    Keyed only on `lookback_weeks`; `end` defaults to None (today) in the
    underlying call. Callers that need an explicit `end` should bypass this
    cache and call `fetch_factor_returns_with_history` directly. A degraded
    `(raw, None)` result (SHAP background unavailable) is passed through but
    never memoized, so a healthy later fetch can repopulate it.
    """
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
