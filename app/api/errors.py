"""Machine-readable error codes for API responses.

The `X-Error-Code` response header is the machine-readable error contract;
HTTP detail strings stay display-only (the adjust-shocks 422 detail is
LLM-generated free text, so clients must never classify by string-matching).
Codes are emitted only where the status code alone is ambiguous:

    rate_limited        429 per-IP rate limit / unlock lockout
    budget_exhausted    429 daily LLM cost cap
    run_cap             429 daily scenario run cap
    rerun_required      422 LLM adjustment patch needs a full re-run
    marking_unavailable 503 mark-to-market price/FX unavailable

Everything else derives from the status code client-side.
"""

from __future__ import annotations

from fastapi import HTTPException

ERROR_CODE_HEADER = "X-Error-Code"


def http_error(status_code: int, code: str, message: str) -> HTTPException:
    """HTTPException whose response carries a machine-readable `X-Error-Code`
    header. The detail string is unchanged — the header is the only addition."""
    return HTTPException(status_code=status_code, detail=message, headers={ERROR_CODE_HEADER: code})
