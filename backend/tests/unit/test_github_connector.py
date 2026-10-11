from typing import Any

import httpx2 as httpx
import pytest

from tests.tarballs import file, make_tarball
from uaw.config import Settings
from uaw.connectors.github.connector import GitHubConnector, ImportLimits, build_github_connector
from uaw.connectors.github.errors import RepositoryNotPublicError, RepositoryTooLargeError
from uaw.connectors.github.filters import SkipReason
from uaw.connectors.github.url import GitHubRepoRef

pytestmark = pytest.mark.anyio

REF = GitHubRepoRef(owner="octo", name="hello")
SHA = "b" * 40
SETTINGS = Settings(_env_file=None, max_repo_size_mb=1)


def fake_github(repo: dict[str, Any], archive: bytes) -> tuple[httpx.MockTransport, list[str]]:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/repos/octo/hello":
            return httpx.Response(200, json=repo)
        if request.url.path == "/repos/octo/hello/commits":
            return httpx.Response(200, json=[{"sha": SHA}])
        if request.url.path == f"/repos/octo/hello/tarball/{SHA}":
            return httpx.Response(200, content=archive)
        return httpx.Response(404)

    return httpx.MockTransport(handler), paths


def repo_json(**overrides: Any) -> dict[str, Any]:
    return {
        "full_name": "octo/hello",
        "private": False,
        "size": 10,
        "default_branch": "main",
        **overrides,
    }


def make_connector(transport: httpx.MockTransport) -> GitHubConnector:
    return build_github_connector(SETTINGS, httpx.AsyncClient(transport=transport))


async def test_fetch_returns_documents_pinned_to_a_commit() -> None:
    archive = make_tarball(file("src/app.py", "print('hi')\n"), file("logo.png", b"PNG"))
    transport, _ = fake_github(repo_json(), archive)

    fetched = await make_connector(transport).fetch(REF)

    assert fetched.commit_sha == SHA
    assert fetched.info.ref == REF
    assert [(d.path, d.content) for d in fetched.documents] == [("src/app.py", "print('hi')\n")]
    assert [(s.path, s.reason) for s in fetched.skipped] == [
        ("logo.png", SkipReason.UNSUPPORTED_TYPE)
    ]


async def test_private_repository_is_rejected_before_download() -> None:
    transport, paths = fake_github(repo_json(private=True), b"")

    with pytest.raises(RepositoryNotPublicError):
        await make_connector(transport).fetch(REF)
    assert paths == ["/repos/octo/hello"]


async def test_oversized_repository_is_rejected_before_download() -> None:
    transport, paths = fake_github(repo_json(size=2048), b"")  # 2 MB > 1 MB limit

    with pytest.raises(RepositoryTooLargeError):
        await make_connector(transport).fetch(REF)
    assert paths == ["/repos/octo/hello"]


def test_limits_are_derived_from_settings() -> None:
    limits = ImportLimits.from_settings(Settings(_env_file=None, max_file_kb=4, max_files=7))

    assert limits.archive.max_file_bytes == 4096
    assert limits.archive.max_files == 7
