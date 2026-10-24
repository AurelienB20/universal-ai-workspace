import json
from collections.abc import Callable

import httpx2 as httpx
import pytest

from uaw.embeddings.errors import EmbeddingUnavailableError
from uaw.embeddings.voyage import MAX_RERANK_DOCUMENTS, VOYAGE_RERANK_URL, VoyageReranker
from uaw.usage.meter import ModelUsage, metering

pytestmark = pytest.mark.anyio

Handler = Callable[[httpx.Request], httpx.Response]


def by_length(request: httpx.Request) -> httpx.Response:
    """Scores each document by its length, sorted by relevance as the API does."""
    documents = json.loads(request.content)["documents"]
    data = sorted(
        ({"index": i, "relevance_score": len(doc) / 100} for i, doc in enumerate(documents)),
        key=lambda item: -item["relevance_score"],
    )
    return httpx.Response(200, json={"object": "list", "data": data, "usage": {"total_tokens": 42}})


def make_reranker(handler: Handler) -> tuple[VoyageReranker, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    async def no_sleep(seconds: float) -> None:
        pass

    reranker = VoyageReranker(
        httpx.AsyncClient(transport=httpx.MockTransport(recording)),
        api_key="secret-key",
        model="rerank-3",
        sleep=no_sleep,
    )
    return reranker, requests


async def test_scores_come_back_in_input_order_and_are_metered() -> None:
    reranker, requests = make_reranker(by_length)

    with metering() as meter:
        scores = await reranker.rerank("where?", ["aa", "a", "aaaa"])

    # The API returns them sorted by relevance; they are matched back by index.
    assert scores == [0.02, 0.01, 0.04]
    [request] = requests
    assert str(request.url) == VOYAGE_RERANK_URL
    assert request.headers["authorization"] == "Bearer secret-key"
    body = json.loads(request.content)
    assert body == {
        "query": "where?",
        "documents": ["aa", "a", "aaaa"],
        "model": "rerank-3",
        "truncation": True,
    }
    assert meter.usages == [ModelUsage("voyage", "rerank-3", 1, 42, 0)]


async def test_no_documents_means_no_call() -> None:
    reranker, requests = make_reranker(by_length)

    assert await reranker.rerank("where?", []) == []
    assert requests == []


async def test_too_many_documents_are_refused_before_any_call() -> None:
    reranker, requests = make_reranker(by_length)

    with pytest.raises(ValueError):
        await reranker.rerank("q", ["d"] * (MAX_RERANK_DOCUMENTS + 1))
    assert requests == []


@pytest.mark.parametrize(
    "data",
    [
        [{"index": 0, "relevance_score": 0.5}],  # one score missing
        [{"index": 0, "relevance_score": 0.5}, {"index": 0, "relevance_score": 0.4}],
        [{"index": 0, "relevance_score": 0.5}, {"index": 5, "relevance_score": 0.4}],
    ],
)
async def test_incomplete_responses_are_rejected(data: list[dict[str, object]]) -> None:
    reranker, _ = make_reranker(
        lambda request: httpx.Response(200, json={"data": data, "usage": {"total_tokens": 1}})
    )

    with pytest.raises(EmbeddingUnavailableError, match="incomplete"):
        await reranker.rerank("q", ["a", "b"])


async def test_server_errors_are_retried() -> None:
    answers = [httpx.Response(503), None]

    def flaky(request: httpx.Request) -> httpx.Response:
        answer = answers.pop(0)
        return answer if answer is not None else by_length(request)

    reranker, requests = make_reranker(flaky)

    assert await reranker.rerank("q", ["a"]) == [0.01]
    assert len(requests) == 2
