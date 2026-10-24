"""Question answering: retrieve passages, ask the model, check its citations."""

import logging
import time

from pydantic import BaseModel, ConfigDict

from uaw.connectors.github.url import GitHubRepoRef
from uaw.generation.citations import Citation, resolve_citations
from uaw.generation.claude import AnswerModel
from uaw.generation.prompt import SYSTEM_PROMPT, Source, build_user_message, label_sources
from uaw.retrieval.retriever import Retriever

logger = logging.getLogger(__name__)

NO_SOURCES_MESSAGE = "The indexed repository has no content to answer from."


class RetrievedPassage(BaseModel):
    """A passage shown to the model, in retrieval order."""

    model_config = ConfigDict(frozen=True)

    id: str
    path: str
    start_line: int
    end_line: int
    section: str | None
    content: str
    # Cosine similarity with the question: compares the passages of one answer.
    score: float
    # Relevance from the reranker, when one reordered the passages.
    rerank_score: float | None = None
    url: str
    # Whether the final answer cites it.
    cited: bool


class AnswerTrace(BaseModel):
    """How the answer was built, to show the evidence behind it (no extra cost: all of
    it is known while answering)."""

    model_config = ConfigDict(frozen=True)

    passages: list[RetrievedPassage]
    # IDs the model cited although they were not provided: removed from the answer.
    removed_citations: list[str]
    # Embedding the question and searching the index.
    retrieval_ms: int
    generation_ms: int
    input_tokens: int
    output_tokens: int


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
    # None for answers cached before traces existed.
    trace: AnswerTrace | None = None


class Answerer:
    def __init__(self, retriever: Retriever, model: AnswerModel, *, top_k: int) -> None:
        self._retriever = retriever
        self._model = model
        self._top_k = top_k

    async def ask(self, repository: GitHubRepoRef, question: str) -> Answer:
        started = time.perf_counter()
        result = await self._retriever.search(repository, question, top_k=self._top_k)
        retrieval_ms = _elapsed_ms(started)
        if not result.hits:
            return Answer(
                repository=result.repository,
                commit_sha=result.commit_sha,
                answer=NO_SOURCES_MESSAGE,
                insufficient_context=True,
                citations=[],
                model=None,
                trace=AnswerTrace(
                    passages=[],
                    removed_citations=[],
                    retrieval_ms=retrieval_ms,
                    generation_ms=0,
                    input_tokens=0,
                    output_tokens=0,
                ),
            )

        sources = label_sources(result.hits)
        started = time.perf_counter()
        generation = await self._model.generate(
            SYSTEM_PROMPT, build_user_message(question, sources)
        )
        generation_ms = _elapsed_ms(started)
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
        cited_ids = {citation.id for citation in resolved.citations}
        return Answer(
            repository=result.repository,
            commit_sha=result.commit_sha,
            answer=resolved.text,
            insufficient_context=generation.draft.insufficient_context,
            citations=resolved.citations,
            model=generation.model,
            trace=AnswerTrace(
                passages=[_passage(source, source.id in cited_ids) for source in sources],
                removed_citations=resolved.unknown_ids,
                retrieval_ms=retrieval_ms,
                generation_ms=generation_ms,
                input_tokens=generation.input_tokens,
                output_tokens=generation.output_tokens,
            ),
        )


def _passage(source: Source, cited: bool) -> RetrievedPassage:
    hit = source.hit
    return RetrievedPassage(
        id=source.id,
        path=hit.path,
        start_line=hit.start_line,
        end_line=hit.end_line,
        section=hit.section,
        content=hit.content,
        score=hit.score,
        rerank_score=hit.rerank_score,
        url=hit.url,
        cited=cited,
    )


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
