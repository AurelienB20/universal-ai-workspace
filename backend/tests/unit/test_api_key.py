from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.main import create_app
from uaw.services import Services

ASK = {"repository": "o/r", "question": "Where?"}
SEARCH = {"repository": "o/r", "query": "q"}
ADMIN = {"X-API-Key": "admin-key"}
DEMO = {"X-API-Key": "demo-key"}


def client(
    api_key: str | None, *, demo_api_key: str | None = None, demo_repositories: str = ""
) -> TestClient:
    settings = Settings(
        _env_file=None,
        app_env="test",
        api_key=SecretStr(api_key) if api_key else None,
        demo_api_key=SecretStr(demo_api_key) if demo_api_key else None,
        demo_repositories=demo_repositories,
    )
    app = create_app(settings)
    services = Services(session_factory=cast(Any, None), runner=None, retriever=None, answerer=None)
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


def demo_client() -> TestClient:
    return client("admin-key", demo_api_key="demo-key", demo_repositories="O/R, pallets/flask")


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
def test_missing_or_wrong_key_is_rejected(headers: dict[str, str]) -> None:
    http = demo_client()

    for method, path, body in [
        ("POST", "/ask", ASK),
        ("POST", "/search", SEARCH),
        ("GET", "/repositories", None),
        ("POST", "/imports", {"url": "https://github.com/o/r"}),
        ("GET", "/imports/00000000-0000-0000-0000-000000000000", None),
    ]:
        response = http.request(method, path, json=body, headers=headers)
        assert response.status_code == 401, path


def test_admin_key_is_accepted() -> None:
    response = demo_client().post("/ask", json=ASK, headers=ADMIN)

    assert response.status_code == 503  # past the key check: answers are disabled


def test_api_is_open_without_a_configured_key() -> None:
    http = client(None)

    assert http.post("/ask", json=ASK).status_code == 503
    assert http.post("/imports", json={"url": "https://github.com/o/r"}).status_code == 503


def test_health_needs_no_key() -> None:
    assert demo_client().get("/health").status_code == 200


def test_demo_key_can_ask_and_search_allowed_repositories() -> None:
    http = demo_client()

    # The allowlist ignores case. 503: past the checks, the providers are disabled.
    assert http.post("/ask", json={**ASK, "repository": "o/R"}, headers=DEMO).status_code == 503
    assert http.post("/search", json=SEARCH, headers=DEMO).status_code == 503


def test_demo_key_cannot_reach_other_repositories() -> None:
    http = demo_client()

    for path, body in [("/ask", ASK), ("/search", SEARCH)]:
        body = {**body, "repository": "secret/repo"}
        response = http.post(path, json=body, headers=DEMO)
        assert response.status_code == 404, path
        # Same answer as a repository that was never imported: nothing is revealed.
        assert response.json()["detail"] == (
            "secret/repo has not been imported yet, or its import is not finished."
        )


def test_admin_key_reaches_every_repository() -> None:
    body = {**ASK, "repository": "secret/repo"}

    assert demo_client().post("/ask", json=body, headers=ADMIN).status_code == 503


def test_demo_key_cannot_import() -> None:
    http = demo_client()

    for method, path, body in [
        ("POST", "/imports", {"url": "https://github.com/o/r"}),
        ("GET", "/imports/00000000-0000-0000-0000-000000000000", None),
    ]:
        assert http.request(method, path, json=body, headers=DEMO).status_code == 403, path
