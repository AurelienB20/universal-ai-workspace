"""Tests against the real Voyage AI API. Opt-in: ``uv run pytest -m live``.

Skipped unless VOYAGE_API_KEY is set (environment or backend/.env). Uses a few
hundred tokens.
"""

import math

import pytest

from uaw.config import Settings
from uaw.embeddings.voyage import VoyageEmbedder, create_voyage_http_client
from uaw.storage.models import EMBEDDING_DIMENSIONS

pytestmark = [pytest.mark.live, pytest.mark.anyio]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def test_code_search_ranks_the_relevant_chunk_first() -> None:
    settings = Settings()
    if settings.voyage_api_key is None:
        pytest.skip("VOYAGE_API_KEY is not set")

    async with create_voyage_http_client(settings.voyage_timeout_seconds) as http:
        embedder = VoyageEmbedder(
            http,
            api_key=settings.voyage_api_key.get_secret_value(),
            model=settings.embedding_model,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        documents = await embedder.embed_documents(
            [
                "File: src/auth/jwt.py\n\ndef verify_token(token):\n"
                "    return jwt.decode(token, SECRET, algorithms=['HS256'])\n",
                "File: src/utils/dates.py\n\ndef parse_date(value):\n"
                "    return datetime.strptime(value, '%Y-%m-%d')\n",
            ]
        )
        query = await embedder.embed_query("Where are authentication tokens validated?")

    assert all(len(vector) == EMBEDDING_DIMENSIONS for vector in [*documents, query])
    assert cosine(query, documents[0]) > cosine(query, documents[1])
