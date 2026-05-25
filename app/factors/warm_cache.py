"""Process-lifetime in-memory cache for universe-level fetches.

Sits on top of the Tier-1 GCS market-data cache. Within a single Cloud Run
instance, repeated scenarios reuse the cached return tuple without even hitting
GCS. Across instances or after a restart, the underlying GCS cache (24h TTL)
absorbs the cold-start cost.

Universe-level only — do NOT cache portfolio-keyed fetches here, since the Portfolio
dataclass + custom holdings would explode the cache key space and risk dataclass-hash
subtleties.

FastAPI integration note: this module exposes functions that can be called from a
`lifespan` startup hook to warm the cache before the first request. The cache is a
plain `functools.lru_cache`, not a Streamlit decorator — survives the Streamlit→
FastAPI migration unchanged.
"""

from __future__ import annotations

import contextlib
import functools

import pandas as pd

from app.factors.regression import fetch_factor_returns_with_history


@functools.lru_cache(maxsize=4)
def get_factor_returns_with_history(
    lookback_weeks: int = 156,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Cached `fetch_factor_returns_with_history` — see that function for semantics.

    maxsize=4 covers a handful of distinct `lookback_weeks` values (default 156,
    plus any one-off variations). Keyed only on `lookback_weeks`; `end` defaults to
    None (today) in the underlying call. Callers that need an explicit `end` should
    bypass this cache and call `fetch_factor_returns_with_history` directly.
    """
    return fetch_factor_returns_with_history(lookback_weeks=lookback_weeks)


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
    """Test helper — drop the in-process cache."""
    get_factor_returns_with_history.cache_clear()
