"""Composition root: builds the long-lived objects the API needs, and releases them."""

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uaw.config import Settings
from uaw.connectors.github.connector import build_github_connector, create_github_http_client
from uaw.embeddings.voyage import VoyageEmbedder, create_voyage_http_client
from uaw.generation.answerer import Answerer
from uaw.generation.claude import ClaudeAnswerModel, create_anthropic_client
from uaw.ingestion.pipeline import IngestionPipeline
from uaw.ingestion.runner import IngestionRunner
from uaw.retrieval.retriever import Retriever
from uaw.storage.db import create_engine, create_session_factory
from uaw.storage.jobs import JobStore
from uaw.storage.models import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Services:
    session_factory: async_sessionmaker[AsyncSession]
    # Both None when no embedding API key is configured: imports and searches are
    # then refused.
    runner: IngestionRunner | None
    retriever: Retriever | None
    # None when the embedding or the Anthropic API key is missing.
    answerer: Answerer | None


async def build_services(settings: Settings, stack: AsyncExitStack) -> Services:
    """Create the services. Resources are released when ``stack`` closes, in reverse
    order: running imports are cancelled first, then HTTP clients and the database
    pool are closed."""
    engine = create_engine(settings)
    stack.push_async_callback(engine.dispose)
    session_factory = create_session_factory(engine)

    async with session_factory.begin() as session:
        interrupted = await JobStore(session).fail_interrupted()
    if interrupted:
        logger.warning("Marked %d interrupted import jobs as failed", interrupted)

    if settings.voyage_api_key is None:
        logger.warning("VOYAGE_API_KEY is not set: imports, searches and answers are disabled")
        return Services(session_factory=session_factory, runner=None, retriever=None, answerer=None)

    github_http = await stack.enter_async_context(create_github_http_client(settings))
    voyage_http = await stack.enter_async_context(
        create_voyage_http_client(settings.voyage_timeout_seconds)
    )
    embedder = VoyageEmbedder(
        voyage_http,
        api_key=settings.voyage_api_key.get_secret_value(),
        model=settings.embedding_model,
        dimensions=EMBEDDING_DIMENSIONS,
        max_batch_size=settings.embedding_batch_size,
        max_batch_chars=settings.embedding_batch_max_chars,
        max_retries=settings.voyage_max_retries,
    )
    pipeline = IngestionPipeline(
        session_factory,
        build_github_connector(settings, github_http),
        embedder,
        embed_batch_size=settings.embedding_batch_size,
    )
    runner = IngestionRunner(pipeline, max_concurrent=settings.max_concurrent_imports)
    stack.push_async_callback(runner.shutdown)
    retriever = Retriever(session_factory, embedder)
    return Services(
        session_factory=session_factory,
        runner=runner,
        retriever=retriever,
        answerer=_build_answerer(settings, stack, retriever),
    )


def _build_answerer(
    settings: Settings, stack: AsyncExitStack, retriever: Retriever
) -> Answerer | None:
    if settings.anthropic_api_key is None:
        logger.warning("ANTHROPIC_API_KEY is not set: answers are disabled")
        return None
    client = create_anthropic_client(
        settings.anthropic_api_key.get_secret_value(),
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    stack.push_async_callback(client.close)
    model = ClaudeAnswerModel(
        client,
        model=settings.llm_model,
        effort=settings.llm_effort,
        max_tokens=settings.llm_max_tokens,
        refusal_fallback=settings.llm_refusal_fallback,
    )
    return Answerer(retriever, model, top_k=settings.answer_top_k)
