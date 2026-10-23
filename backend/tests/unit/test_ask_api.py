"""Ask API checks that happen before any database or model call."""

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.main import create_app
from uaw.services import Services


def client() -> TestClient:
    app = create_app(Settings(_env_file=None, app_env="test"))
    services = Services(session_factory=cast(Any, None), runner=None, retriever=None, answerer=None)
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)  # not entered: the lifespan (database) does not run


@pytest.mark.parametrize(
    "body",
    [
        {"repository": "nope", "question": "Where?"},
        {"repository": "o/r", "question": ""},
        {"repository": "o/r", "question": " \n "},
        {"repository": "o/r", "question": "x" * 2001},
        {"repository": "o/r"},
    ],
)
def test_invalid_requests_are_rejected(body: dict[str, Any]) -> None:
    assert client().post("/ask", json=body).status_code == 422


def test_answers_are_refused_without_api_keys() -> None:
    response = client().post("/ask", json={"repository": "o/r", "question": "Where?"})

    assert response.status_code == 503
    assert "Anthropic" in response.json()["detail"]
