"""Retrieval metrics, at two levels.

A question is labeled with its evidence: the spans (a file, optionally a line range)
that contain the answer. The search returns ranked chunks, each a line range.

- **files**: a chunk counts as relevant when its file holds some evidence. Lenient: any
  chunk of a large relevant file counts.
- **lines**: a chunk counts as relevant when it overlaps an evidence line range (or
  comes from an evidence file labeled without lines). This is what a citation needs.

Questions without evidence (the answer is not in the repository) are kept out of the
scores; their best similarity is reported, to study a "no answer" threshold later.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

Level = Literal["files", "lines"]
LEVELS: tuple[Level, ...] = ("files", "lines")


class Span(BaseModel):
    """A file, or lines ``start_line``..``end_line`` of it (1-based, inclusive)."""

    model_config = ConfigDict(frozen=True)

    path: str
    start_line: int | None = None
    end_line: int | None = None

    def covers(self, chunk: "Span") -> bool:
        """Whether ``chunk`` (a retrieved line range) holds part of this evidence."""
        if chunk.path != self.path:
            return False
        if self.start_line is None or self.end_line is None:
            return True  # labeled at file level
        if chunk.start_line is None or chunk.end_line is None:
            return True
        return chunk.start_line <= self.end_line and self.start_line <= chunk.end_line

    def as_file(self) -> "Span":
        return Span(path=self.path)


def at_level(evidence: Sequence[Span], level: Level) -> list[Span]:
    """The evidence as seen at ``level``: one span per file at file level."""
    if level == "lines":
        return list(evidence)
    return list(dict.fromkeys(span.as_file() for span in evidence))


def first_relevant_rank(ranked: Sequence[Span], evidence: Sequence[Span]) -> int | None:
    """1-based rank of the first chunk covered by some evidence, or None."""
    for rank, chunk in enumerate(ranked, start=1):
        if any(span.covers(chunk) for span in evidence):
            return rank
    return None


def recall_at_k(ranked: Sequence[Span], evidence: Sequence[Span], k: int) -> float:
    """Share of the evidence spans covered by at least one of the first ``k`` chunks."""
    if not evidence:
        raise ValueError("A question needs evidence to compute recall")
    top = ranked[:k]
    found = sum(any(span.covers(chunk) for chunk in top) for span in evidence)
    return found / len(evidence)


def hit_at_k(ranked: Sequence[Span], evidence: Sequence[Span], k: int) -> bool:
    rank = first_relevant_rank(ranked, evidence)
    return rank is not None and rank <= k


def reciprocal_rank(ranked: Sequence[Span], evidence: Sequence[Span]) -> float:
    """1 / rank of the first relevant chunk (1.0 if first, 0.5 if second...), 0 if absent."""
    rank = first_relevant_rank(ranked, evidence)
    return 0.0 if rank is None else 1.0 / rank


@dataclass(frozen=True)
class QuestionRun:
    """One question, its labels, and what the search returned for it."""

    question_id: str
    category: str
    split: str
    evidence: Sequence[Span]
    ranked: Sequence[Span]
    scores: Sequence[float]


class QuestionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    category: str
    split: str
    answerable: bool
    # None when the question has no evidence, or when nothing relevant was retrieved.
    first_relevant_rank: dict[Level, int | None]
    recall: dict[Level, dict[int, float]]
    # Similarity of the best chunk: for questions without an answer, how "sure" the
    # search looked anyway.
    top_score: float | None


class Scores(BaseModel):
    model_config = ConfigDict(frozen=True)

    questions: int
    hit_rate: dict[int, float]
    recall: dict[int, float]
    # Mean reciprocal rank within the retrieved chunks.
    mrr: float


class RetrievalReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Questions with evidence (scored), and without (reported apart).
    answerable: int
    unanswerable: int
    overall: dict[Level, Scores]
    by_category: dict[str, dict[Level, Scores]]
    outcomes: list[QuestionOutcome]


def _scores(runs: Sequence[QuestionRun], level: Level, ks: Sequence[int]) -> Scores:
    count = len(runs)
    evidence = {run.question_id: at_level(run.evidence, level) for run in runs}
    return Scores(
        questions=count,
        hit_rate={
            k: sum(hit_at_k(r.ranked, evidence[r.question_id], k) for r in runs) / count for k in ks
        },
        recall={
            k: sum(recall_at_k(r.ranked, evidence[r.question_id], k) for r in runs) / count
            for k in ks
        },
        mrr=sum(reciprocal_rank(r.ranked, evidence[r.question_id]) for r in runs) / count,
    )


def _outcome(run: QuestionRun, ks: Sequence[int]) -> QuestionOutcome:
    answerable = bool(run.evidence)
    ranks: dict[Level, int | None] = {}
    recall: dict[Level, dict[int, float]] = {}
    for level in LEVELS:
        evidence = at_level(run.evidence, level)
        ranks[level] = first_relevant_rank(run.ranked, evidence) if answerable else None
        recall[level] = {k: recall_at_k(run.ranked, evidence, k) for k in ks} if answerable else {}
    return QuestionOutcome(
        question_id=run.question_id,
        category=run.category,
        split=run.split,
        answerable=answerable,
        first_relevant_rank=ranks,
        recall=recall,
        top_score=max(run.scores, default=None),
    )


def evaluate(runs: Sequence[QuestionRun], ks: Sequence[int]) -> RetrievalReport:
    """Aggregate the metrics over the runs, overall and per category, at both levels."""
    scored = [run for run in runs if run.evidence]
    if not scored:
        raise ValueError("Nothing to evaluate: no question has evidence")
    by_category: dict[str, list[QuestionRun]] = defaultdict(list)
    for run in scored:
        by_category[run.category].append(run)
    return RetrievalReport(
        answerable=len(scored),
        unanswerable=len(runs) - len(scored),
        overall={level: _scores(scored, level, ks) for level in LEVELS},
        by_category={
            category: {level: _scores(group, level, ks) for level in LEVELS}
            for category, group in sorted(by_category.items())
        },
        outcomes=[_outcome(run, ks) for run in runs],
    )
