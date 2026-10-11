"""Application settings, loaded from environment variables (and an optional .env file).

Settings are validated at startup so that a misconfiguration fails fast with a clear
error instead of surfacing later in the middle of a request.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "test", "production"] = "local"
    log_level: LogLevel = "INFO"

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

    @field_validator("github_token", mode="before")
    @classmethod
    def _empty_token_is_none(cls, value: object) -> object:
        # ``GITHUB_TOKEN=`` in a .env file means "no token", not an empty credential.
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
