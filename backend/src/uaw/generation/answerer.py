"""Question answering: retrieve passages, ask the model, check its citations."""

import logging

from pydantic import BaseModel, ConfigDict

from uaw.connectors.github.url import GitHubRepoRef
from uaw.generation.citations import Citation, resolve_citations
from uaw.generation.claude import AnswerModel
from uaw.generation.prompt import SYSTEM_PROMPT, build_user_message, label_sources
from uaw.retrieval.retriever import Retriever

logger = logging.getLogger(__name__)

NO_SOURCES_MESSAGE = "The indexed repository has no content to answer from."


class Answer(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: str
    commit_sha: str
    # Markdown, citing sources as [S1], [S2]... Every marker has a citation below.
    answer: str
    # True when the retrieved passages did not contain enough to answer.
    insufficient_context: bool
    citations: list[Citation]
    # Model that wrote the answer (None when no model was called).
    model: str | None


class Answerer:
    def __init__(self, retriever: Retriever, model: AnswerModel, *, top_k: int) -> None:
        self._retriever = retriever
        self._model = model
        self._top_k = top_k

    async def ask(self, repository: GitHubRepoRef, question: str) -> Answer:
        result = await self._retriever.search(repository, question, top_k=self._top_k)
        if not result.hits:
            return Answer(
                repository=result.repository,
                commit_sha=result.commit_sha,
                answer=NO_SOURCES_MESSAGE,
                insufficient_context=True,
                citations=[],
                model=None,
            )

        sources = label_sources(result.hits)
        generation = await self._model.generate(
            SYSTEM_PROMPT, build_user_message(question, sources)
        )
        resolved = resolve_citations(generation.draft.answer, sources)
        logger.info(
            "Answered a question on %s with %s (%d sources, %d cited, %d+%d tokens)",
            result.repository,
            generation.model,
            len(sources),
            len(resolved.citations),
            generation.input_tokens,
            generation.output_tokens,
        )
        return Answer(
            repository=result.repository,
            commit_sha=result.commit_sha,
            answer=resolved.text,
            insufficient_context=generation.draft.insufficient_context,
            citations=resolved.citations,
            model=generation.model,
        )
