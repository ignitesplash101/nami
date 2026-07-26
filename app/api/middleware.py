"""HTTP middleware: per-request correlation id + structured access logging.

Also exposes `client_ip`, the single trusted-IP function shared by the rate
limiter and the durable auth lockout so a spoofed header can't reset either.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.observability.context import (
    current_usage_tags,
    hash_ip,
    ip_hash_var,
    new_request_id,
    request_id_var,
    start_usage_tags,
    tag_request,
)

_access_logger = logging.getLogger("nami.access")

REQUEST_ID_HEADER = "X-Request-ID"

# Set by the scheduled pre-warm job so its ~16 weekday runs can be told apart from
# real visitors. Without it the warm is indistinguishable from traffic and would
# dominate every usage metric. Purely a reporting label — it grants nothing.
SYNTHETIC_HEADER = "X-Nami-Synthetic"


def _is_routable(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local)


def client_ip(request: Request) -> str:
    """Best-effort trusted client IP.

    `X-Forwarded-For` is client-controllable, so we read the chain RIGHT-TO-LEFT
    and return the first publicly-routable address. On Cloud Run the real client
    address is appended by Google's front end (its own hops are private ranges),
    while any attacker-prepended fake IPs sit on the LEFT and are ignored. Falls
    back to the direct peer. The durable Firestore lockout + daily budget cap are
    the authoritative backstops; this per-IP key is a coarse first layer.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        for hop in reversed([h.strip() for h in forwarded.split(",") if h.strip()]):
            if _is_routable(hop):
                return hop
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()
    ip_hash = hash_ip(client_ip(request))
    request_id_var.set(request_id)
    ip_hash_var.set(ip_hash)
    start_usage_tags()
    if request.headers.get(SYNTHETIC_HEADER):
        tag_request(synthetic=True)

    start = time.perf_counter()
    response: Response | None = None
    try:
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        _access_logger.info(
            "request",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status": response.status_code if response is not None else 500,
                "latency_ms": latency_ms,
                "ip_hash": ip_hash,
                # Handler-supplied dimensions (access mode, sample keys, cache hit).
                # This is the ONLY place they are recorded — nothing is persisted.
                **current_usage_tags(),
            },
        )
