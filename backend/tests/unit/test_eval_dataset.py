from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from uaw.evaluation.dataset import EvalDataset, load_dataset

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


@pytest.mark.parametrize("path", sorted(EVAL_DIR.glob("*.json")), ids=lambda p: p.name)
def test_shipped_datasets_are_valid(path: Path) -> None:
    dataset = load_dataset(path)

    assert dataset.questions
    # Labels are POSIX paths relative to the repository root, as indexed.
    assert all(
        not p.startswith("/") and "\\" not in p and ".." not in p.split("/")
        for p in dataset.labeled_paths()
    )


def dataset(**overrides: Any) -> dict[str, Any]:
    return {
        "repository": "pallets/itsdangerous",
        "commit_sha": "a" * 40,
        "questions": [{"id": "q1", "question": "Where?", "relevant_paths": ["a.py"]}],
    } | overrides


def test_minimal_dataset_is_valid() -> None:
    assert EvalDataset.model_validate(dataset()).ref.full_name == "pallets/itsdangerous"


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository": "https://github.com/pallets/itsdangerous"},
        {"commit_sha": "main"},
        {"questions": []},
        {"questions": [{"id": "q1", "question": "Where?", "relevant_paths": []}]},
        {
            "questions": [
                {"id": "q1", "question": "A?", "relevant_paths": ["a.py"]},
                {"id": "q1", "question": "B?", "relevant_paths": ["b.py"]},
            ]
        },
        {"unexpected": True},
        # Evidence lines: both or neither, 1-based, in order.
        {
            "questions": [
                {"id": "q1", "question": "A?", "evidence": [{"path": "a.py", "start_line": 3}]}
            ]
        },
        {
            "questions": [
                {
                    "id": "q1",
                    "question": "A?",
                    "evidence": [{"path": "a.py", "start_line": 0, "end_line": 2}],
                }
            ]
        },
        {
            "questions": [
                {
                    "id": "q1",
                    "question": "A?",
                    "evidence": [{"path": "a.py", "start_line": 5, "end_line": 4}],
                }
            ]
        },
        # Categories must match the evidence.
        {
            "questions": [
                {
                    "id": "q1",
                    "question": "A?",
                    "category": "unanswerable",
                    "relevant_paths": ["a.py"],
                }
            ]
        },
        {
            "questions": [
                {
                    "id": "q1",
                    "question": "A?",
                    "category": "multi-file",
                    "evidence": [
                        {"path": "a.py"},
                        {"path": "a.py", "start_line": 1, "end_line": 2},
                    ],
                }
            ]
        },
        {
            "questions": [
                {"id": "q1", "question": "A?", "category": "guess", "relevant_paths": ["a.py"]}
            ]
        },
        {
            "questions": [
                {"id": "q1", "question": "A?", "split": "train", "relevant_paths": ["a.py"]}
            ]
        },
        {
            "questions": [
                {
                    "id": "q1",
                    "question": "A?",
                    "relevant_paths": ["a.py"],
                    "evidence": [{"path": "a.py"}],
                }
            ]
        },
    ],
)
def test_invalid_datasets_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EvalDataset.model_validate(dataset(**overrides))


def test_version_1_labels_become_file_level_evidence() -> None:
    question = EvalDataset.model_validate(dataset()).questions[0]

    assert [(span.path, span.start_line) for span in question.evidence] == [("a.py", None)]
    assert (question.category, question.split) == ("lookup", "dev")


def test_questions_without_an_answer_and_splits() -> None:
    parsed = EvalDataset.model_validate(
        dataset(
            questions=[
                {
                    "id": "q1",
                    "question": "A?",
                    "evidence": [{"path": "a.py", "start_line": 1, "end_line": 4}],
                },
                {"id": "q2", "question": "B?", "category": "unanswerable", "split": "test"},
            ]
        )
    )

    assert [q.id for q in parsed.select("test")] == ["q2"]
    assert [q.id for q in parsed.select(None)] == ["q1", "q2"]
    assert parsed.labeled_paths() == {"a.py"}
