import pytest

from uaw.config import Settings
from uaw.evaluation.__main__ import run
from uaw.evaluation.dataset import EvalDataset
from uaw.evaluation.metrics import evaluate
from uaw.evaluation.runner import EvaluationError, EvaluationRun, format_run

DATASET = EvalDataset.model_validate(
    {
        "repository": "octo/demo",
        "commit_sha": "a" * 40,
        "questions": [
            {"id": "q1", "question": "Where is auth?", "relevant_paths": ["auth.py"]},
            {"id": "q2", "question": "Where is the CLI?", "relevant_paths": ["cli.py"]},
        ],
    }
)


def evaluation_run(commit_sha: str) -> EvaluationRun:
    report = evaluate(
        [("q1", ["auth.py", "x.py"], ["auth.py"]), ("q2", ["x.py", "y.py"], ["cli.py"])], ks=[1]
    )
    return EvaluationRun(repository="octo/demo", commit_sha=commit_sha, top_k=2, report=report)


def test_report_lists_imperfect_questions() -> None:
    text = format_run(DATASET, evaluation_run("a" * 40))

    assert "MRR@2: 0.500" in text
    assert "q2 (missed in top 2): Where is the CLI?" in text
    assert "q1" not in text.split("not relevant:")[1]
    assert "Warning" not in text


def test_report_warns_when_the_commit_differs_from_the_labels() -> None:
    assert "Warning: labels were written for commit aaaaaaaaaaaa" in format_run(
        DATASET, evaluation_run("b" * 40)
    )


@pytest.mark.anyio
async def test_evaluation_needs_an_embedding_key() -> None:
    settings = Settings(_env_file=None, voyage_api_key=None)

    with pytest.raises(EvaluationError, match="VOYAGE_API_KEY"):
        await run(DATASET, settings, top_k=5)
