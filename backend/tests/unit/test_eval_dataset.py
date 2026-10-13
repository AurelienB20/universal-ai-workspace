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
    ],
)
def test_invalid_datasets_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EvalDataset.model_validate(dataset(**overrides))
