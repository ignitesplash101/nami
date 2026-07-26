"""Request-scoped context: a correlation id and a hashed client IP.

Stored in `contextvars` so library loggers (`logging.getLogger(__name__)` across
the app) pick up the request id with no signature changes. The SSE endpoints spawn
worker threads which do NOT inherit contextvars automatically — those code paths
must propagate the context explicitly via `contextvars.copy_context().run(...)`
(see `app/api/main.py`).
"""

from __future__ import annotations

import hashlib
import uuid
from contextvars import ContextVar

# Module-level salt only obscures raw IPs in logs/Firestore; it is not a secret.
# A per-process random salt would break cross-instance lockout keying, so the salt
# is intentionally static.
_IP_SALT = "nami.v1"

request_id_var: ContextVar[str | None] = ContextVar("nami_request_id", default=None)
ip_hash_var: ContextVar[str | None] = ContextVar("nami_ip_hash", default=None)

# Non-personal dimensions a handler may attach to its own access-log line. An
# ALLOWLIST, not free-form: `logging` raises if an `extra` key collides with a
# LogRecord attribute, so an unchecked tag name would break logging at runtime.
USAGE_TAGS = frozenset(
    {"access_mode", "scenario_key", "portfolio_key", "cache_hit", "synthetic", "error_code"}
)

usage_tags_var: ContextVar[dict[str, object] | None] = ContextVar("nami_usage_tags", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex


def hash_ip(ip: str | None) -> str:
    """Stable, non-reversible hash of a client IP (never store raw IPs)."""
    if not ip:
        return "unknown"
    digest = hashlib.sha256(f"{_IP_SALT}:{ip}".encode()).hexdigest()
    return digest[:16]


def current_request_id() -> str | None:
    return request_id_var.get()


def current_ip_hash() -> str | None:
    return ip_hash_var.get()


def start_usage_tags() -> dict[str, object]:
    """Install a fresh, MUTABLE tag bag for this request and return it.

    Mutable-dict-in-a-contextvar rather than repeated `.set()` calls, deliberately:
    FastAPI runs sync (`def`) endpoints in a threadpool with a *copied* context, so
    a handler rebinding the var would be invisible to the middleware that writes the
    access-log line. Both contexts reference the same dict object, so mutating it
    propagates. The SSE worker threads (`copy_context().run(...)`) work the same way.
    """
    tags: dict[str, object] = {}
    usage_tags_var.set(tags)
    return tags


def tag_request(**tags: object) -> None:
    """Attach non-personal dimensions to this request's access-log line.

    Silently ignores unknown keys (see `USAGE_TAGS`) and `None` values, so a caller
    can pass an optional field without branching. No-op outside a request.
    """
    bag = usage_tags_var.get()
    if bag is None:
        return
    bag.update({k: v for k, v in tags.items() if k in USAGE_TAGS and v is not None})


def current_usage_tags() -> dict[str, object]:
    """Snapshot of this request's tags, safe to splat into a logging `extra`."""
    return dict(usage_tags_var.get() or {})
