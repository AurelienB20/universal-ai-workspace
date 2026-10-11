"""Import a public GitHub repository as a list of text documents.

This layer holds the import policy (public repositories only, size limits, commit
pinning). HTTP details live in ``client.py`` and archive parsing in ``archive.py``.
"""

import asyncio
import logging
from dataclasses import dataclass

import httpx2 as httpx
from pydantic import BaseModel, ConfigDict

from uaw.config import Settings
from uaw.connectors.github.archive import (
    ArchiveLimits,
    SkippedFile,
    read_repository_archive,
)
from uaw.connectors.github.client import GitHubClient, RepositoryInfo
from uaw.connectors.github.errors import RepositoryNotPublicError, RepositoryTooLargeError
from uaw.connectors.github.url import GitHubRepoRef
from uaw.domain.documents import SourceDocument

logger = logging.getLogger(__name__)

_MB = 1024 * 1024


@dataclass(frozen=True)
class ImportLimits:
    max_repo_size_bytes: int
    max_archive_bytes: int
    archive: ArchiveLimits

    @classmethod
    def from_settings(cls, settings: Settings) -> "ImportLimits":
        return cls(
            max_repo_size_bytes=settings.max_repo_size_mb * _MB,
            max_archive_bytes=settings.max_archive_mb * _MB,
            archive=ArchiveLimits(
                max_uncompressed_bytes=settings.max_uncompressed_mb * _MB,
                max_entries=settings.max_archive_entries,
                max_file_bytes=settings.max_file_kb * 1024,
                max_files=settings.max_files,
            ),
        )


class FetchedRepository(BaseModel):
    model_config = ConfigDict(frozen=True)

    info: RepositoryInfo
    commit_sha: str
    documents: list[SourceDocument]
    skipped: list[SkippedFile]


class GitHubConnector:
    def __init__(self, client: GitHubClient, limits: ImportLimits) -> None:
        self._client = client
        self._limits = limits

    async def fetch(self, ref: GitHubRepoRef) -> FetchedRepository:
        info = await self._client.get_repository(ref)
        if info.private:
            raise RepositoryNotPublicError(
                f"Repository {info.ref.full_name} is private. Only public repositories are "
                "supported."
            )
        # GitHub's ``size`` covers the whole git history, so it over-estimates the
        # archive. It is a cheap pre-check that avoids downloading obvious giants.
        if info.size_kb * 1024 > self._limits.max_repo_size_bytes:
            raise RepositoryTooLargeError(
                f"Repository {info.ref.full_name} is too large to import "
                f"(max {self._limits.max_repo_size_bytes // _MB} MB)."
            )

        commit_sha = await self._client.get_latest_commit_sha(info.ref)
        archive = await self._client.download_tarball(
            info.ref, commit_sha, self._limits.max_archive_bytes
        )
        # Decompression and parsing are CPU-bound: run them off the event loop.
        result = await asyncio.to_thread(read_repository_archive, archive, self._limits.archive)

        logger.info(
            "Fetched %s@%s: %d documents, %d skipped",
            info.ref.full_name,
            commit_sha,
            len(result.documents),
            len(result.skipped),
        )
        return FetchedRepository(
            info=info,
            commit_sha=commit_sha,
            documents=result.documents,
            skipped=result.skipped,
        )


def create_github_http_client(settings: Settings) -> httpx.AsyncClient:
    """HTTP client for GitHub calls. Redirects are handled by ``GitHubClient`` itself."""
    return httpx.AsyncClient(timeout=settings.github_timeout_seconds, follow_redirects=False)


def build_github_connector(settings: Settings, http: httpx.AsyncClient) -> GitHubConnector:
    token = settings.github_token.get_secret_value() if settings.github_token else None
    client = GitHubClient(
        http,
        token=token,
        download_timeout_seconds=settings.github_download_timeout_seconds,
    )
    return GitHubConnector(client, ImportLimits.from_settings(settings))
