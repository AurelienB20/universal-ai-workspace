"""Application settings, loaded from environment variables (and an optional .env file).

Settings are validated at startup so that a misconfiguration fails fast with a clear
error instead of surfacing later in the middle of a request.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LogFormat = Literal["text", "json"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "test", "production"] = "local"
    log_level: LogLevel = "INFO"
    # "json": one JSON object per line, for a log collector (production).
    log_format: LogFormat = "text"

    # API protection. Clients send the key in the X-API-Key header. It is required in
    # production; without it (local development), the API is open.
    api_key: SecretStr | None = None
    # Requests per client IP address, counted in memory by each process. 0 = no limit.
    rate_limit_imports_per_hour: int = Field(default=10, ge=0)
    rate_limit_search_per_minute: int = Field(default=60, ge=0)
    rate_limit_ask_per_minute: int = Field(default=10, ge=0)
    max_request_body_kb: int = Field(default=64, gt=0, le=1024)

    # Cost control: tokens per UTC day, all clients combined. 0 = no budget. Once a
    # budget is spent, new requests needing that provider are refused until midnight
    # UTC; a request already running is allowed to finish.
    daily_embedding_token_budget: int = Field(default=0, ge=0)
    daily_llm_token_budget: int = Field(default=0, ge=0)

    # GitHub connector. A token is optional: it raises the API rate limit from
    # 60 to 5,000 requests per hour. No scope is needed for public repositories.
    github_token: SecretStr | None = None
    github_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    github_download_timeout_seconds: float = Field(default=120.0, gt=0, le=900)

    # Repository import limits.
    max_repo_size_mb: int = Field(default=200, gt=0)  # GitHub-reported size (incl. history)
    max_archive_mb: int = Field(default=50, gt=0)  # compressed tarball
    max_uncompressed_mb: int = Field(default=300, gt=0)  # all archive entries combined
    max_archive_entries: int = Field(default=50_000, gt=0)
    max_file_kb: int = Field(default=256, gt=0)  # larger files are skipped
    max_files: int = Field(default=3_000, gt=0)  # indexed files per repository

    # PostgreSQL with pgvector. The default matches docker-compose.yml (local only).
    # Secret because the URL contains the password.
    database_url: SecretStr = SecretStr("postgresql+asyncpg://uaw:uaw@127.0.0.1:5432/uaw")
    database_pool_size: int = Field(default=5, gt=0, le=50)

    # Embeddings (Voyage AI). Without a key, imports are refused with a clear error.
    voyage_api_key: SecretStr | None = None
    embedding_model: str = "voyage-code-3"
    voyage_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    voyage_max_retries: int = Field(default=4, ge=0, le=10)
    # Voyage accepts up to 1,000 texts and 120K tokens per voyage-code-3 request. The
    # character budget assumes the worst case of ~2 characters per token.
    embedding_batch_size: int = Field(default=128, gt=0, le=1000)
    embedding_batch_max_chars: int = Field(default=200_000, gt=0, le=240_000)

    # Imports run in the API process, at most this many at a time.
    max_concurrent_imports: int = Field(default=2, gt=0, le=10)

    # Answer generation (Claude). Without a key, questions are refused with a clear error.
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    # Claude Opus 5.5 always thinks: effort is the only depth control. Its API default
    # is "medium"; it is set explicitly so that a model change cannot alter it silently.
    llm_effort: Effort = "medium"
    llm_max_tokens: int = Field(default=2_000, gt=0, le=64_000)
    llm_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    # On a safety refusal, the API retries the request on a model it picks for the
    # refusal category, inside the same call.
    llm_refusal_fallback: bool = True
    # Passages retrieved and shown to the model for each question.
    answer_top_k: int = Field(default=8, gt=0, le=20)

    @field_validator(
        "api_key", "github_token", "voyage_api_key", "anthropic_api_key", mode="before"
    )
    @classmethod
    def _empty_secret_is_none(cls, value: object) -> object:
        # ``GITHUB_TOKEN=`` in a .env file means "no token", not an empty credential.
        return None if value == "" else value

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg_driver(cls, value: SecretStr) -> SecretStr:
        # The storage layer is asynchronous and only supports the asyncpg driver.
        if not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must start with 'postgresql+asyncpg://'")
        return value

    @model_validator(mode="after")
    def _require_api_key_in_production(self) -> Self:
        # A public server without a key would let anyone spend the provider budgets.
        if self.app_env == "production" and self.api_key is None:
            raise ValueError("API_KEY is required when APP_ENV=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
