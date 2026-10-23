"""Voyage AI embeddings client (https://docs.voyageai.com/reference/embeddings-api).

Responsibilities: batching within the API limits, retries with exponential backoff
on rate limits and server errors, and strict validation of the response (count,
order, dimension), so that a vector can never be attached to the wrong chunk.
"""

import asyncio
import logging
import math
import random
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal

import httpx2 as httpx
from pydantic import BaseModel, ValidationError

from uaw.embeddings.base import batch_ranges
from uaw.embeddings.errors import EmbeddingConfigurationError, EmbeddingUnavailableError
from uaw.usage.meter import record_usage

logger = logging.getLogger(__name__)

VOYAGE_EMBEDDINGS_URL = "https://api.voyageai.com/v1/embeddings"
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_SECONDS = 60.0

InputType = Literal["document", "query"]
Sleep = Callable[[float], Awaitable[None]]


class _EmbeddingItem(BaseModel):
    embedding: list[float]
    index: int


class _Usage(BaseModel):
    total_tokens: int


class _EmbeddingsPayload(BaseModel):
    data: list[_EmbeddingItem]
    usage: _Usage


class VoyageEmbedder:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        model: str,
        dimensions: int,
        max_batch_size: int = 128,
        max_batch_chars: int = 200_000,
        max_retries: int = 4,
        backoff_base_seconds: float = 1.0,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        # ``http`` is injected so tests can plug in a mock transport; its timeout
        # applies to each request. ``sleep`` is injected so tests do not wait.
        self._http = http
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._max_batch_size = max_batch_size
        self._max_batch_chars = max_batch_chars
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._sleep = sleep

    @property
    def model(self) -> str:
        return self._model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start, end in batch_ranges(
            texts, max_items=self._max_batch_size, max_chars=self._max_batch_chars
        ):
            vectors.extend(await self._embed_batch(texts[start:end], "document"))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed_batch([text], "query"))[0]

    async def _embed_batch(self, texts: Sequence[str], input_type: InputType) -> list[list[float]]:
        body = {
            "input": list(texts),
            "model": self._model,
            # Voyage prepends a retrieval prompt adapted to documents or queries.
            "input_type": input_type,
            "output_dimension": self._dimensions,
            # Fail loudly rather than silently embedding a truncated text.
            "truncation": False,
        }
        response = await self._post_with_retries(body)
        return self._parse(response, expected=len(texts))

    async def _post_with_retries(self, body: dict[str, object]) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(self._max_retries + 1):
            is_last = attempt == self._max_retries
            try:
                response = await self._http.post(VOYAGE_EMBEDDINGS_URL, json=body, headers=headers)
            except httpx.TransportError as exc:  # includes timeouts
                if is_last:
                    raise EmbeddingUnavailableError("Could not reach Voyage AI.") from exc
                logger.warning("Voyage request failed (%s), retrying", type(exc).__name__)
                await self._sleep(self._backoff(attempt))
                continue

            if response.is_success:
                return response
            if response.status_code not in RETRYABLE_STATUSES:
                _raise_for_status(response)
            if is_last:
                logger.error("Voyage still failing after retries (status %d)", response.status_code)
                raise EmbeddingUnavailableError(
                    "Voyage AI is unavailable or rate limited. Try again later."
                )
            delay = _retry_after(response) or self._backoff(attempt)
            logger.warning("Voyage returned %d, retrying in %.1fs", response.status_code, delay)
            await self._sleep(delay)
        raise AssertionError("unreachable")

    def _backoff(self, attempt: int) -> float:
        # 1s, 2s, 4s... plus jitter, so that parallel imports do not retry in lockstep.
        base = self._backoff_base_seconds * 2.0**attempt
        return base + random.uniform(0, self._backoff_base_seconds)

    def _parse(self, response: httpx.Response, *, expected: int) -> list[list[float]]:
        try:
            payload = _EmbeddingsPayload.model_validate_json(response.content)
        except ValidationError as exc:
            raise EmbeddingUnavailableError("Voyage AI returned an unexpected response.") from exc
        # Recorded before the checks below: a successful response is billed even if
        # its content is then rejected.
        record_usage("voyage", self._model, input_tokens=payload.usage.total_tokens)

        # Results are matched to inputs by ``index``, never by position in the list.
        if sorted(item.index for item in payload.data) != list(range(expected)):
            raise EmbeddingUnavailableError("Voyage AI returned an incomplete response.")
        for item in payload.data:
            if len(item.embedding) != self._dimensions or not all(
                math.isfinite(x) for x in item.embedding
            ):
                raise EmbeddingUnavailableError("Voyage AI returned an invalid embedding.")

        logger.debug("Embedded %d texts (%d tokens)", expected, payload.usage.total_tokens)
        return [item.embedding for item in sorted(payload.data, key=lambda item: item.index)]


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after", "")
    try:
        seconds = float(value)
    except ValueError:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS) if seconds >= 0 else None


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status in (401, 403):
        logger.error("Voyage rejected the configured API key (%d)", status)
        raise EmbeddingConfigurationError("Voyage AI rejected the server's credentials.")
    # 400 means a bug on our side (bad model name, text too long...): log the detail
    # for the operator, but do not show it to users.
    logger.error("Voyage rejected the request (%d): %s", status, response.text[:500])
    raise EmbeddingUnavailableError("Voyage AI rejected the embedding request.")


def create_voyage_http_client(timeout_seconds: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)
