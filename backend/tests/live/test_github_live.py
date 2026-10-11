"""Tests against the real GitHub API. Opt-in: ``uv run pytest -m live``.

They use unauthenticated requests unless GITHUB_TOKEN is set (4 API calls per test,
well within the 60 requests/hour anonymous limit).
"""

import pytest

from uaw.config import Settings
from uaw.connectors.github.connector import build_github_connector, create_github_http_client
from uaw.connectors.github.errors import RepositoryNotFoundError
from uaw.connectors.github.url import parse_github_repo_url

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_fetch_small_python_repository() -> None:
    settings = Settings()
    async with create_github_http_client(settings) as http:
        connector = build_github_connector(settings, http)
        fetched = await connector.fetch(
            parse_github_repo_url("https://github.com/pallets/itsdangerous")
        )

    paths = {doc.path for doc in fetched.documents}
    assert len(fetched.commit_sha) == 40
    assert "src/itsdangerous/signer.py" in paths
    assert "README.md" in paths
    assert all(".." not in path.split("/") for path in paths)


async def test_missing_repository() -> None:
    settings = Settings()
    async with create_github_http_client(settings) as http:
        connector = build_github_connector(settings, http)
        with pytest.raises(RepositoryNotFoundError):
            await connector.fetch(
                parse_github_repo_url("https://github.com/pallets/this-repo-does-not-exist-42")
            )
