import json
import logging
from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.logging_config import JsonFormatter, RequestIdFilter, request_id_var
from uaw.main import create_app
from uaw.services import Services


def client(**settings: Any) -> TestClient:
    app = create_app(Settings(_env_file=None, app_env="test", **settings))
    services = Services(session_factory=cast(Any, None), runner=None, retriever=None, answerer=None)
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


def test_each_response_gets_a_request_id() -> None:
    http = client()

    first = http.get("/health").headers["X-Request-ID"]
    second = http.get("/health").headers["X-Request-ID"]

    assert len(first) == 32
    assert first != second


def test_a_safe_incoming_request_id_is_kept() -> None:
    response = client().get("/health", headers={"X-Request-ID": "proxy-42.a_b"})

    assert response.headers["X-Request-ID"] == "proxy-42.a_b"


@pytest.mark.parametrize("unsafe", ["a" * 65, "line\nbreak", 'quote"d', ""])
def test_an_unsafe_incoming_request_id_is_replaced(unsafe: str) -> None:
    response = client().get("/health", headers={"X-Request-ID": unsafe})

    assert response.headers["X-Request-ID"] != unsafe


class Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def access_log() -> Iterator[Collector]:
    # Attached to the logger itself: create_app() reconfigures the root handlers.
    collector = Collector()
    access_logger = logging.getLogger("uaw.access")
    access_logger.addHandler(collector)
    yield collector
    access_logger.removeHandler(collector)


def test_requests_are_logged_with_status_and_duration(access_log: Collector) -> None:
    client().post("/ask", json={"repository": "o/r", "question": "Where?"})

    [record] = access_log.records
    assert record.getMessage().startswith("POST /ask 503 ")
    assert vars(record)["status"] == 503
    assert isinstance(vars(record)["duration_ms"], int)


def test_health_probes_are_not_logged(access_log: Collector) -> None:
    client().get("/health")

    assert access_log.records == []


def test_oversized_body_is_rejected_before_parsing() -> None:
    http = client(max_request_body_kb=1)

    response = http.post(
        "/ask",
        content=json.dumps({"repository": "o/r", "question": "x" * 2000}),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.headers["X-Request-ID"]


def test_streamed_oversized_body_is_rejected() -> None:
    def chunks() -> Iterator[bytes]:  # no Content-Length: chunked transfer
        yield b'{"repository": "o/r", "question": "'
        yield b"x" * 2000
        yield b'"}'

    response = client(max_request_body_kb=1).post(
        "/ask", content=chunks(), headers={"content-type": "application/json"}
    )

    assert response.status_code == 413


def test_body_within_the_limit_reaches_the_route() -> None:
    response = client(max_request_body_kb=1).post(
        "/ask", json={"repository": "o/r", "question": "Where?"}
    )

    assert response.status_code == 503  # answers disabled, but the body was read


def log_record(**extra: Any) -> logging.LogRecord:
    record = logging.makeLogRecord(
        {"name": "uaw.test", "levelname": "INFO", "msg": "hello %s", "args": ("world",)} | extra
    )
    RequestIdFilter().filter(record)
    return record


def test_json_logs_carry_the_request_id_and_extra_fields() -> None:
    token = request_id_var.set("req-1")
    try:
        record = log_record(status=200)
    finally:
        request_id_var.reset(token)

    entry = json.loads(JsonFormatter().format(record))

    assert entry["message"] == "hello world"
    assert entry["level"] == "INFO"
    assert entry["request_id"] == "req-1"
    assert entry["status"] == 200


def test_logs_outside_a_request_have_a_placeholder_id() -> None:
    assert json.loads(JsonFormatter().format(log_record()))["request_id"] == "-"
