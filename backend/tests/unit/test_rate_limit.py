from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from uaw.api.deps import get_services
from uaw.api.ratelimit import ConcurrencyLimiter, RateLimiter
from uaw.config import Settings
from uaw.main import create_app
from uaw.services import Services


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_allows_the_limit_then_asks_to_wait() -> None:
    clock = FakeClock()
    limiter = RateLimiter(3, 60, clock=clock)

    assert [limiter.acquire("a") for _ in range(3)] == [0, 0, 0]
    # One request is refilled every 20 seconds.
    assert limiter.acquire("a") == pytest.approx(20)


def test_requests_are_refilled_over_time() -> None:
    clock = FakeClock()
    limiter = RateLimiter(3, 60, clock=clock)
    for _ in range(3):
        limiter.acquire("a")

    clock.now = 20
    assert limiter.acquire("a") == 0
    assert limiter.acquire("a") > 0


def test_clients_are_limited_separately() -> None:
    limiter = RateLimiter(1, 60, clock=FakeClock())

    assert limiter.acquire("a") == 0
    assert limiter.acquire("b") == 0
    assert limiter.acquire("a") > 0


def test_least_recently_seen_client_is_forgotten_when_full() -> None:
    limiter = RateLimiter(1, 60, max_clients=2, clock=FakeClock())
    limiter.acquire("a")
    limiter.acquire("b")
    limiter.acquire("c")  # evicts "a"

    assert limiter.acquire("a") == 0  # a fresh bucket
    assert limiter.acquire("c") > 0


def client(**settings: Any) -> TestClient:
    app = create_app(Settings(_env_file=None, app_env="test", **settings))
    services = Services(session_factory=cast(Any, None), runner=None, retriever=None, answerer=None)
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


def test_api_returns_429_with_retry_after() -> None:
    http = client(rate_limit_ask_per_minute=2)
    body = {"repository": "o/r", "question": "Where?"}

    # Answers are disabled (503), but each request still counts.
    assert [http.post("/ask", json=body).status_code for _ in range(2)] == [503, 503]
    response = http.post("/ask", json=body)

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) == 30


def test_zero_disables_a_limit() -> None:
    http = client(rate_limit_ask_per_minute=0)
    body = {"repository": "o/r", "question": "Where?"}

    assert {http.post("/ask", json=body).status_code for _ in range(20)} == {503}


def test_concurrency_limiter_refuses_beyond_the_limit_then_frees_slots() -> None:
    limiter = ConcurrencyLimiter(2)

    with limiter.slot(), limiter.slot():
        with pytest.raises(HTTPException) as exc_info, limiter.slot():
            pass
        assert exc_info.value.status_code == 503
        assert exc_info.value.headers == {"Retry-After": "5"}

    with limiter.slot():  # both slots were released
        pass


def test_concurrency_limiter_frees_the_slot_when_the_operation_fails() -> None:
    limiter = ConcurrencyLimiter(1)

    with pytest.raises(RuntimeError), limiter.slot():
        raise RuntimeError("model unavailable")

    with limiter.slot():
        pass
