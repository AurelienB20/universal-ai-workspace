import pytest
from pydantic import ValidationError

from uaw.connectors.github.url import (
    MAX_URL_LENGTH,
    GitHubRepoRef,
    InvalidRepositoryUrlError,
    parse_github_full_name,
    parse_github_repo_url,
)


@pytest.mark.parametrize(
    ("url", "owner", "name"),
    [
        ("https://github.com/fastapi/fastapi", "fastapi", "fastapi"),
        ("https://github.com/fastapi/fastapi/", "fastapi", "fastapi"),
        ("https://github.com/fastapi/fastapi.git", "fastapi", "fastapi"),
        ("https://www.github.com/fastapi/fastapi", "fastapi", "fastapi"),
        ("HTTPS://GitHub.com/Owner/Repo", "Owner", "Repo"),
        ("  https://github.com/owner/repo  ", "owner", "repo"),
        ("https://github.com/my-org/my_repo.v2", "my-org", "my_repo.v2"),
        ("https://github.com/a/b", "a", "b"),
        ("https://github.com/owner/repo.git.git", "owner", "repo.git"),
        (f"https://github.com/{'a' * 39}/{'r' * 100}", "a" * 39, "r" * 100),
    ],
)
def test_parses_valid_repository_urls(url: str, owner: str, name: str) -> None:
    ref = parse_github_repo_url(url)

    assert ref == GitHubRepoRef(owner=owner, name=name)


@pytest.mark.parametrize(
    "url",
    [
        # empty / not a URL
        "",
        "   ",
        "github.com/owner/repo",
        "owner/repo",
        # wrong scheme
        "http://github.com/owner/repo",
        "ftp://github.com/owner/repo",
        "javascript:alert(1)",
        "file:///etc/passwd",
        # wrong or disguised host
        "https://gitlab.com/owner/repo",
        "https://api.github.com/repos/owner/repo",
        "https://gist.github.com/owner/repo",
        "https://github.com.evil.com/owner/repo",
        "https://evil.com/github.com/owner/repo",
        "https://user@github.com/owner/repo",
        "https://github.com@evil.com/owner/repo",
        "https://github.com:443/owner/repo",
        "https://[::1/owner/repo",
        # not the repository root
        "https://github.com",
        "https://github.com/",
        "https://github.com/owner",
        "https://github.com/owner/repo/tree/main/src",
        "https://github.com/owner/repo/.git",
        "https://github.com//owner/repo",
        "https://github.com/owner/repo?tab=readme",
        "https://github.com/owner/repo#readme",
        # path traversal and encoding tricks
        "https://github.com/owner/..",
        "https://github.com/owner/.",
        "https://github.com/../repo",
        "https://github.com/owner/%2e%2e",
        "https://github.com/owner/re%2Fpo",
        "https://github.com/owner\\repo",
        # invalid characters
        "https://github.com/owner/re po",
        "https://github.com/owner/repo\n/x",
        "https://github.com/ownér/repo",
        "https://github.com/owner/.git",
        # invalid owner / repo names
        "https://github.com/-owner/repo",
        f"https://github.com/{'a' * 40}/repo",
        f"https://github.com/owner/{'r' * 101}",
        "https://github.com/own_er/repo",
    ],
)
def test_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        parse_github_repo_url(url)


def test_rejects_overlong_input_before_parsing() -> None:
    url = "https://github.com/owner/" + "r" * MAX_URL_LENGTH

    with pytest.raises(InvalidRepositoryUrlError, match="too long"):
        parse_github_repo_url(url)


def test_error_message_is_user_facing() -> None:
    with pytest.raises(InvalidRepositoryUrlError) as exc_info:
        parse_github_repo_url("https://gitlab.com/owner/repo")

    assert "github.com" in str(exc_info.value)


def test_derived_urls() -> None:
    ref = GitHubRepoRef(owner="fastapi", name="fastapi")

    assert ref.full_name == "fastapi/fastapi"
    assert ref.html_url == "https://github.com/fastapi/fastapi"


@pytest.mark.parametrize(
    ("owner", "name"),
    [("-bad", "repo"), ("owner", ".."), ("owner", "a/b"), ("", "repo"), ("owner", "")],
)
def test_ref_cannot_be_constructed_invalid(owner: str, name: str) -> None:
    # The model enforces the same rules as the parser, so an invalid reference can
    # never be built elsewhere in the code (e.g. from the database or a test).
    with pytest.raises(ValidationError):
        GitHubRepoRef(owner=owner, name=name)


def test_ref_is_immutable() -> None:
    ref = GitHubRepoRef(owner="owner", name="repo")

    with pytest.raises(ValidationError):
        ref.owner = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("value", "owner", "name"),
    [
        ("pallets/flask", "pallets", "flask"),
        ("  Pallets/Flask ", "Pallets", "Flask"),
        ("my-org/my_repo.v2", "my-org", "my_repo.v2"),
    ],
)
def test_parses_full_names(value: str, owner: str, name: str) -> None:
    assert parse_github_full_name(value) == GitHubRepoRef(owner=owner, name=name)


@pytest.mark.parametrize(
    "value",
    ["", "flask", "pallets/flask/extra", "/flask", "pallets/", "-bad/repo", "o/..", "o/r p"],
)
def test_rejects_invalid_full_names(value: str) -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        parse_github_full_name(value)
