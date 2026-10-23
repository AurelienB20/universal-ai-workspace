"""ClaudeAnswerModel against a mocked Messages API (no network)."""

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2 as httpx
import pytest

from uaw.generation.claude import DRAFT_ANSWER_SCHEMA, ClaudeAnswerModel
from uaw.generation.errors import (
    GenerationConfigurationError,
    GenerationRefusedError,
    GenerationUnavailableError,
)
from uaw.usage.meter import ModelUsage, metering

pytestmark = pytest.mark.anyio

MODEL = "claude-opus-5-5"
DRAFT = {"answer": "Signed with HMAC [S1].", "insufficient_context": False}

Responder = Callable[[httpx.Request], httpx.Response]


def message(content: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": content,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 80},
    } | overrides


def text(value: object) -> dict[str, Any]:
    return {"type": "text", "text": value if isinstance(value, str) else json.dumps(value)}


def reply(body: dict[str, Any], status: int = 200) -> Responder:
    return lambda request: httpx.Response(status, json=body)


class Recorder:
    def __init__(self, respond: Responder) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)


def model_with(respond: Responder, **options: Any) -> tuple[ClaudeAnswerModel, Recorder]:
    recorder = Recorder(respond)
    client = anthropic.AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx.MockTransport(recorder)),
    )
    params: dict[str, Any] = {"model": MODEL, "effort": "medium", "max_tokens": 4000} | options
    return ClaudeAnswerModel(client, **params), recorder


async def test_request_uses_structured_output_effort_and_refusal_fallback() -> None:
    model, recorder = model_with(reply(message([text(DRAFT)])))

    generation = await model.generate("system prompt", "user message")

    assert generation.draft.answer == "Signed with HMAC [S1]."
    assert (generation.model, generation.input_tokens, generation.output_tokens) == (
        MODEL,
        1200,
        80,
    )
    request = recorder.requests[0]
    body = json.loads(request.content)
    assert body["model"] == MODEL
    assert body["system"] == "system prompt"
    assert body["messages"] == [{"role": "user", "content": "user message"}]
    assert body["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": DRAFT_ANSWER_SCHEMA},
    }
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]
    # Opus 5.5 rejects disabled thinking and budget_tokens: the field is left out.
    assert "thinking" not in body


async def test_refusal_fallback_can_be_disabled() -> None:
    model, recorder = model_with(reply(message([text(DRAFT)])), refusal_fallback=False)

    await model.generate("s", "u")

    assert "fallbacks" not in json.loads(recorder.requests[0].content)
    assert "server-side-fallback" not in recorder.requests[0].headers.get("anthropic-beta", "")


async def test_answer_after_a_mid_answer_fallback_is_the_fallback_models() -> None:
    content = [
        text('{"answer": "partial'),
        {"type": "fallback", "from": {"model": MODEL}, "to": {"model": "claude-opus-4-8"}},
        {"type": "thinking", "thinking": "", "signature": "sig"},
        text(DRAFT),
    ]
    model, _ = model_with(reply(message(content, model="claude-opus-4-8")))

    generation = await model.generate("s", "u")

    assert generation.draft.answer == DRAFT["answer"]
    assert generation.model == "claude-opus-4-8"


async def test_refusal_is_reported_without_reading_the_content() -> None:
    body = message(
        [text("I cannot help")],
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": None},
    )
    model, _ = model_with(reply(body))

    with pytest.raises(GenerationRefusedError):
        await model.generate("s", "u")


async def test_truncated_answer_is_an_error() -> None:
    model, _ = model_with(reply(message([text('{"answer": "cut')], stop_reason="max_tokens")))

    with pytest.raises(GenerationUnavailableError, match="too long"):
        await model.generate("s", "u")


@pytest.mark.parametrize(
    "content",
    [[], [text("not json")], [text({"answer": "x"})], [text(DRAFT | {"extra": 1})]],
)
async def test_unexpected_content_is_rejected(content: list[dict[str, Any]]) -> None:
    model, _ = model_with(reply(message(content)))

    with pytest.raises(GenerationUnavailableError, match="unexpected"):
        await model.generate("s", "u")


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, GenerationConfigurationError),
        (403, GenerationConfigurationError),
        (404, GenerationConfigurationError),
        (400, GenerationUnavailableError),
        (429, GenerationUnavailableError),
        (529, GenerationUnavailableError),
    ],
)
async def test_api_errors_become_user_safe_errors(status: int, error: type[Exception]) -> None:
    body = {"type": "error", "error": {"type": "x", "message": "secret detail sk-ant-123"}}
    model, _ = model_with(reply(body, status))

    with pytest.raises(error) as exc_info:
        await model.generate("s", "u")
    assert "sk-ant" not in str(exc_info.value)


async def test_network_errors_are_reported_as_unavailable() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    model, _ = model_with(fail)

    with pytest.raises(GenerationUnavailableError):
        await model.generate("s", "u")


async def test_billed_tokens_are_reported_even_for_a_refusal() -> None:
    body = message(
        [text("I cannot help")],
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": None},
    )
    model, _ = model_with(reply(body))

    with metering() as meter, pytest.raises(GenerationRefusedError):
        await model.generate("s", "u")

    assert meter.usages == [
        ModelUsage("anthropic", MODEL, requests=1, input_tokens=1200, output_tokens=80)
    ]
