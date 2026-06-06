"""Per-IP rate limiting (slowapi).

Decorator-only: ONLY the paid LLM endpoints and the unlock endpoint are limited.
Static-file serving and the catch-all SPA route are deliberately NOT throttled so
the React app always loads. State is per-instance in memory (acceptable for the
max-2-instance deployment — worst case ~2x the configured limit); the authoritative
backstops for cost/abuse are the Firestore daily budget and unlock lockout.

Limits are read from `Config` via callables so they pick up env overrides at
request time (and stay test-tunable).
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.middleware import client_ip
from app.config import load_config

limiter = Limiter(key_func=client_ip, default_limits=[])


def llm_limit() -> str:
    return load_config().rate_limit_llm


def unlock_limit() -> str:
    return load_config().rate_limit_unlock


def setup_rate_limiting(app: object) -> None:
    app.state.limiter = limiter  # type: ignore[attr-defined]
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[attr-defined]
    app.add_middleware(SlowAPIMiddleware)  # type: ignore[attr-defined]


def _rate_limit_handler(request: object, exc: RateLimitExceeded) -> object:
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded; slow down and retry shortly."},
    )
