"""Tests against the real Anthropic API. Opt-in: ``uv run pytest -m live``.

Skipped unless ANTHROPIC_API_KEY is set (environment or backend/.env). Uses a few
thousand tokens of the configured model.
"""

import pytest

from tests.generation_fakes import hit
from uaw.config import Settings
from uaw.generation.citations import resolve_citations
from uaw.generation.claude import (
    AnswerDelta,
    ClaudeAnswerModel,
    Generation,
    create_anthropic_client,
)
from uaw.generation.prompt import SYSTEM_PROMPT, build_user_message, label_sources

pytestmark = [pytest.mark.live, pytest.mark.anyio]

PASSAGES = [
    hit(
        "src/auth/tokens.py",
        10,
        14,
        "def verify(token: str) -> bool:\n"
        "    payload, signature = token.rsplit('.', 1)\n"
        "    return hmac.compare_digest(signature, sign(payload))\n",
    ),
    hit("README.md", 1, 3, "# Demo\n\nA demo project.\n"),
]


def claude_model(settings: Settings) -> ClaudeAnswerModel:
    if settings.anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY is not set")
    client = create_anthropic_client(
        settings.anthropic_api_key.get_secret_value(),
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    return ClaudeAnswerModel(
        client,
        model=settings.llm_model,
        effort=settings.llm_effort,
        max_tokens=settings.llm_max_tokens,
        refusal_fallback=settings.llm_refusal_fallback,
    )


async def test_answer_cites_the_relevant_passage() -> None:
    sources = label_sources(PASSAGES)
    model = claude_model(Settings())

    generation = await model.generate(
        SYSTEM_PROMPT, build_user_message("How are tokens verified?", sources)
    )
    resolved = resolve_citations(generation.draft.answer, sources)

    assert not generation.draft.insufficient_context
    assert "S1" in [citation.id for citation in resolved.citations]
    assert resolved.unknown_ids == []


async def test_unanswerable_question_is_flagged() -> None:
    sources = label_sources(PASSAGES)
    model = claude_model(Settings())

    generation = await model.generate(
        SYSTEM_PROMPT, build_user_message("Which database does this project use?", sources)
    )

    assert generation.draft.insufficient_context


async def test_streamed_draft_is_the_final_answer() -> None:
    sources = label_sources(PASSAGES)
    model = claude_model(Settings())
    deltas: list[str] = []
    final: Generation | None = None

    async for event in model.stream(
        SYSTEM_PROMPT, build_user_message("How are tokens verified?", sources)
    ):
        if isinstance(event, AnswerDelta):
            deltas.append(event.text)
        elif isinstance(event, Generation):
            final = event

    assert final is not None
    # Several pieces, which put together are exactly the validated answer.
    assert len(deltas) > 1
    assert "".join(deltas) == final.draft.answer
