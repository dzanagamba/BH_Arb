"""P1-2: request correlation ids on responses and log records."""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from server import api as api_module
from server import app as app_module
from server.app import app
from server.observability import (
    ContextLogFilter,
    JsonLogFormatter,
    configure_logging,
    reset_request_id,
    set_request_id,
)

client = TestClient(app)


def _request_id_header(response) -> str:
    return response.headers[app_module.REQUEST_ID_HEADER]


def test_incoming_request_id_is_echoed():
    response = client.get("/api/health", headers={"X-Request-ID": "scan-42:prematch"})

    assert response.status_code == 200
    assert _request_id_header(response) == "scan-42:prematch"


def test_missing_request_id_is_generated():
    response = client.get("/api/health")

    generated = _request_id_header(response)
    assert generated
    assert generated != "-"


def test_a_log_injecting_header_is_replaced():
    hostile = "abc\nlevel=CRITICAL"
    response = client.get("/api/health", headers={"X-Request-ID": hostile})

    generated = _request_id_header(response)
    assert generated != hostile
    assert "\n" not in generated
    assert app_module.valid_request_id(generated)


def test_an_oversized_header_is_replaced():
    response = client.get("/api/health", headers={"X-Request-ID": "a" * 200})

    generated = _request_id_header(response)
    assert generated != "a" * 200
    assert len(generated) <= 128


def test_the_id_survives_on_a_refused_request(monkeypatch):
    """A 401 still carries the id, so the log line can be tied to the caller."""
    monkeypatch.setattr(api_module, "API_KEY", "secret")
    response = client.get("/api/metrics", headers={"X-Request-ID": "refused-1"})

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "refused-1"


def test_context_filter_attaches_ids_to_every_record(caplog):
    token = set_request_id("req-abc")
    try:
        with caplog.at_level(logging.INFO):
            logging.getLogger("bh.test").info("hello")
    finally:
        reset_request_id(token)

    record = caplog.records[-1]
    assert record.request_id == "req-abc"
    assert record.scan_id == "-"


def test_json_formatter_keeps_known_fields_and_drops_unknown_ones():
    record = logging.LogRecord(
        name="server.api",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="scan complete",
        args=(),
        exc_info=None,
    )
    ContextLogFilter().filter(record)
    record.request_id = "req-1"
    record.scan_id = "scan-1"
    record.mode = "prematch"
    record.duration_seconds = 1.25
    record.books = 9
    # Not in the allowlist: this must never reach the log line.
    record.api_key = "super-secret"
    record.odds_payload = {"1": 2.1, "X": 3.2, "2": 3.4}

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["message"] == "scan complete"
    assert payload["request_id"] == "req-1"
    assert payload["scan_id"] == "scan-1"
    assert payload["mode"] == "prematch"
    assert payload["duration_seconds"] == 1.25
    assert payload["books"] == 9
    text = json.dumps(payload)
    assert "super-secret" not in text
    assert "odds_payload" not in text


def test_json_formatter_includes_the_traceback():
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord(
            name="server.api",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="scan failed",
            args=(),
            exc_info=__import__("sys").exc_info(),
        )
    ContextLogFilter().filter(record)

    payload = json.loads(JsonLogFormatter().format(record))

    assert "RuntimeError: boom" in payload["exception"]


def test_configure_logging_can_switch_to_json():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        configure_logging("DEBUG", "json")
        assert isinstance(root.handlers[0].formatter, JsonLogFormatter)
        assert root.level == logging.DEBUG
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
