import pytest

from uaw.config import Settings
from uaw.evaluation.__main__ import run
from uaw.evaluation.dataset import EvalDataset
from uaw.evaluation.metrics import QuestionRun, Span, evaluate
from uaw.evaluation.runner import EvaluationError, EvaluationRun, check_labels, format_run

DATASET = EvalDataset.model_validate(
    {
        "repository": "octo/demo",
        "commit_sha": "a" * 40,
        "questions": [
            {
                "id": "q1",
                "question": "Where is auth?",
                "evidence": [{"path": "auth.py", "start_line": 3, "end_line": 8}],
            },
            {
                "id": "q2",
                "question": "Where is the CLI?",
                "category": "paraphrase",
                "evidence": [{"path": "cli.py"}],
            },
            {"id": "q3", "question": "Is there a GUI?", "category": "unanswerable"},
        ],
    }
)


def evaluation_run(commit_sha: str) -> EvaluationRun:
    hits = [Span(path="auth.py", start_line=1, end_line=10), Span(path="x.py")]
    runs = [
        QuestionRun("q1", "lookup", "dev", DATASET.questions[0].evidence, hits, [0.8, 0.5]),
        QuestionRun("q2", "paraphrase", "dev", DATASET.questions[1].evidence, hits, [0.7, 0.6]),
        QuestionRun("q3", "unanswerable", "dev", [], hits, [0.42, 0.3]),
    ]
    report = evaluate(runs, ks=[1])
    return EvaluationRun(
        repository="octo/demo", commit_sha=commit_sha, top_k=2, split=None, report=report
    )


def test_report_shows_both_levels_categories_and_misses() -> None:
    text = format_run(DATASET, evaluation_run("a" * 40))

    assert "Questions: 2 scored, 1 without an answer (split: all, top 2)" in text
    assert "all, files" in text and "all, lines" in text
    assert "paraphrase (1)" in text
    assert "q2 [paraphrase] (missed in top 2): Where is the CLI?" in text
    assert "q3: 0.420" in text
    assert "Warning" not in text


def test_report_warns_when_the_commit_differs_from_the_labels() -> None:
    assert "Warning: labels were written for commit aaaaaaaaaaaa" in format_run(
        DATASET, evaluation_run("b" * 40)
    )


def test_labels_are_checked_against_the_indexed_files() -> None:
    problems = check_labels(DATASET.questions, {"auth.py": 5})

    assert problems == [
        "q1: auth.py has 5 lines, label ends at 8",
        "q2: cli.py is not indexed",
    ]
    assert check_labels(DATASET.questions, {"auth.py": 8, "cli.py": 1}) == []


@pytest.mark.anyio
async def test_evaluation_needs_an_embedding_key() -> None:
    settings = Settings(_env_file=None, voyage_api_key=None)

    with pytest.raises(EvaluationError, match="VOYAGE_API_KEY"):
        await run(DATASET, settings, top_k=5)
