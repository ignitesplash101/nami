from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.api.main import api
from app.api.middleware import REQUEST_ID_HEADER, client_ip
from app.observability.context import hash_ip
from app.observability.logging import JsonFormatter, configure_logging


class _FakeReq:
    def __init__(self, xff: str | None = None, peer: str = "10.0.0.1") -> None:
        self.headers = {"X-Forwarded-For": xff} if xff else {}
        self.client = type("C", (), {"host": peer})()


@pytest.fixture
def client():
    return TestClient(api)


def test_response_carries_request_id(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers.get(REQUEST_ID_HEADER)


def test_inbound_request_id_is_echoed(client):
    resp = client.get("/api/health", headers={REQUEST_ID_HEADER: "abc123"})
    assert resp.headers.get(REQUEST_ID_HEADER) == "abc123"


def test_json_formatter_emits_valid_json_with_extra():
    record = logging.LogRecord(
        name="nami.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request",
        args=(),
        exc_info=None,
    )
    record.path = "/api/health"
    record.status = 200
    line = JsonFormatter().format(record)
    payload = json.loads(line)
    assert payload["message"] == "request"
    assert payload["path"] == "/api/health"
    assert payload["status"] == 200
    assert payload["severity"] == "INFO"


def test_hash_ip_is_stable_and_non_raw():
    assert hash_ip("1.2.3.4") == hash_ip("1.2.3.4")
    assert "1.2.3.4" not in hash_ip("1.2.3.4")
    assert hash_ip(None) == "unknown"


def test_client_ip_reads_rightmost_routable_ignoring_spoof():
    # Attacker-prepended left entries are ignored; rightmost routable wins, so a
    # spoofed X-Forwarded-For cannot change (or reset) the per-IP key.
    assert client_ip(_FakeReq("8.8.8.8")) == "8.8.8.8"
    assert client_ip(_FakeReq("1.1.1.1, 8.8.8.8")) == "8.8.8.8"
    assert client_ip(_FakeReq("9.9.9.9, 8.8.8.8")) == "8.8.8.8"
    # No routable hop in XFF -> fall back to the direct peer.
    assert client_ip(_FakeReq("10.0.0.5, 192.168.0.1", peer="7.7.7.7")) == "7.7.7.7"


def test_configure_logging_installs_json_handler():
    configure_logging("INFO")
    root = logging.getLogger()
    assert any(isinstance(h.formatter, JsonFormatter) for h in root.handlers)
