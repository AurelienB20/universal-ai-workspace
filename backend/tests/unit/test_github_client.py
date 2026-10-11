import asyncio
from collections.abc import AsyncIterator, Callable

import httpx2 as httpx
import pytest

from uaw.connectors.github.client import GitHubClient
from uaw.connectors.github.errors import (
    EmptyRepositoryError,
    GitHubRateLimitError,
    GitHubUnavailableError,
    RepositoryNotFoundError,
    RepositoryTooLargeError,
)
from uaw.connectors.github.url import GitHubRepoRef

pytestmark = pytest.mark.anyio

REF = GitHubRepoRef(owner="octo", name="hello")
SHA = "a" * 40
REPO_JSON = {
    "full_name": "Octo/Hello",
    "private": False,
    "size": 120,
    "default_branch": "main",
    "description": "Demo",
}

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(
    handler: Handler, *, token: str | None = None, download_timeout: float = 5.0
) -> tuple[GitHubClient, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(recording_handler))
    client = GitHubClient(http, token=token, download_timeout_seconds=download_timeout)
    return client, requests


# --- get_repository ---------------------------------------------------------------


async def test_get_repository_returns_canonical_info() -> None:
    client, requests = make_client(lambda _: httpx.Response(200, json=REPO_JSON))

    info = await client.get_repository(REF)

    assert info.ref == GitHubRepoRef(owner="Octo", name="Hello")
    assert (info.default_branch, info.size_kb, info.private) == ("main", 120, False)
    assert str(requests[0].url) == "https://api.github.com/repos/octo/hello"
    assert requests[0].headers["user-agent"] == "universal-ai-workspace"
    assert "authorization" not in requests[0].headers


async def test_token_is_sent_to_the_api() -> None:
    client, requests = make_client(lambda _: httpx.Response(200, json=REPO_JSON), token="t0k")

    await client.get_repository(REF)

    assert requests[0].headers["authorization"] == "Bearer t0k"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(404), RepositoryNotFoundError),
        (httpx.Response(403), RepositoryNotFoundError),
        (httpx.Response(403, headers={"x-ratelimit-remaining": "0"}), GitHubRateLimitError),
        (httpx.Response(403, headers={"retry-after": "60"}), GitHubRateLimitError),
        (httpx.Response(429), GitHubRateLimitError),
        (httpx.Response(401), GitHubUnavailableError),
        (httpx.Response(500), GitHubUnavailableError),
        (httpx.Response(200, text="not json"), GitHubUnavailableError),
        (httpx.Response(200, json={"full_name": "x"}), GitHubUnavailableError),
        (httpx.Response(200, json={**REPO_JSON, "full_name": "../etc"}), GitHubUnavailableError),
    ],
)
async def test_get_repository_maps_failures(
    response: httpx.Response, error: type[Exception]
) -> None:
    client, _ = make_client(lambda _: response)

    with pytest.raises(error):
        await client.get_repository(REF)


async def test_rate_limit_message_suggests_a_token_only_when_none_is_set() -> None:
    client, _ = make_client(lambda _: httpx.Response(429))
    with pytest.raises(GitHubRateLimitError, match="GITHUB_TOKEN"):
        await client.get_repository(REF)

    client, _ = make_client(lambda _: httpx.Response(429), token="t0k")
    with pytest.raises(GitHubRateLimitError) as exc_info:
        await client.get_repository(REF)
    assert "GITHUB_TOKEN" not in str(exc_info.value)


@pytest.mark.parametrize(
    "exception", [httpx.ConnectTimeout("timeout"), httpx.ConnectError("refused")]
)
async def test_network_failures_become_unavailable(exception: Exception) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise exception

    client, _ = make_client(handler)

    with pytest.raises(GitHubUnavailableError):
        await client.get_repository(REF)


async def test_follows_api_redirect_for_renamed_repository() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octo/hello":
            return httpx.Response(
                301, headers={"location": "https://api.github.com/repositories/42"}
            )
        return httpx.Response(200, json=REPO_JSON)

    client, requests = make_client(handler)

    await client.get_repository(REF)

    assert [r.url.path for r in requests] == ["/repos/octo/hello", "/repositories/42"]


@pytest.mark.parametrize(
    "location",
    ["https://evil.example/repos/x", "http://api.github.com/repos/x", "//evil.example/x"],
)
async def test_refuses_redirects_outside_the_api_host(location: str) -> None:
    client, requests = make_client(lambda _: httpx.Response(301, headers={"location": location}))

    with pytest.raises(GitHubUnavailableError):
        await client.get_repository(REF)
    assert len(requests) == 1


async def test_redirect_loops_are_bounded() -> None:
    redirect = httpx.Response(301, headers={"location": "https://api.github.com/loop"})
    client, requests = make_client(lambda _: redirect)

    with pytest.raises(GitHubUnavailableError, match="redirected too many times"):
        await client.get_repository(REF)
    assert len(requests) == 4


# --- get_latest_commit_sha -------------------------------------------------------


async def test_latest_commit_sha() -> None:
    client, requests = make_client(lambda _: httpx.Response(200, json=[{"sha": SHA}]))

    assert await client.get_latest_commit_sha(REF) == SHA
    assert str(requests[0].url) == "https://api.github.com/repos/octo/hello/commits?per_page=1"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(200, json=[]), EmptyRepositoryError),
        (httpx.Response(409), EmptyRepositoryError),
        (httpx.Response(200, json=[{"sha": "not-a-sha"}]), GitHubUnavailableError),
        (httpx.Response(200, json={"message": "?"}), GitHubUnavailableError),
        (httpx.Response(200, json=None), GitHubUnavailableError),
    ],
)
async def test_latest_commit_sha_failures(response: httpx.Response, error: type[Exception]) -> None:
    client, _ = make_client(lambda _: response)

    with pytest.raises(error):
        await client.get_latest_commit_sha(REF)


# --- download_tarball --------------------------------------------------------------

CODELOAD_URL = f"https://codeload.github.com/octo/hello/legacy.tar.gz/{SHA}"


def tarball_handler(body: httpx.Response) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(302, headers={"location": CODELOAD_URL})
        return body

    return handler


async def test_download_follows_redirect_to_codeload_without_leaking_the_token() -> None:
    client, requests = make_client(
        tarball_handler(httpx.Response(200, content=b"archive-bytes")), token="t0k"
    )

    data = await client.download_tarball(REF, SHA, max_bytes=1000)

    assert data == b"archive-bytes"
    assert [r.url.host for r in requests] == ["api.github.com", "codeload.github.com"]
    assert requests[0].headers["authorization"] == "Bearer t0k"
    assert "authorization" not in requests[1].headers


async def test_download_refuses_redirect_to_unknown_host() -> None:
    client, requests = make_client(
        lambda _: httpx.Response(302, headers={"location": "https://evil.example/a.tgz"})
    )

    with pytest.raises(GitHubUnavailableError):
        await client.download_tarball(REF, SHA, max_bytes=1000)
    assert len(requests) == 1


async def test_download_rejects_declared_oversized_archive() -> None:
    client, _ = make_client(tarball_handler(httpx.Response(200, content=b"x" * 2000)))

    with pytest.raises(RepositoryTooLargeError):
        await client.download_tarball(REF, SHA, max_bytes=1000)


async def test_download_stops_streaming_once_the_cap_is_exceeded() -> None:
    chunks_sent = 0

    async def endless() -> AsyncIterator[bytes]:
        nonlocal chunks_sent
        while True:
            chunks_sent += 1
            yield b"x" * 100

    # No Content-Length header: only the streaming cap can stop this download.
    client, _ = make_client(tarball_handler(httpx.Response(200, content=endless())))

    with pytest.raises(RepositoryTooLargeError):
        await client.download_tarball(REF, SHA, max_bytes=1000)
    assert chunks_sent <= 11


async def test_slow_download_hits_the_overall_timeout() -> None:
    async def slow_drip() -> AsyncIterator[bytes]:
        while True:
            await asyncio.sleep(0.05)
            yield b"x"

    client, _ = make_client(
        tarball_handler(httpx.Response(200, content=slow_drip())), download_timeout=0.2
    )

    with pytest.raises(GitHubUnavailableError, match="too long"):
        await client.download_tarball(REF, SHA, max_bytes=10_000)


async def test_download_requires_a_full_commit_sha() -> None:
    client, requests = make_client(lambda _: httpx.Response(200))

    with pytest.raises(ValueError):
        await client.download_tarball(REF, "main", max_bytes=1000)
    assert requests == []
