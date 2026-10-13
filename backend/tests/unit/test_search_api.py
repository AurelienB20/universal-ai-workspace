"""Search API checks that happen before any database or embedding call."""

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.main import create_app
from uaw.retrieval.retriever import Retriever
from uaw.services import Services


def client_with(retriever: Retriever | None) -> TestClient:
    app = create_app(Settings(_env_file=None, app_env="test"))
    services = Services(session_factory=cast(Any, None), runner=None, retriever=retriever)
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)  # not entered: the lifespan (database) does not run


@pytest.mark.parametrize(
    "body",
    [
        {"repository": "pallets", "query": "auth"},
        {"repository": "https://github.com/pallets/flask", "query": "auth"},
        {"repository": "pallets/flask", "query": ""},
        {"repository": "pallets/flask", "query": "   "},
        {"repository": "pallets/flask", "query": "x" * 2001},
        {"repository": "pallets/flask", "query": "auth", "top_k": 0},
        {"repository": "pallets/flask", "query": "auth", "top_k": 51},
    ],
)
def test_invalid_requests_are_rejected(body: dict[str, Any]) -> None:
    assert client_with(retriever=None).post("/search", json=body).status_code == 422


def test_search_is_refused_without_embedding_key() -> None:
    response = client_with(retriever=None).post(
        "/search", json={"repository": "pallets/flask", "query": "Where is routing?"}
    )

    assert response.status_code == 503
    assert "embedding" in response.json()["detail"]
