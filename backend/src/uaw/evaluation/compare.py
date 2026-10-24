"""Compare two evaluation reports (written with --json): what a change gained or lost.

Usage (from backend/):
    uv run python -m uaw.evaluation.compare eval/results/baseline-flask.json new.json

Shows the line-level metrics side by side, overall and per category, then the questions
whose first relevant chunk moved. Both reports must cover the same questions.
"""

import argparse
import sys
from pathlib import Path

from uaw.evaluation.metrics import Scores
from uaw.evaluation.runner import EvaluationRun


def load_run(path: Path) -> EvaluationRun:
    return EvaluationRun.model_validate_json(path.read_bytes())


def _row(label: str, before: Scores, after: Scores, k: int) -> str:
    def cell(old: float, new: float) -> str:
        return f"{old:.2f} -> {new:.2f} ({new - old:+.2f})"

    return (
        f"{label:<20} "
        f"hit@1 {cell(before.hit_rate[1], after.hit_rate[1])}   "
        f"rec@{k} {cell(before.recall[k], after.recall[k])}   "
        f"MRR {cell(before.mrr, after.mrr)}"
    )


def _rank(rank: int | None) -> str:
    return "missed" if rank is None else str(rank)


def compare(before: EvaluationRun, after: EvaluationRun) -> str:
    """A text report of the differences between two runs on the same questions."""
    old_ids = {o.question_id for o in before.report.outcomes}
    new_ids = {o.question_id for o in after.report.outcomes}
    if old_ids != new_ids:
        raise ValueError(
            "The reports cover different questions: "
            f"only before {sorted(old_ids - new_ids)}, only after {sorted(new_ids - old_ids)}"
        )
    ks = sorted(
        set(before.report.overall["lines"].recall) & set(after.report.overall["lines"].recall)
    )
    k = 5 if 5 in ks else ks[-1]

    old_report, new_report = before.report, after.report
    lines = [
        f"{before.repository}: {before.commit_sha[:12]} -> {after.commit_sha[:12]}",
        "",
        _row("all (lines)", old_report.overall["lines"], new_report.overall["lines"], k),
        _row("all (files)", old_report.overall["files"], new_report.overall["files"], k),
        "",
    ]
    for category, scores in new_report.by_category.items():
        previous = old_report.by_category.get(category)
        if previous is not None:
            lines.append(_row(category, previous["lines"], scores["lines"], k))

    old_ranks = {o.question_id: o.first_relevant_rank["lines"] for o in old_report.outcomes}
    moved: list[tuple[str, int | None, int | None]] = []
    for outcome in new_report.outcomes:
        old_rank, new_rank = old_ranks[outcome.question_id], outcome.first_relevant_rank["lines"]
        if outcome.answerable and old_rank != new_rank:
            moved.append((outcome.question_id, old_rank, new_rank))
    if moved:
        lines += ["", "First relevant chunk (lines) moved:"]
        for question_id, old_rank, new_rank in moved:
            better = new_rank is not None and (old_rank is None or new_rank < old_rank)
            sign = "+" if better else "-"
            lines.append(f"  {sign} {question_id}: {_rank(old_rank)} -> {_rank(new_rank)}")
    else:
        lines += ["", "No question's first relevant chunk moved."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m uaw.evaluation.compare", description="Compare two evaluation reports."
    )
    parser.add_argument("before", type=Path, help="reference report (JSON)")
    parser.add_argument("after", type=Path, help="report to compare with it (JSON)")
    args = parser.parse_args(argv)
    try:
        print(compare(load_run(args.before), load_run(args.after)))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
