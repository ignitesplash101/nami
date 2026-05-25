from __future__ import annotations

import hashlib
import hmac
import os
from typing import Literal

from dotenv import load_dotenv
from fastapi import Request, Response

load_dotenv()

AccessMode = Literal["visitor", "admin"]

COOKIE_NAME = "nami_admin"
COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
_ADMIN_PAYLOAD = "admin"


def configured_passcode() -> str | None:
    raw = os.getenv("PASSCODE")
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def verify_passcode(candidate: str, expected: str | None = None) -> bool:
    expected_passcode = configured_passcode() if expected is None else expected.strip()
    candidate_passcode = candidate.strip()
    if not expected_passcode or not candidate_passcode:
        return False
    return hmac.compare_digest(candidate_passcode, expected_passcode)


def _signature(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_admin_token(secret: str | None = None) -> str | None:
    secret_value = configured_passcode() if secret is None else secret.strip()
    if not secret_value:
        return None
    return f"{_ADMIN_PAYLOAD}.{_signature(_ADMIN_PAYLOAD, secret_value)}"


def verify_admin_token(token: str | None, secret: str | None = None) -> bool:
    secret_value = configured_passcode() if secret is None else secret.strip()
    if not token or not secret_value or "." not in token:
        return False
    payload, supplied_sig = token.split(".", 1)
    if payload != _ADMIN_PAYLOAD:
        return False
    expected_sig = _signature(payload, secret_value)
    return hmac.compare_digest(supplied_sig, expected_sig)


def access_mode_for_request(request: Request) -> AccessMode:
    return "admin" if verify_admin_token(request.cookies.get(COOKIE_NAME)) else "visitor"


def set_admin_cookie(response: Response, request: Request) -> bool:
    token = create_admin_token()
    if token is None:
        return False
    secure = request.url.scheme == "https" or os.getenv("ENVIRONMENT") == "prod"
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    return True


def clear_admin_cookie(response: Response, request: Request) -> None:
    secure = request.url.scheme == "https" or os.getenv("ENVIRONMENT") == "prod"
    response.delete_cookie(COOKIE_NAME, httponly=True, secure=secure, samesite="lax")


def can_use_custom_portfolio(mode: AccessMode) -> bool:
    return mode == "admin"


def can_use_free_text_scenario(mode: AccessMode) -> bool:
    return mode == "admin"


def can_use_narrative_decomposition(mode: AccessMode) -> bool:
    return mode == "admin"
