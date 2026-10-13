"""API checks that happen before any database access."""

from typing import Any, cast

from fastapi.testclient import TestClient

from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.ingestion.runner import IngestionRunner
from uaw.main import create_app
from uaw.services import Services


def client_with(runner: IngestionRunner | None) -> TestClient:
    app = create_app(Settings(_env_file=None, app_env="test"))
    # The session factory must not be used by these requests.
    services = Services(session_factory=cast(Any, None), runner=runner, retriever=None)
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)  # not entered: the lifespan (database) does not run


def test_invalid_url_is_rejected_with_a_helpful_message() -> None:
    response = client_with(runner=None).post(
        "/imports", json={"url": "https://gitlab.com/octo/demo"}
    )

    assert response.status_code == 422
    assert "github" in response.json()["detail"].lower()


def test_imports_are_refused_without_embedding_key() -> None:
    response = client_with(runner=None).post(
        "/imports", json={"url": "https://github.com/octo/demo"}
    )

    assert response.status_code == 503
    assert "embedding" in response.json()["detail"]


def test_job_id_must_be_a_uuid() -> None:
    assert client_with(runner=None).get("/imports/not-a-uuid").status_code == 422
