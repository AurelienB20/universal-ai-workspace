from typing import Any

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
    monkeypatch.setenv("DAILY_EMBEDDING_TOKEN_BUDGET", "5000000")
    monkeypatch.setenv("DAILY_LLM_TOKEN_BUDGET", "1000000")
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


@pytest.mark.parametrize("missing", ["DAILY_EMBEDDING_TOKEN_BUDGET", "DAILY_LLM_TOKEN_BUDGET"])
def test_production_requires_both_budgets(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_KEY", "server-key")
    monkeypatch.setenv("DAILY_EMBEDDING_TOKEN_BUDGET", "5000000")
    monkeypatch.setenv("DAILY_LLM_TOKEN_BUDGET", "1000000")
    monkeypatch.setenv(missing, "0")

    with pytest.raises(ValidationError, match=missing):
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


def test_demo_repositories_are_parsed_from_a_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_REPOSITORIES", " Pallets/Flask, octo/demo ,,")

    settings = Settings(_env_file=None)

    assert settings.demo_repositories == frozenset({"pallets/flask", "octo/demo"})


def test_invalid_demo_repository_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_REPOSITORIES", "https://github.com/pallets/flask")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_demo_key_requires_an_admin_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_API_KEY", "demo-key")

    with pytest.raises(ValidationError, match="requires API_KEY"):
        Settings(_env_file=None)


def test_demo_key_must_differ_from_the_admin_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "same-key")
    monkeypatch.setenv("DEMO_API_KEY", "same-key")

    with pytest.raises(ValidationError, match="must differ"):
        Settings(_env_file=None)


def test_reranking_adds_to_the_voyage_reservation() -> None:
    without = Settings(_env_file=None, rerank_model="")
    with_reranker = Settings(_env_file=None, rerank_model="rerank-3")

    assert without.query_reserved_voyage_tokens == without.query_reserved_embedding_tokens
    assert with_reranker.query_reserved_voyage_tokens == (
        with_reranker.query_reserved_embedding_tokens + with_reranker.rerank_reserved_tokens
    )


def test_public_imports_require_a_demo_key() -> None:
    with pytest.raises(ValidationError, match="PUBLIC_IMPORTS_ENABLED requires DEMO_API_KEY"):
        Settings(_env_file=None, public_imports_enabled=True, api_key="admin")


def test_visitor_imports_must_leave_room_in_the_embedding_budget() -> None:
    keys: dict[str, Any] = {
        "api_key": "admin",
        "demo_api_key": "demo",
        "public_imports_enabled": True,
    }
    # 20 imports x 400,000 tokens = 8,000,000 tokens a day at most.
    with pytest.raises(ValidationError, match=r"must exceed what visitor imports"):
        Settings(_env_file=None, daily_embedding_token_budget=8_000_000, **keys)

    settings = Settings(_env_file=None, daily_embedding_token_budget=13_000_000, **keys)
    assert settings.visitor_daily_embedding_tokens == 8_000_000


def test_public_imports_are_off_by_default() -> None:
    assert Settings(_env_file=None).public_imports_enabled is False
