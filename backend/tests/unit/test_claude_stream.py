"""ClaudeAnswerModel.stream against a mocked streaming Messages API (no network)."""

import json
from typing import Any

import httpx2 as httpx
import pytest

from tests.unit.test_claude_model import DRAFT, MODEL, message, model_with
from uaw.generation.claude import AnswerDelta, AnswerRestart, Generation, StreamEvent
from uaw.generation.errors import GenerationRefusedError, GenerationUnavailableError
from uaw.usage.meter import ModelUsage, metering

pytestmark = pytest.mark.anyio

FALLBACK_MODEL = "claude-opus-4-8"

Block = tuple[dict[str, Any], list[str]]


def text_block(*deltas: str) -> Block:
    return {"type": "text", "text": ""}, list(deltas)


def chunks(value: str, size: int = 7) -> list[str]:
    return [value[start : start + size] for start in range(0, len(value), size)]


def stream_body(
    blocks: list[Block],
    *,
    stop_reason: str = "end_turn",
    model: str = MODEL,
    stop_details: dict[str, Any] | None = None,
) -> str:
    start = message([], model=MODEL, stop_reason=None)
    start["usage"] = {"input_tokens": 1200, "output_tokens": 1}
    events: list[dict[str, Any]] = [{"type": "message_start", "message": start}]
    for index, (block, deltas) in enumerate(blocks):
        events.append({"type": "content_block_start", "index": index, "content_block": block})
        events.extend(
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "text_delta", "text": delta},
            }
            for delta in deltas
        )
        events.append({"type": "content_block_stop", "index": index})
    events.append(
        {
            "type": "message_delta",
            "delta": {
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "stop_details": stop_details,
            },
            "usage": {"output_tokens": 80},
        }
    )
    events.append({"type": "message_stop"})
    return "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)


def streaming(body: str) -> Any:
    return lambda request: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content=body.encode()
    )


async def collect(model: Any) -> list[StreamEvent]:
    return [event async for event in model.stream("system prompt", "user message")]


def drafts(events: list[StreamEvent]) -> str:
    return "".join(event.text for event in events if isinstance(event, AnswerDelta))


async def test_the_answer_text_arrives_in_pieces_then_the_checked_generation() -> None:
    model, recorder = model_with(streaming(stream_body([text_block(*chunks(json.dumps(DRAFT)))])))

    with metering() as meter:
        events = await collect(model)

    assert drafts(events) == DRAFT["answer"]
    assert len([event for event in events if isinstance(event, AnswerDelta)]) > 1
    final = events[-1]
    assert isinstance(final, Generation)
    assert final.draft.answer == DRAFT["answer"]
    assert (final.model, final.input_tokens, final.output_tokens) == (MODEL, 1200, 80)
    # Counted once, with the final totals.
    assert meter.usages == [ModelUsage("anthropic", MODEL, 1, 1200, 80)]
    # The same request as ``generate``, streamed.
    body = json.loads(recorder.requests[0].content)
    assert body["stream"] is True
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"


async def test_a_mid_answer_fallback_restarts_the_draft() -> None:
    blocks = [
        text_block('{"answer": "par', "tial"),
        (
            {"type": "fallback", "from": {"model": MODEL}, "to": {"model": FALLBACK_MODEL}},
            [],
        ),
        ({"type": "thinking", "thinking": "", "signature": "sig"}, []),
        text_block(*chunks(json.dumps(DRAFT))),
    ]
    model, _ = model_with(streaming(stream_body(blocks, model=FALLBACK_MODEL)))

    events = await collect(model)

    restart = next(index for index, event in enumerate(events) if isinstance(event, AnswerRestart))
    assert drafts(events[:restart]) == "partial"
    assert drafts(events[restart:]) == DRAFT["answer"]
    final = events[-1]
    assert isinstance(final, Generation)
    assert final.draft.answer == DRAFT["answer"]
    assert final.model == FALLBACK_MODEL


async def test_a_fallback_before_any_text_needs_no_restart() -> None:
    blocks = [
        ({"type": "fallback", "from": {"model": MODEL}, "to": {"model": FALLBACK_MODEL}}, []),
        text_block(json.dumps(DRAFT)),
    ]
    model, _ = model_with(streaming(stream_body(blocks, model=FALLBACK_MODEL)))

    events = await collect(model)

    assert not any(isinstance(event, AnswerRestart) for event in events)
    assert drafts(events) == DRAFT["answer"]


async def test_a_refusal_at_the_end_raises_after_the_draft() -> None:
    body = stream_body(
        [text_block('{"answer": "I will', " not")],
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": None},
    )
    model, _ = model_with(streaming(body))
    events: list[StreamEvent] = []

    with metering() as meter, pytest.raises(GenerationRefusedError):
        async for event in model.stream("s", "u"):
            events.append(event)

    assert drafts(events) == "I will not"
    # Billed all the same.
    assert meter.usages == [ModelUsage("anthropic", MODEL, 1, 1200, 80)]


async def test_a_truncated_answer_is_an_error() -> None:
    body = stream_body([text_block('{"answer": "Too lo')], stop_reason="max_tokens")
    model, _ = model_with(streaming(body))

    with pytest.raises(GenerationUnavailableError, match="too long"):
        await collect(model)


async def test_an_abandoned_stream_records_the_tokens_already_generated() -> None:
    first = '{"answer": "Signed'  # 18 characters: about 6 tokens
    model, _ = model_with(streaming(stream_body([text_block(first, " with HMAC")])))

    with metering() as meter:
        events = model.stream("s", "u")
        assert await anext(events) == AnswerDelta(text="Signed")
        await events.aclose()

    # The final count never arrived: input from message_start, output estimated.
    assert meter.usages == [ModelUsage("anthropic", MODEL, 1, 1200, 6)]


async def test_provider_errors_are_translated() -> None:
    model, _ = model_with(lambda request: httpx.Response(529, json={"type": "error"}))

    with metering() as meter, pytest.raises(GenerationUnavailableError):
        await collect(model)

    assert meter.usages == []
