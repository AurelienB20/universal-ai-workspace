"""Labeled questions used to measure retrieval quality on one repository."""

import re
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from uaw.connectors.github.url import GitHubRepoRef, parse_github_full_name


class EvalQuestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    question: str = Field(min_length=1)
    # Every file that contains (part of) the answer, as indexed (POSIX paths).
    relevant_paths: list[str] = Field(min_length=1)


class EvalDataset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str
    # Commit the labels were written against. Results on another commit are only
    # comparable if the labeled files did not move.
    commit_sha: str
    description: str = ""
    questions: list[EvalQuestion] = Field(min_length=1)

    @field_validator("repository")
    @classmethod
    def _valid_repository(cls, value: str) -> str:
        parse_github_full_name(value)
        return value

    @field_validator("commit_sha")
    @classmethod
    def _full_sha(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("commit_sha must be a full 40-character lowercase SHA")
        return value

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [question.id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("Question ids must be unique")
        return self

    @property
    def ref(self) -> GitHubRepoRef:
        return parse_github_full_name(self.repository)

    def labeled_paths(self) -> set[str]:
        return {path for question in self.questions for path in question.relevant_paths}


def load_dataset(path: Path) -> EvalDataset:
    return EvalDataset.model_validate_json(path.read_bytes())
