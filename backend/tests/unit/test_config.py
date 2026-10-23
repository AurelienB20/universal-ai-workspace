import pytest
from pydantic import ValidationError

from uaw.config import Settings


def test_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "local"
    assert settings.log_level == "INFO"


def test_reads_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_KEY", "server-key")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "server-key"
    assert settings.log_level == "DEBUG"


def test_production_requires_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_KEY", "")  # empty means "not set"

    with pytest.raises(ValidationError, match="API_KEY"):
        Settings(_env_file=None)


def test_invalid_value_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_url_requires_asyncpg_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://uaw:uaw@localhost:5432/uaw")

    with pytest.raises(ValidationError, match="asyncpg"):
        Settings(_env_file=None)


def test_database_url_is_hidden_from_repr() -> None:
    settings = Settings(_env_file=None)

    assert "uaw:uaw@" not in repr(settings)
