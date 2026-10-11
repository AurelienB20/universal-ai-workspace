"""Minimal GitHub REST API client for importing public repositories.

Responsibilities: HTTP transport, redirects, timeouts and translating HTTP failures
into connector errors. Business rules (public only, size limits) live in
``connector.py``.

Security notes:
- URLs are always built from a validated ``GitHubRepoRef`` against a fixed host.
- Redirects are followed manually and only to HTTPS URLs on an allowlist of hosts.
- The token is only ever sent to ``api.github.com``, never to redirect targets.
"""

import asyncio
import logging
import re

import httpx2 as httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from uaw.connectors.github.errors import (
    EmptyRepositoryError,
    GitHubRateLimitError,
    GitHubUnavailableError,
    RepositoryNotFoundError,
    RepositoryTooLargeError,
)
from uaw.connectors.github.url import GitHubRepoRef

logger = logging.getLogger(__name__)

API_HOST = "api.github.com"
API_BASE_URL = f"https://{API_HOST}"
CODELOAD_HOST = "codeload.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = "universal-ai-workspace"
MAX_REDIRECTS = 3

_COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40}")


class RepositoryInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: GitHubRepoRef  # canonical owner/name casing, as reported by GitHub
    default_branch: str
    size_kb: int
    private: bool
    description: str | None


class _RepositoryPayload(BaseModel):
    full_name: str
    private: bool
    size: int
    default_branch: str
    description: str | None = None


class _CommitPayload(BaseModel):
    sha: str


class GitHubClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        token: str | None = None,
        download_timeout_seconds: float = 120.0,
    ) -> None:
        # ``http`` is injected so the application can share one connection pool and
        # tests can plug in a mock transport. Per-request timeouts are set on it.
        self._http = http
        self._token = token
        self._download_timeout_seconds = download_timeout_seconds

    async def get_repository(self, ref: GitHubRepoRef) -> RepositoryInfo:
        response = await self._api_get(f"/repos/{ref.full_name}", ref)
        try:
            payload = _RepositoryPayload.model_validate_json(response.content)
            owner, _, name = payload.full_name.partition("/")
            canonical_ref = GitHubRepoRef(owner=owner, name=name)
        except ValidationError as exc:
            raise GitHubUnavailableError("GitHub returned an unexpected response.") from exc

        return RepositoryInfo(
            ref=canonical_ref,
            default_branch=payload.default_branch,
            size_kb=payload.size,
            private=payload.private,
            description=payload.description,
        )

    async def get_latest_commit_sha(self, ref: GitHubRepoRef) -> str:
        """Return the SHA of the latest commit on the repository's default branch.

        Listing commits without a ``sha`` parameter targets the default branch, so the
        (repository-controlled) branch name never has to be put into a URL.
        """
        response = await self._api_get(f"/repos/{ref.full_name}/commits?per_page=1", ref)
        try:
            commits = [_CommitPayload.model_validate(item) for item in response.json()]
        except (ValueError, TypeError, ValidationError) as exc:
            raise GitHubUnavailableError("GitHub returned an unexpected response.") from exc

        if not commits:
            raise EmptyRepositoryError(f"Repository {ref.full_name} has no commits.")
        sha = commits[0].sha
        if not _COMMIT_SHA_RE.fullmatch(sha):
            raise GitHubUnavailableError("GitHub returned an invalid commit identifier.")
        return sha

    async def download_tarball(self, ref: GitHubRepoRef, commit_sha: str, max_bytes: int) -> bytes:
        """Download the ``.tar.gz`` archive of a commit, streaming it with a size cap."""
        if not _COMMIT_SHA_RE.fullmatch(commit_sha):
            raise ValueError("commit_sha must be a full 40-character hex SHA")
        url = f"{API_BASE_URL}/repos/{ref.full_name}/tarball/{commit_sha}"
        try:
            async with asyncio.timeout(self._download_timeout_seconds):
                data = await self._stream_download(url, ref, max_bytes)
        except TimeoutError as exc:
            raise GitHubUnavailableError("Downloading the repository took too long.") from exc
        except httpx.TimeoutException as exc:
            raise GitHubUnavailableError("GitHub did not respond in time.") from exc
        except httpx.TransportError as exc:
            raise GitHubUnavailableError("Could not connect to GitHub.") from exc

        logger.info("Downloaded archive of %s@%s (%d bytes)", ref.full_name, commit_sha, len(data))
        return data

    async def _api_get(self, path: str, ref: GitHubRepoRef) -> httpx.Response:
        url = f"{API_BASE_URL}{path}"
        try:
            for _ in range(MAX_REDIRECTS + 1):
                response = await self._http.get(url, headers=self._headers_for(url))
                if not response.is_redirect:
                    _raise_for_status(response, ref, has_token=self._token is not None)
                    return response
                # Renamed or transferred repositories answer with a 301 to the new
                # API location. Only redirects within the API host are accepted.
                url = _checked_redirect(response, allowed_hosts={API_HOST})
        except httpx.TimeoutException as exc:
            raise GitHubUnavailableError("GitHub did not respond in time.") from exc
        except httpx.TransportError as exc:
            raise GitHubUnavailableError("Could not connect to GitHub.") from exc
        raise GitHubUnavailableError("GitHub redirected too many times.")

    async def _stream_download(self, url: str, ref: GitHubRepoRef, max_bytes: int) -> bytes:
        too_large = RepositoryTooLargeError(
            f"The repository archive exceeds the size limit ({max_bytes // (1024 * 1024)} MB)."
        )
        for _ in range(MAX_REDIRECTS + 1):
            async with self._http.stream("GET", url, headers=self._headers_for(url)) as response:
                if response.is_redirect:
                    url = _checked_redirect(response, allowed_hosts={API_HOST, CODELOAD_HOST})
                    continue
                _raise_for_status(response, ref, has_token=self._token is not None)

                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > max_bytes:
                    raise too_large
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > max_bytes:
                        raise too_large
                return bytes(buffer)
        raise GitHubUnavailableError("GitHub redirected too many times.")

    def _headers_for(self, url: str) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": API_VERSION,
        }
        if self._token and httpx.URL(url).host == API_HOST:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers


def _checked_redirect(response: httpx.Response, *, allowed_hosts: set[str]) -> str:
    location = response.headers.get("location", "")
    target = response.url.join(location)
    if target.scheme != "https" or target.host not in allowed_hosts:
        logger.warning("Refused redirect to %s", target.host)
        raise GitHubUnavailableError("GitHub redirected to an unexpected location.")
    return str(target)


def _raise_for_status(response: httpx.Response, ref: GitHubRepoRef, *, has_token: bool) -> None:
    status = response.status_code
    if response.is_success:
        return

    is_rate_limited = status == 429 or (
        status == 403
        and (
            response.headers.get("x-ratelimit-remaining") == "0"
            or "retry-after" in response.headers
        )
    )
    if is_rate_limited:
        hint = "" if has_token else " Configure GITHUB_TOKEN to raise the limit."
        logger.warning("GitHub rate limit reached (status %d)", status)
        raise GitHubRateLimitError(f"GitHub API rate limit reached. Try again later.{hint}")
    if status in (403, 404):
        raise RepositoryNotFoundError(
            f"Repository {ref.full_name} was not found or is not accessible."
        )
    if status == 409:
        raise EmptyRepositoryError(f"Repository {ref.full_name} has no commits.")
    if status == 401:
        logger.error("GitHub rejected the configured token (401)")
        raise GitHubUnavailableError("GitHub rejected the server's credentials.")

    logger.warning("Unexpected GitHub response: status %d", status)
    raise GitHubUnavailableError("GitHub returned an unexpected response.")
