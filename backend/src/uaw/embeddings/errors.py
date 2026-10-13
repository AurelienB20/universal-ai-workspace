"""Errors raised by embedding providers.

Every message is safe to show to end users: it never contains API keys or raw
response bodies.
"""


class EmbeddingError(Exception):
    """Base class for all embedding errors."""


class EmbeddingConfigurationError(EmbeddingError):
    """The provider rejected the server's configuration (API key, model...)."""


class EmbeddingUnavailableError(EmbeddingError):
    """The provider could not be reached, kept failing or answered unexpectedly."""
