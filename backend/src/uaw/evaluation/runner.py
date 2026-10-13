"""Run a labeled question set against the retriever and report the metrics."""

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uaw.evaluation.dataset import EvalDataset
from uaw.evaluation.metrics import RetrievalReport, evaluate
from uaw.retrieval.retriever import RetrievalError, Retriever
from uaw.storage.search import ChunkSearch

REPORTED_KS = (1, 3, 5, 10)


class EvaluationError(Exception):
    """The evaluation cannot run. The message tells the user what to do."""


class EvaluationRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: str
    # Commit actually evaluated (the latest indexed one).
    commit_sha: str
    top_k: int
    report: RetrievalReport


async def evaluate_dataset(
    dataset: EvalDataset,
    retriever: Retriever,
    sessions: async_sessionmaker[AsyncSession],
    *,
    top_k: int,
) -> EvaluationRun:
    try:
        snapshot = await retriever.find_snapshot(dataset.ref)
    except RetrievalError as exc:
        raise EvaluationError(
            f"{exc} Import https://github.com/{dataset.repository} first."
        ) from exc

    # A label pointing to a file that is not indexed would silently count as a miss:
    # refuse to run instead.
    async with sessions() as session:
        indexed = await ChunkSearch(session).document_paths(snapshot.id)
    missing = sorted(dataset.labeled_paths() - indexed)
    if missing:
        raise EvaluationError(
            f"These labeled files are not in the indexed snapshot ({snapshot.commit_sha}): "
            + ", ".join(missing)
        )

    runs = []
    for question in dataset.questions:
        result = await retriever.search(dataset.ref, question.question, top_k=top_k)
        runs.append((question.id, [hit.path for hit in result.hits], question.relevant_paths))
    return EvaluationRun(
        repository=snapshot.repository,
        commit_sha=snapshot.commit_sha,
        top_k=top_k,
        report=evaluate(runs, [k for k in REPORTED_KS if k <= top_k]),
    )


def format_run(dataset: EvalDataset, run: EvaluationRun) -> str:
    report = run.report
    lines = [f"Repository: {run.repository} @ {run.commit_sha[:12]}"]
    if run.commit_sha != dataset.commit_sha:
        lines.append(
            f"Warning: labels were written for commit {dataset.commit_sha[:12]}; "
            "results are comparable only if the labeled files did not change."
        )
    lines += [f"Questions: {report.questions}", "", f"{'k':>4}  {'hit@k':>6}  {'recall@k':>8}"]
    lines += [
        f"{k:>4}  {report.hit_rate[k]:>6.2f}  {report.recall[k]:>8.2f}" for k in report.hit_rate
    ]
    lines.append(f"MRR@{run.top_k}: {report.mrr:.3f}")

    questions = {question.id: question.question for question in dataset.questions}
    imperfect = [o for o in report.outcomes if o.first_relevant_rank != 1]
    if imperfect:
        lines += ["", "Questions whose first hit is not relevant:"]
        for outcome in imperfect:
            rank = outcome.first_relevant_rank
            where = f"first relevant at rank {rank}" if rank else f"missed in top {run.top_k}"
            lines.append(f"  - {outcome.question_id} ({where}): {questions[outcome.question_id]}")
    return "\n".join(lines)
