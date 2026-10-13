"""Retrieval metrics, computed at file level.

A question is labeled with the files that contain its answer. The search returns
chunks; a chunk counts as relevant when its file is one of the labeled files.
"""

from collections.abc import Collection, Sequence

from pydantic import BaseModel, ConfigDict


def first_relevant_rank(ranked_paths: Sequence[str], relevant: Collection[str]) -> int | None:
    """1-based rank of the first chunk from a relevant file, or None if there is none."""
    for rank, path in enumerate(ranked_paths, start=1):
        if path in relevant:
            return rank
    return None


def recall_at_k(ranked_paths: Sequence[str], relevant: Collection[str], k: int) -> float:
    """Share of the relevant files that appear in the first ``k`` chunks."""
    if not relevant:
        raise ValueError("A question needs at least one relevant file")
    found = set(ranked_paths[:k]) & set(relevant)
    return len(found) / len(set(relevant))


def hit_at_k(ranked_paths: Sequence[str], relevant: Collection[str], k: int) -> bool:
    """Whether at least one relevant file appears in the first ``k`` chunks."""
    rank = first_relevant_rank(ranked_paths, relevant)
    return rank is not None and rank <= k


def reciprocal_rank(ranked_paths: Sequence[str], relevant: Collection[str]) -> float:
    """1 / rank of the first relevant chunk (1.0 if first, 0.5 if second...), 0 if absent."""
    rank = first_relevant_rank(ranked_paths, relevant)
    return 0.0 if rank is None else 1.0 / rank


class QuestionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    first_relevant_rank: int | None
    recall: dict[int, float]


class RetrievalReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    questions: int
    # Averages over all questions, keyed by k.
    hit_rate: dict[int, float]
    recall: dict[int, float]
    # Mean reciprocal rank within the retrieved chunks.
    mrr: float
    outcomes: list[QuestionOutcome]


def evaluate(
    runs: Sequence[tuple[str, Sequence[str], Collection[str]]], ks: Sequence[int]
) -> RetrievalReport:
    """Aggregate metrics over ``(question_id, ranked_paths, relevant_paths)`` runs."""
    if not runs:
        raise ValueError("Nothing to evaluate")
    outcomes = [
        QuestionOutcome(
            question_id=question_id,
            first_relevant_rank=first_relevant_rank(ranked, relevant),
            recall={k: recall_at_k(ranked, relevant, k) for k in ks},
        )
        for question_id, ranked, relevant in runs
    ]
    count = len(runs)
    return RetrievalReport(
        questions=count,
        hit_rate={k: sum(hit_at_k(r, rel, k) for _, r, rel in runs) / count for k in ks},
        recall={k: sum(o.recall[k] for o in outcomes) / count for k in ks},
        mrr=sum(reciprocal_rank(r, rel) for _, r, rel in runs) / count,
        outcomes=outcomes,
    )
