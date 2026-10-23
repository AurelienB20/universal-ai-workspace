from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.main import create_app
from uaw.services import Services

ASK = {"repository": "o/r", "question": "Where?"}


def client(api_key: str | None) -> TestClient:
    settings = Settings(
        _env_file=None, app_env="test", api_key=SecretStr(api_key) if api_key else None
    )
    app = create_app(settings)
    services = Services(session_factory=cast(Any, None), runner=None, retriever=None, answerer=None)
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
def test_missing_or_wrong_key_is_rejected(headers: dict[str, str]) -> None:
    http = client("server-key")

    for method, path, body in [
        ("POST", "/ask", ASK),
        ("POST", "/search", {"repository": "o/r", "query": "q"}),
        ("POST", "/imports", {"url": "https://github.com/o/r"}),
        ("GET", "/imports/00000000-0000-0000-0000-000000000000", None),
    ]:
        response = http.request(method, path, json=body, headers=headers)
        assert response.status_code == 401, path


def test_valid_key_is_accepted() -> None:
    response = client("server-key").post("/ask", json=ASK, headers={"X-API-Key": "server-key"})

    assert response.status_code == 503  # past the key check: answers are disabled


def test_api_is_open_without_a_configured_key() -> None:
    assert client(None).post("/ask", json=ASK).status_code == 503


def test_health_needs_no_key() -> None:
    assert client("server-key").get("/health").status_code == 200
