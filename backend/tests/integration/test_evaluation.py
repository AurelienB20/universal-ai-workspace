"""Evaluation runs against a real snapshot, with a fake embedder."""

import re
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.test_search import QUERY, AxisEmbedder, add_snapshot, vector
from uaw.evaluation.dataset import EvalDataset
from uaw.evaluation.runner import EvaluationError, evaluate_dataset
from uaw.retrieval.retriever import Retriever

pytestmark = [pytest.mark.db, pytest.mark.anyio]


def dataset(*questions: dict[str, Any]) -> EvalDataset:
    return EvalDataset.model_validate(
        {
            "repository": "octo/demo",
            "commit_sha": "b" * 40,
            "questions": [
                {"id": f"q{i}", "question": f"Question {i}?"} | question
                for i, question in enumerate(questions)
            ],
        }
    )


def evidence(path: str, start: int | None = None, end: int | None = None) -> dict[str, Any]:
    if start is None:
        return {"evidence": [{"path": path}]}
    return {"evidence": [{"path": path, "start_line": start, "end_line": end}]}


async def add_files(session_factory: async_sessionmaker[AsyncSession]) -> None:
    # add_snapshot makes one single-line chunk per vector: line 1, line 2...
    async with session_factory.begin() as session:
        await add_snapshot(
            session,
            files={
                "best.py": [QUERY, vector((0, 1.0), (1, 2.0))],
                "second.py": [vector((0, 1.0), (1, 1.0))],
                "far.py": [vector((2, 1.0))],
            },
        )


async def test_metrics_are_computed_from_real_searches(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_files(session_factory)
    embedder = AxisEmbedder()

    run = await evaluate_dataset(
        dataset(
            evidence("best.py", 1, 1),
            evidence("best.py", 2, 2) | {"category": "paraphrase"},
            evidence("far.py"),
            {"category": "unanswerable", "split": "test"},
        ),
        Retriever(session_factory, embedder),
        session_factory,
        top_k=2,
    )

    assert embedder.queries == [f"Question {i}?" for i in range(4)]
    assert run.repository == "octo/demo"
    ranks = [o.first_relevant_rank for o in run.report.outcomes]
    # Ranking: best.py:1, then second.py:1, then best.py:2 (outside the top 2).
    assert ranks[0] == {"files": 1, "lines": 1}
    assert ranks[1] == {"files": 1, "lines": None}
    assert ranks[2] == {"files": None, "lines": None}
    assert run.report.unanswerable == 1
    assert run.report.outcomes[3].top_score == pytest.approx(1.0)
    assert run.report.overall["lines"].hit_rate == {1: pytest.approx(1 / 3)}
    assert run.report.overall["files"].hit_rate == {1: pytest.approx(2 / 3)}


async def test_a_split_can_be_evaluated_alone(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_files(session_factory)
    embedder = AxisEmbedder()

    run = await evaluate_dataset(
        dataset(evidence("best.py"), evidence("far.py") | {"split": "test"}),
        Retriever(session_factory, embedder),
        session_factory,
        top_k=2,
        split="test",
    )

    assert embedder.queries == ["Question 1?"]
    assert [o.question_id for o in run.report.outcomes] == ["q1"]


@pytest.mark.parametrize(
    ("label", "problem"),
    [
        (evidence("renamed.py"), "q1: renamed.py is not indexed"),
        (evidence("best.py", 2, 9), "q1: best.py has 2 lines, label ends at 9"),
    ],
)
async def test_labels_must_match_the_indexed_snapshot(
    session_factory: async_sessionmaker[AsyncSession], label: dict[str, Any], problem: str
) -> None:
    await add_files(session_factory)
    embedder = AxisEmbedder()

    with pytest.raises(EvaluationError, match=re.escape(problem)):
        await evaluate_dataset(
            dataset(evidence("best.py"), label),
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
            dataset(evidence("a.py")),
            Retriever(session_factory, AxisEmbedder()),
            session_factory,
            top_k=5,
        )
