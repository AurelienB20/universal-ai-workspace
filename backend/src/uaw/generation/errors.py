"""Errors raised while generating answers.

Every message is safe to show to end users: it never contains API keys, prompts or
raw response bodies.
"""


class GenerationError(Exception):
    """Base class for all generation errors."""


class GenerationConfigurationError(GenerationError):
    """The provider rejected the server's configuration (API key, model...)."""


class GenerationUnavailableError(GenerationError):
    """The provider could not be reached, kept failing or answered unexpectedly."""


class GenerationRefusedError(GenerationError):
    """The model declined to answer (safety refusal)."""
