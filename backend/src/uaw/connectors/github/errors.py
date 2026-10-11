"""Errors raised by the GitHub connector.

Every message is safe to show to end users: it never contains tokens, internal URLs
or raw response bodies.
"""


class GitHubConnectorError(Exception):
    """Base class for all GitHub connector errors."""


class RepositoryNotFoundError(GitHubConnectorError):
    """The repository does not exist or is not accessible."""


class RepositoryNotPublicError(GitHubConnectorError):
    """The repository exists but is not public."""


class EmptyRepositoryError(GitHubConnectorError):
    """The repository has no commits."""


class RepositoryTooLargeError(GitHubConnectorError):
    """The repository or its archive exceeds the configured import limits."""


class GitHubRateLimitError(GitHubConnectorError):
    """GitHub's API rate limit has been reached."""


class GitHubUnavailableError(GitHubConnectorError):
    """GitHub could not be reached or returned an unexpected response."""


class InvalidArchiveError(GitHubConnectorError):
    """The downloaded archive is corrupt or has an unexpected layout."""
