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
