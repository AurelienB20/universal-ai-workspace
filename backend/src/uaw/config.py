"""Application settings, loaded from environment variables (and an optional .env file).

Settings are validated at startup so that a misconfiguration fails fast with a clear
error instead of surfacing later in the middle of a request.
"""

from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from uaw.connectors.github.url import parse_github_full_name

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

    # API protection. Clients send a key in the X-API-Key header. API_KEY is the admin
    # key (every route); it is required in production. Without it (local development),
    # the API is open.
    api_key: SecretStr | None = None
    # Demo key, for a public web interface: questions and searches only, on the
    # DEMO_REPOSITORIES ("owner/name", comma-separated). Never imports.
    demo_api_key: SecretStr | None = None
    demo_repositories: Annotated[frozenset[str], NoDecode] = frozenset()
    # Requests per client IP address, counted in memory by each process. 0 = no limit.
    rate_limit_imports_per_hour: int = Field(default=10, ge=0)
    rate_limit_search_per_minute: int = Field(default=60, ge=0)
    rate_limit_ask_per_minute: int = Field(default=10, ge=0)
    max_request_body_kb: int = Field(default=64, gt=0, le=1024)
    # Questions answered at the same time, all clients combined. Beyond, a question is
    # refused at once (503) rather than queued.
    max_concurrent_asks: int = Field(default=4, gt=0, le=50)

    # Cost control: tokens per UTC day, all clients combined. 0 = no budget; both are
    # required in production. Once a budget is spent, new requests needing that
    # provider are refused until midnight UTC.
    daily_embedding_token_budget: int = Field(default=0, ge=0)
    daily_llm_token_budget: int = Field(default=0, ge=0)
    # Worst-case tokens reserved by each question (and search) before it starts, so
    # that simultaneous requests cannot overshoot the budget together. The LLM
    # estimate covers the passages, the question and LLM_MAX_TOKENS.
    ask_reserved_llm_tokens: int = Field(default=12_000, gt=0)
    query_reserved_embedding_tokens: int = Field(default=2_000, gt=0)

    @property
    def query_reserved_voyage_tokens(self) -> int:
        """Voyage tokens one question or search may use: its embedding, and the reranking
        of its candidates when a reranker is configured."""
        return self.query_reserved_embedding_tokens + (
            self.rerank_reserved_tokens if self.rerank_model else 0
        )

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

    # Imports by visitors of the public demo (demo key with a visitor id). Off by
    # default. A visitor reads only the repositories they imported, for
    # VISITOR_ACCESS_HOURS, and imports under stricter limits than the admin.
    public_imports_enabled: bool = False
    visitor_access_hours: int = Field(default=24, gt=0, le=24 * 30)
    visitor_max_repo_size_mb: int = Field(default=20, gt=0)
    visitor_max_files: int = Field(default=300, gt=0)
    # Embedding tokens of one visitor import, estimated before any is spent. The
    # estimate counts 3 characters per token; measured: about 4 on Flask and
    # itsdangerous, so it overestimates the real cost.
    visitor_max_import_tokens: int = Field(default=400_000, gt=0)
    # Imports per visitor and in total, per UTC day, counted in the database. With the
    # cap above, visitors can spend at most VISITOR_IMPORTS_PER_DAY x
    # VISITOR_MAX_IMPORT_TOKENS embedding tokens a day.
    visitor_imports_per_visitor_per_day: int = Field(default=2, gt=0)
    visitor_imports_per_day: int = Field(default=20, gt=0)
    # Per client IP address, counted in memory (a restart resets it). 0 = no limit.
    rate_limit_visitor_imports_per_day: int = Field(default=3, ge=0)
    # Visitor imports run one at a time; at most this many wait behind the running one.
    visitor_import_queue: int = Field(default=3, ge=0, le=50)
    # Questions per visitor and per day about the repositories they imported, counted
    # in memory. 0 = no limit. Questions about the DEMO_REPOSITORIES are not counted.
    visitor_questions_per_day: int = Field(default=15, ge=0)
    # How often expired accesses, and the repositories nobody reads any more, are deleted.
    visitor_cleanup_interval_minutes: int = Field(default=60, gt=0)

    @property
    def visitor_daily_embedding_tokens(self) -> int:
        """The most embedding tokens visitor imports can spend in a day."""
        return self.visitor_imports_per_day * self.visitor_max_import_tokens

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
    # Ready snapshots kept per repository after an import (the newest is searched).
    # More than one, so that a question still reading the previous snapshot when a
    # new import finishes does not lose its passages.
    keep_snapshots: int = Field(default=2, ge=1, le=20)

    # Answer generation (Claude). Without a key, questions are refused with a clear error.
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    # Claude Opus 5.5 always thinks: effort is the only depth control. Its API default
    # is "medium"; it is set explicitly so that a model change cannot alter it silently.
    llm_effort: Effort = "medium"
    llm_max_tokens: int = Field(default=2_000, gt=0, le=64_000)
    llm_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    # Retrieval: "vector" (embeddings only) or "hybrid" (embeddings and full text, fused
    # with RRF). Change only on evaluation results (backend/eval/results).
    retrieval_mode: Literal["vector", "hybrid"] = "vector"
    retrieval_text_weight: float = Field(default=1.0, ge=0, le=10)
    # Below 1, chunks from test files rank lower (except for questions about tests).
    # Measured: 0.5 raises the line-level MRR on Flask from 0.68 to 0.76 (test split).
    retrieval_test_weight: float = Field(default=0.5, gt=0, le=1)
    # Voyage reranker reordering the best chunks ("" = no reranking). Measured on the
    # Flask test split: MRR 0.76 -> 0.91, for about 0.4 s more per search.
    rerank_model: str = "rerank-3"
    rerank_candidates: int = Field(default=30, ge=1, le=100)
    # Worst-case reranking tokens of one question: (question + chunk) per candidate.
    rerank_reserved_tokens: int = Field(default=40_000, gt=0)
    # On a safety refusal, the API retries the request on a model it picks for the
    # refusal category, inside the same call.
    llm_refusal_fallback: bool = True
    # Passages retrieved and shown to the model for each question.
    answer_top_k: int = Field(default=8, gt=0, le=20)

    @field_validator(
        "api_key",
        "demo_api_key",
        "github_token",
        "voyage_api_key",
        "anthropic_api_key",
        mode="before",
    )
    @classmethod
    def _empty_secret_is_none(cls, value: object) -> object:
        # ``GITHUB_TOKEN=`` in a .env file means "no token", not an empty credential.
        return None if value == "" else value

    @field_validator("demo_repositories", mode="before")
    @classmethod
    def _parse_repository_list(cls, value: object) -> object:
        if isinstance(value, str):
            value = [item for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set, frozenset)):
            # Lowercase "owner/name": the same identity as the stored repositories.
            return frozenset(parse_github_full_name(item).full_name.lower() for item in value)
        return value

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

    @model_validator(mode="after")
    def _require_budgets_in_production(self) -> Self:
        # Without a budget, a leaked key or a bug could spend without any limit.
        if self.app_env == "production" and not (
            self.daily_embedding_token_budget and self.daily_llm_token_budget
        ):
            raise ValueError(
                "DAILY_EMBEDDING_TOKEN_BUDGET and DAILY_LLM_TOKEN_BUDGET are required "
                "when APP_ENV=production"
            )
        return self

    @model_validator(mode="after")
    def _check_demo_key(self) -> Self:
        if self.demo_api_key is None:
            return self
        # Without an admin key the API is open: a demo key would restrict nothing.
        if self.api_key is None:
            raise ValueError("DEMO_API_KEY requires API_KEY (the admin key)")
        if self.demo_api_key.get_secret_value() == self.api_key.get_secret_value():
            raise ValueError("DEMO_API_KEY must differ from API_KEY")
        return self

    @model_validator(mode="after")
    def _check_public_imports(self) -> Self:
        if not self.public_imports_enabled:
            return self
        # Visitors are told apart by the web interface, which holds the demo key.
        if self.demo_api_key is None:
            raise ValueError("PUBLIC_IMPORTS_ENABLED requires DEMO_API_KEY")
        # Visitor imports count against the embedding budget like any import. Without
        # room left after their maximum, they could stop every question for the day.
        budget = self.daily_embedding_token_budget
        if budget and budget <= self.visitor_daily_embedding_tokens:
            raise ValueError(
                f"DAILY_EMBEDDING_TOKEN_BUDGET ({budget}) must exceed what visitor imports "
                f"can spend in a day ({self.visitor_daily_embedding_tokens} = "
                "VISITOR_IMPORTS_PER_DAY x VISITOR_MAX_IMPORT_TOKENS), so that questions "
                "keep the rest"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
