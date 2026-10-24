import pytest

from uaw.evaluation.compare import compare
from uaw.evaluation.metrics import QuestionRun, Span, evaluate
from uaw.evaluation.runner import EvaluationRun

EVIDENCE = {
    "q1": [Span(path="a.py", start_line=1, end_line=5)],
    "q2": [Span(path="b.py", start_line=1, end_line=5)],
}


def run_with(rankings: dict[str, list[str]], sha: str = "a" * 40) -> EvaluationRun:
    runs = [
        QuestionRun(
            question_id,
            "paraphrase" if question_id == "q2" else "lookup",
            "dev",
            EVIDENCE[question_id],
            [Span(path=path, start_line=1, end_line=5) for path in paths],
            [0.5] * len(paths),
        )
        for question_id, paths in rankings.items()
    ]
    return EvaluationRun(
        repository="octo/demo",
        commit_sha=sha,
        top_k=5,
        split=None,
        report=evaluate(runs, ks=[1, 5]),
    )


def test_comparison_shows_gains_losses_and_moved_questions() -> None:
    before = run_with({"q1": ["a.py", "x.py"], "q2": ["x.py", "y.py"]})
    after = run_with({"q1": ["x.py", "a.py"], "q2": ["b.py"]}, sha="b" * 40)

    text = compare(before, after)

    assert "octo/demo: aaaaaaaaaaaa -> bbbbbbbbbbbb" in text
    # q1 drops from rank 1 to 2, q2 goes from missed to rank 1: hit@1 stays 0.50.
    assert "hit@1 0.50 -> 0.50 (+0.00)" in text
    assert "MRR 0.50 -> 0.75 (+0.25)" in text
    assert "paraphrase" in text
    assert "- q1: 1 -> 2" in text
    assert "+ q2: missed -> 1" in text


def test_identical_runs_report_no_movement() -> None:
    run = run_with({"q1": ["a.py"], "q2": ["b.py"]})

    assert "No question's first relevant chunk moved." in compare(run, run)


def test_reports_on_different_questions_are_refused() -> None:
    before = run_with({"q1": ["a.py"], "q2": ["b.py"]})
    after = run_with({"q1": ["a.py"]})

    with pytest.raises(ValueError, match="different questions"):
        compare(before, after)
