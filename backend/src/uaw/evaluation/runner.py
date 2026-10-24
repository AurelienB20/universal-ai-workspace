"""Run a labeled question set against the retriever and report the metrics."""

from dataclasses import asdict

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uaw.evaluation.dataset import EvalDataset, EvalQuestion, Split
from uaw.evaluation.metrics import LEVELS, QuestionRun, RetrievalReport, Scores, Span, evaluate
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
    # None: every question.
    split: Split | None
    # How retrieval was configured (absent from reports made before hybrid search).
    retrieval: dict[str, object] | None = None
    report: RetrievalReport


def check_labels(questions: list[EvalQuestion], line_counts: dict[str, int]) -> list[str]:
    """Problems with the labels: files not indexed, lines past the end of a file.

    A wrong label would silently count as a retrieval miss, so the run refuses them."""
    problems = []
    for question in questions:
        for span in question.evidence:
            lines = line_counts.get(span.path)
            if lines is None:
                problems.append(f"{question.id}: {span.path} is not indexed")
            elif span.end_line is not None and span.end_line > lines:
                problems.append(
                    f"{question.id}: {span.path} has {lines} lines, label ends at {span.end_line}"
                )
    return problems


async def evaluate_dataset(
    dataset: EvalDataset,
    retriever: Retriever,
    sessions: async_sessionmaker[AsyncSession],
    *,
    top_k: int,
    split: Split | None = None,
) -> EvaluationRun:
    try:
        snapshot = await retriever.find_snapshot(dataset.ref)
    except RetrievalError as exc:
        raise EvaluationError(
            f"{exc} Import https://github.com/{dataset.repository} first."
        ) from exc

    questions = dataset.select(split)
    if not questions:
        raise EvaluationError(f"No question in the {split} split.")
    async with sessions() as session:
        line_counts = await ChunkSearch(session).document_line_counts(snapshot.id)
    problems = check_labels(questions, line_counts)
    if problems:
        raise EvaluationError(
            f"Some labels do not match the indexed snapshot ({snapshot.commit_sha}):\n  "
            + "\n  ".join(problems)
        )

    runs = []
    for question in questions:
        result = await retriever.search(dataset.ref, question.question, top_k=top_k)
        runs.append(
            QuestionRun(
                question_id=question.id,
                category=question.category,
                split=question.split,
                evidence=question.evidence,
                ranked=[
                    Span(path=hit.path, start_line=hit.start_line, end_line=hit.end_line)
                    for hit in result.hits
                ],
                scores=[hit.score for hit in result.hits],
            )
        )
    return EvaluationRun(
        repository=snapshot.repository,
        commit_sha=snapshot.commit_sha,
        top_k=top_k,
        split=split,
        retrieval=asdict(retriever.options),
        report=evaluate(runs, [k for k in REPORTED_KS if k <= top_k]),
    )


def _row(label: str, scores: Scores, ks: list[int]) -> str:
    cells = [f"{scores.hit_rate[k]:>6.2f}" for k in ks] + [f"{scores.recall[k]:>6.2f}" for k in ks]
    return f"{label:<22}" + "".join(f"  {cell}" for cell in cells) + f"  {scores.mrr:>6.3f}"


def format_run(dataset: EvalDataset, run: EvaluationRun) -> str:
    report = run.report
    ks = sorted(report.overall["lines"].hit_rate)
    lines = [f"Repository: {run.repository} @ {run.commit_sha[:12]}"]
    if run.commit_sha != dataset.commit_sha:
        lines.append(
            f"Warning: labels were written for commit {dataset.commit_sha[:12]}; "
            "results are comparable only if the labeled lines did not change."
        )
    lines.append(
        f"Questions: {report.answerable} scored, {report.unanswerable} without an answer"
        f" (split: {run.split or 'all'}, top {run.top_k})"
    )
    header = (
        f"{'':<22}"
        + "".join(f"  {f'hit@{k}':>6}" for k in ks)
        + "".join(f"  {f'rec@{k}':>6}" for k in ks)
        + f"  {'MRR':>6}"
    )
    lines += ["", header]
    lines += [_row(f"all, {level}", report.overall[level], ks) for level in LEVELS]
    lines += ["", "By category (lines):"]
    lines += [
        _row(f"  {category} ({scores['lines'].questions})", scores["lines"], ks)
        for category, scores in report.by_category.items()
    ]

    questions = {question.id: question.question for question in dataset.questions}
    imperfect = [o for o in report.outcomes if o.answerable and o.first_relevant_rank["lines"] != 1]
    if imperfect:
        lines += ["", "Questions whose first chunk is not evidence (lines):"]
        for outcome in imperfect:
            rank = outcome.first_relevant_rank["lines"]
            where = f"first evidence at rank {rank}" if rank else f"missed in top {run.top_k}"
            lines.append(
                f"  - {outcome.question_id} [{outcome.category}] ({where}): "
                f"{questions[outcome.question_id]}"
            )
    unanswerable = [o for o in report.outcomes if not o.answerable]
    if unanswerable:
        lines += ["", "Questions without an answer (best similarity found anyway):"]
        lines += [
            f"  - {o.question_id}: {o.top_score:.3f}"
            if o.top_score is not None
            else f"  - {o.question_id}: nothing retrieved"
            for o in unanswerable
        ]
    return "\n".join(lines)
