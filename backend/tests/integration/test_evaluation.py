"""Evaluation runs against a real snapshot, with a fake embedder."""

import re

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.test_search import QUERY, AxisEmbedder, add_snapshot, vector
from uaw.evaluation.dataset import EvalDataset
from uaw.evaluation.runner import EvaluationError, evaluate_dataset
from uaw.retrieval.retriever import Retriever

pytestmark = [pytest.mark.db, pytest.mark.anyio]


def dataset(*relevant: list[str]) -> EvalDataset:
    return EvalDataset.model_validate(
        {
            "repository": "octo/demo",
            "commit_sha": "b" * 40,
            "questions": [
                {"id": f"q{i}", "question": f"Question {i}?", "relevant_paths": paths}
                for i, paths in enumerate(relevant)
            ],
        }
    )


async def test_metrics_are_computed_from_real_searches(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(
            session,
            files={
                "best.py": [QUERY],
                "second.py": [vector((0, 1.0), (1, 1.0))],
                "far.py": [vector((2, 1.0))],
            },
        )
    embedder = AxisEmbedder()

    run = await evaluate_dataset(
        dataset(["best.py"], ["second.py"], ["far.py"]),
        Retriever(session_factory, embedder),
        session_factory,
        top_k=2,
    )

    assert embedder.queries == ["Question 0?", "Question 1?", "Question 2?"]
    assert run.repository == "octo/demo"
    assert [o.first_relevant_rank for o in run.report.outcomes] == [1, 2, None]
    assert run.report.hit_rate == {1: pytest.approx(1 / 3)}
    assert run.report.mrr == pytest.approx(0.5)


async def test_labels_must_point_to_indexed_files(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(session, files={"a.py": [QUERY]})
    embedder = AxisEmbedder()

    with pytest.raises(EvaluationError, match=re.escape("renamed.py")):
        await evaluate_dataset(
            dataset(["a.py"], ["renamed.py"]),
            Retriever(session_factory, embedder),
            session_factory,
            top_k=5,
        )
    assert embedder.queries == []


async def test_repository_must_be_imported(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(
        EvaluationError, match=re.escape("Import https://github.com/octo/demo first")
    ):
        await evaluate_dataset(
            dataset(["a.py"]), Retriever(session_factory, AxisEmbedder()), session_factory, top_k=5
        )
