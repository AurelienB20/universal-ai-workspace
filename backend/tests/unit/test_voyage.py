import json
from collections.abc import Callable

import httpx2 as httpx
import pytest

from uaw.embeddings.errors import EmbeddingConfigurationError, EmbeddingUnavailableError
from uaw.embeddings.voyage import VoyageEmbedder
from uaw.usage.meter import ModelUsage, metering

pytestmark = pytest.mark.anyio

DIMS = 4
Handler = Callable[[httpx.Request], httpx.Response]


def vector(seed: int) -> list[float]:
    return [float(seed)] * DIMS


def ok_response(request: httpx.Request) -> httpx.Response:
    """Echoes one vector per input, in reverse order, to check index-based matching."""
    inputs = json.loads(request.content)["input"]
    data = [
        {"object": "embedding", "embedding": vector(len(text)), "index": i}
        for i, text in enumerate(inputs)
    ]
    return httpx.Response(200, json={"data": data[::-1], "usage": {"total_tokens": 7}})


def make_embedder(
    handler: Handler, **kwargs: int
) -> tuple[VoyageEmbedder, list[httpx.Request], list[float]]:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    embedder = VoyageEmbedder(
        httpx.AsyncClient(transport=httpx.MockTransport(recording_handler)),
        api_key="secret-key",
        model="voyage-code-3",
        dimensions=DIMS,
        sleep=fake_sleep,
        **kwargs,
    )
    return embedder, requests, sleeps


def responses(*items: httpx.Response | Exception) -> Handler:
    queue = list(items)

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if item.status_code != 200 else ok_response(request)

    return handler


async def test_embed_documents_sends_expected_request() -> None:
    embedder, requests, _ = make_embedder(ok_response)

    vectors = await embedder.embed_documents(["a", "bb", "ccc"])

    # Vectors are matched by index although the response lists them in reverse.
    assert vectors == [vector(1), vector(2), vector(3)]
    request = requests[0]
    assert str(request.url) == "https://api.voyageai.com/v1/embeddings"
    assert request.headers["authorization"] == "Bearer secret-key"
    assert json.loads(request.content) == {
        "input": ["a", "bb", "ccc"],
        "model": "voyage-code-3",
        "input_type": "document",
        "output_dimension": DIMS,
        "truncation": False,
    }


async def test_embed_query_uses_query_input_type() -> None:
    embedder, requests, _ = make_embedder(ok_response)

    assert await embedder.embed_query("where is auth?") == vector(14)
    assert json.loads(requests[0].content)["input_type"] == "query"


async def test_large_inputs_are_split_into_batches_in_order() -> None:
    embedder, requests, _ = make_embedder(ok_response, max_batch_size=2, max_batch_chars=1000)

    vectors = await embedder.embed_documents(["a", "bb", "ccc", "dddd", "eeeee"])

    assert vectors == [vector(n) for n in range(1, 6)]
    assert [len(json.loads(r.content)["input"]) for r in requests] == [2, 2, 1]


async def test_empty_input_makes_no_request() -> None:
    embedder, requests, _ = make_embedder(ok_response)

    assert await embedder.embed_documents([]) == []
    assert requests == []


async def test_retries_rate_limits_and_server_errors() -> None:
    handler = responses(
        httpx.Response(429, headers={"retry-after": "3"}),
        httpx.Response(503),
        httpx.ConnectError("boom"),
        httpx.Response(200),
    )
    embedder, requests, sleeps = make_embedder(handler)

    assert await embedder.embed_documents(["a"]) == [vector(1)]
    assert len(requests) == 4
    assert sleeps[0] == 3.0  # Retry-After is honoured
    assert 2.0 <= sleeps[1] < 3.0 and 4.0 <= sleeps[2] < 5.0  # exponential backoff


async def test_gives_up_after_max_retries() -> None:
    embedder, requests, _ = make_embedder(lambda _: httpx.Response(500), max_retries=2)

    with pytest.raises(EmbeddingUnavailableError, match="Try again later"):
        await embedder.embed_documents(["a"])
    assert len(requests) == 3


async def test_retry_after_is_capped() -> None:
    handler = responses(httpx.Response(429, headers={"retry-after": "3600"}), httpx.Response(200))
    embedder, _, sleeps = make_embedder(handler)

    await embedder.embed_documents(["a"])

    assert sleeps == [60.0]


@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_credentials_are_not_retried(status: int) -> None:
    embedder, requests, _ = make_embedder(lambda _: httpx.Response(status))

    with pytest.raises(EmbeddingConfigurationError) as exc_info:
        await embedder.embed_documents(["a"])
    assert len(requests) == 1
    assert "secret-key" not in str(exc_info.value)


async def test_bad_request_is_not_retried_nor_shown_to_users() -> None:
    body = {"detail": "Input text too long: internal detail"}
    embedder, requests, _ = make_embedder(lambda _: httpx.Response(400, json=body))

    with pytest.raises(EmbeddingUnavailableError) as exc_info:
        await embedder.embed_documents(["a"])
    assert len(requests) == 1
    assert "internal detail" not in str(exc_info.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"data": [], "usage": {"total_tokens": 1}},  # missing vector
        {"data": [{"embedding": vector(1), "index": 0}] * 2, "usage": {"total_tokens": 1}},
        {"data": [{"embedding": vector(1), "index": 1}], "usage": {"total_tokens": 1}},
        {"data": [{"embedding": [1.0, 2.0], "index": 0}], "usage": {"total_tokens": 1}},
        {"data": [{"embedding": [1.0, 2.0, 3.0, "nan"], "index": 0}], "usage": {"total_tokens": 1}},
        {"unexpected": True},
    ],
    ids=["missing", "duplicate", "wrong-index", "wrong-dimension", "nan", "malformed"],
)
async def test_invalid_responses_are_rejected(payload: dict[str, object]) -> None:
    embedder, _, _ = make_embedder(lambda _: httpx.Response(200, json=payload))

    with pytest.raises(EmbeddingUnavailableError, match="Voyage AI returned"):
        await embedder.embed_documents(["a"])


async def test_billed_tokens_are_reported_to_the_usage_meter() -> None:
    embedder, _, _ = make_embedder(ok_response, max_batch_size=2)

    with metering() as meter:
        await embedder.embed_documents(["a", "b", "c"])  # two requests
        await embedder.embed_query("q")

    assert meter.usages == [ModelUsage("voyage", "voyage-code-3", requests=3, input_tokens=21)]
