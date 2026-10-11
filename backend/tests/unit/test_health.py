from fastapi.testclient import TestClient

from uaw import __version__
from uaw.config import Settings
from uaw.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app(Settings(_env_file=None, app_env="test")))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
