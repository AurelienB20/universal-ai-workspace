"""Strict parsing of user-supplied GitHub repository URLs.

This is a security boundary: the rest of the system never touches the raw URL the
user typed. It only receives a validated ``GitHubRepoRef`` and builds GitHub API URLs
itself, against a fixed host. That rules out SSRF (making the server fetch arbitrary
hosts) and path injection into API calls.

Accepted form (and nothing else):
    https://github.com/{owner}/{repo}
with an optional ``www.`` host prefix, ``.git`` suffix and trailing slash.

Whether the repository actually exists and is public is checked later, against the
GitHub API. This module only validates syntax.
"""

import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

MAX_URL_LENGTH = 300

# GitHub logins: ASCII letters, digits and hyphens, at most 39 characters, not
# starting with a hyphen. Some legacy accounts contain double or trailing hyphens,
# so those are allowed.
OWNER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$"
# Repository names: ASCII letters, digits, '.', '_' and '-', at most 100 characters.
REPO_PATTERN = r"^[A-Za-z0-9._-]{1,100}$"

_ALLOWED_HOSTS = frozenset({"github.com", "www.github.com"})
_RESERVED_REPO_NAMES = frozenset({".", ".."})

Owner = Annotated[str, StringConstraints(pattern=OWNER_PATTERN)]
RepoName = Annotated[str, StringConstraints(pattern=REPO_PATTERN)]


class InvalidRepositoryUrlError(ValueError):
    """The input is not a supported GitHub repository URL. The message is user-facing."""


class GitHubRepoRef(BaseModel):
    """A syntactically valid reference to a GitHub repository."""

    model_config = ConfigDict(frozen=True)

    owner: Owner
    name: RepoName

    @field_validator("name")
    @classmethod
    def _reject_reserved_names(cls, value: str) -> str:
        if value in _RESERVED_REPO_NAMES:
            raise ValueError(f"'{value}' is not a valid repository name")
        return value

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def html_url(self) -> str:
        return f"https://github.com/{self.full_name}"


def parse_github_repo_url(raw_url: str) -> GitHubRepoRef:
    """Parse a public GitHub repository URL into a ``GitHubRepoRef``.

    Raises:
        InvalidRepositoryUrlError: if the input is not exactly a repository root URL.
    """
    url = raw_url.strip()
    if not url:
        raise InvalidRepositoryUrlError("The repository URL is empty.")
    if len(url) > MAX_URL_LENGTH:
        raise InvalidRepositoryUrlError(
            f"The repository URL is too long (max {MAX_URL_LENGTH} characters)."
        )
    if not url.isascii() or any(char.isspace() for char in url):
        raise InvalidRepositoryUrlError("The repository URL contains unsupported characters.")

    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise InvalidRepositoryUrlError("The repository URL is malformed.") from exc

    if parts.scheme.lower() != "https":
        raise InvalidRepositoryUrlError("Only https:// GitHub URLs are supported.")
    # Comparing the whole netloc (not just the hostname) also rejects user info
    # ("user@github.com") and explicit ports ("github.com:443").
    if parts.netloc.lower() not in _ALLOWED_HOSTS:
        raise InvalidRepositoryUrlError("Only repositories hosted on github.com are supported.")
    if parts.query or parts.fragment:
        raise InvalidRepositoryUrlError(
            "Use the repository root URL, without query string or fragment."
        )

    path = parts.path.removesuffix("/")
    segments = path.split("/")[1:] if path.startswith("/") else []
    if len(segments) != 2:
        raise InvalidRepositoryUrlError(
            "Use the repository root URL, e.g. https://github.com/owner/repository."
        )

    owner, name = segments
    name = name.removesuffix(".git")
    if not re.fullmatch(OWNER_PATTERN, owner):
        raise InvalidRepositoryUrlError(f"'{owner}' is not a valid GitHub owner name.")
    if not re.fullmatch(REPO_PATTERN, name) or name in _RESERVED_REPO_NAMES:
        raise InvalidRepositoryUrlError(f"'{name}' is not a valid GitHub repository name.")

    return GitHubRepoRef(owner=owner, name=name)
