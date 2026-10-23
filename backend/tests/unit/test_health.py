from typing import Any, cast

from fastapi.testclient import TestClient

from uaw import __version__
from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.main import create_app
from uaw.services import Services


def test_health_returns_ok() -> None:
    client = TestClient(create_app(Settings(_env_file=None, app_env="test")))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def unreachable_database() -> Any:
    raise OSError("connection refused")


def test_readiness_fails_when_the_database_is_unreachable() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))
    services = Services(
        session_factory=cast(Any, unreachable_database), runner=None, retriever=None, answerer=None
    )
    app.dependency_overrides[get_services] = lambda: services

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "The database is unreachable."}
