"""Claude client for answer generation (Anthropic Messages API, official SDK).

Responsibilities: one structured-output request per question, checks on the stop
reason before reading the content (refusal, truncation), strict validation of the
returned JSON, and translation of SDK errors into user-safe messages. Retries of rate
limits, server errors and timeouts are done by the SDK (``max_retries``).
"""

import logging
from typing import Any, Protocol

import anthropic
from anthropic.types.beta import BetaMessage
from pydantic import BaseModel, ConfigDict, ValidationError

from uaw.config import Effort
from uaw.generation.errors import (
    GenerationConfigurationError,
    GenerationRefusedError,
    GenerationUnavailableError,
)

logger = logging.getLogger(__name__)

# Server-side refusal fallback, "default" form: the API picks the fallback model from
# the refusal category. This header is required by that form (the list form uses
# another one).
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class DraftAnswer(BaseModel):
    """What the model must return (enforced by the API with a JSON schema)."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    insufficient_context: bool


# Written by hand rather than generated: structured outputs require
# "additionalProperties": false and every property listed in "required".
DRAFT_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "Markdown answer citing sources as [S1], [S2]...",
        },
        "insufficient_context": {
            "type": "boolean",
            "description": "True if the sources do not contain enough to answer.",
        },
    },
    "required": ["answer", "insufficient_context"],
    "additionalProperties": False,
}


class Generation(BaseModel):
    model_config = ConfigDict(frozen=True)

    draft: DraftAnswer
    # Model that produced the answer: differs from the requested one after a fallback.
    model: str
    input_tokens: int
    output_tokens: int


class AnswerModel(Protocol):
    """Generates a draft answer from a system prompt and a user message."""

    async def generate(self, system: str, user_message: str) -> Generation: ...


class ClaudeAnswerModel:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        *,
        model: str,
        effort: Effort,
        max_tokens: int,
        refusal_fallback: bool = True,
    ) -> None:
        # ``client`` is injected so tests can plug in a mock HTTP transport.
        self._client = client
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._refusal_fallback = refusal_fallback

    async def generate(self, system: str, user_message: str) -> Generation:
        fallback: dict[str, Any] = (
            {"fallbacks": "default", "betas": [REFUSAL_FALLBACK_BETA]}
            if self._refusal_fallback
            else {}
        )
        try:
            message = await self._client.beta.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_message}],
                output_config={
                    "effort": self._effort,
                    "format": {"type": "json_schema", "schema": DRAFT_ANSWER_SCHEMA},
                },
                **fallback,
            )
        except anthropic.APIError as exc:
            raise _translate(exc) from exc
        return self._parse(message)

    def _parse(self, message: BetaMessage) -> Generation:
        # The stop reason is checked first: a refused or truncated response does not
        # contain a complete JSON document.
        if message.stop_reason == "refusal":
            category = message.stop_details.category if message.stop_details else None
            logger.warning("Claude refused to answer (category=%s, id=%s)", category, message.id)
            raise GenerationRefusedError("Claude declined to answer this question.")
        if message.stop_reason == "max_tokens":
            logger.error("Claude reached max_tokens=%d (id=%s)", self._max_tokens, message.id)
            raise GenerationUnavailableError("The answer was too long to be generated completely.")

        text = _final_text(message)
        try:
            if text is None:
                raise ValueError("no text block")
            draft = DraftAnswer.model_validate_json(text)
        except (ValueError, ValidationError) as exc:
            logger.error("Unexpected Claude response (id=%s): %s", message.id, exc)
            raise GenerationUnavailableError("Claude returned an unexpected response.") from exc

        if message.model != self._model:
            logger.info("Answer served by fallback model %s", message.model)
        return Generation(
            draft=draft,
            model=message.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )


def _final_text(message: BetaMessage) -> str | None:
    """The JSON text of the model that completed the answer.

    After a refusal mid-generation, the content holds the declined model's partial
    output, a ``fallback`` block, then the fallback model's output: only the text
    after the last ``fallback`` block is the answer.
    """
    text: str | None = None
    for block in message.content:
        if block.type == "fallback":
            text = None
        elif block.type == "text" and text is None:
            text = block.text
    return text


def _translate(exc: anthropic.APIError) -> Exception:
    """SDK errors -> user-safe errors. Details are logged for the operator only."""
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        logger.error("Anthropic rejected the configured API key (%s)", type(exc).__name__)
        return GenerationConfigurationError("Claude rejected the server's credentials.")
    if isinstance(exc, anthropic.NotFoundError):
        logger.error("Anthropic model or endpoint not found: %s", exc.message)
        return GenerationConfigurationError("The configured Claude model is not available.")
    if isinstance(exc, anthropic.RateLimitError | anthropic.APIConnectionError):
        # Includes timeouts. The SDK has already retried.
        logger.warning("Claude unavailable after retries (%s)", type(exc).__name__)
        return GenerationUnavailableError("Claude is unavailable or rate limited. Try again later.")
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        logger.warning("Claude server error %d after retries", exc.status_code)
        return GenerationUnavailableError("Claude is unavailable or rate limited. Try again later.")
    # 400 and similar: a bug on our side (invalid parameter, prompt too long...).
    logger.error("Claude rejected the request (%s): %s", type(exc).__name__, exc)
    return GenerationUnavailableError("Claude rejected the request.")


def create_anthropic_client(
    api_key: str, *, timeout_seconds: float, max_retries: int
) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key=api_key, timeout=timeout_seconds, max_retries=max_retries
    )
