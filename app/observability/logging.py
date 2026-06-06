"""Structured JSON logging for Cloud Logging.

A ~single-class stdlib formatter (no structlog) that emits one JSON line per record
with Cloud-Logging-friendly keys. The request id is pulled from the contextvar in
`app.observability.context`, so existing module loggers gain correlation for free.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.observability.context import current_request_id

# Standard LogRecord attributes we never want to duplicate into the JSON `extra`.
_RESERVED = set(logging.makeLogRecord({}).__dict__.keys()) | {"message", "asctime", "taskName"}

# Map Python levels to Cloud Logging severities.
_SEVERITY = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": _SEVERITY.get(record.levelname, record.levelname),
            "message": record.getMessage(),
            "logger": record.name,
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        request_id = current_request_id()
        if request_id:
            payload["request_id"] = request_id

        # Promote any structured `extra=` fields (e.g. path, status, latency_ms).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    # Replace existing handlers so we don't double-log under uvicorn.
    root.handlers = [handler]
