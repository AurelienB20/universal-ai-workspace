"""Labeled questions used to measure retrieval quality on one repository."""

import re
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from uaw.connectors.github.url import GitHubRepoRef, parse_github_full_name
from uaw.evaluation.metrics import Span

# What makes a question hard, to see where retrieval fails rather than one average:
# - lookup: asked with the code's own words;
# - paraphrase: none of the code's words;
# - identifier: an exact name (class, function, setting), where full-text search shines;
# - multi-file: the answer needs several files;
# - cross-lingual: asked in another language than the code and its docs;
# - unanswerable: the answer is not in the repository (no evidence).
Category = Literal[
    "lookup", "paraphrase", "identifier", "multi-file", "cross-lingual", "unanswerable"
]
# "dev" questions may be looked at while tuning retrieval; "test" ones only to report,
# so that tuning cannot fit the very questions it is judged on.
Split = Literal["dev", "test"]


class Evidence(Span):
    """A span holding (part of) the answer: a whole file, or one line range of it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def _valid_lines(self) -> Self:
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("Give both start_line and end_line, or neither")
        if (
            self.start_line is not None
            and self.end_line is not None
            and not 1 <= self.start_line <= self.end_line
        ):
            raise ValueError("Lines are 1-based and start_line <= end_line")
        return self


class EvalQuestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    question: str = Field(min_length=1)
    category: Category = "lookup"
    split: Split = "dev"
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_relevant_paths(cls, data: object) -> object:
        # Version 1 labeled files only: {"relevant_paths": ["a.py"]}.
        if isinstance(data, dict) and "relevant_paths" in data:
            data = dict(data)
            if "evidence" in data:
                raise ValueError("Give evidence or relevant_paths, not both")
            data["evidence"] = [{"path": path} for path in data.pop("relevant_paths")]
        return data

    @model_validator(mode="after")
    def _evidence_matches_category(self) -> Self:
        if self.category == "unanswerable" and self.evidence:
            raise ValueError(f"{self.id}: an unanswerable question has no evidence")
        if self.category != "unanswerable" and not self.evidence:
            raise ValueError(f"{self.id}: give the evidence, or use the unanswerable category")
        if self.category == "multi-file" and len({span.path for span in self.evidence}) < 2:
            raise ValueError(f"{self.id}: a multi-file question needs evidence in 2+ files")
        return self


class EvalDataset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str
    # Commit the labels were written against. Results on another commit are only
    # comparable if the labeled lines did not move.
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
        return {span.path for question in self.questions for span in question.evidence}

    def select(self, split: Split | None) -> list[EvalQuestion]:
        """The questions of one split, or all of them."""
        return [q for q in self.questions if split is None or q.split == split]


def load_dataset(path: Path) -> EvalDataset:
    return EvalDataset.model_validate_json(path.read_bytes())
