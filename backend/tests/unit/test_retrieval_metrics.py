import pytest

from uaw.evaluation.metrics import (
    QuestionRun,
    Span,
    at_level,
    evaluate,
    first_relevant_rank,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
)


def chunk(path: str, start: int, end: int) -> Span:
    return Span(path=path, start_line=start, end_line=end)


def file(path: str) -> Span:
    return Span(path=path)


# Several chunks can come from the same file: ranks are chunk ranks.
RANKED = [chunk("a.py", 1, 40), chunk("a.py", 41, 80), chunk("b.py", 1, 30), chunk("c.md", 1, 9)]


def test_evidence_covers_overlapping_chunks_only() -> None:
    evidence = chunk("a.py", 50, 60)

    assert evidence.covers(chunk("a.py", 41, 80))
    assert evidence.covers(chunk("a.py", 60, 90))  # touching the last line counts
    assert not evidence.covers(chunk("a.py", 1, 40))
    assert not evidence.covers(chunk("b.py", 50, 60))
    assert file("a.py").covers(chunk("a.py", 1, 40))  # labeled without lines


def test_line_level_is_stricter_than_file_level() -> None:
    evidence = [chunk("a.py", 50, 60)]

    # The first chunk is from the right file, but not the answering lines.
    assert first_relevant_rank(RANKED, at_level(evidence, "files")) == 1
    assert first_relevant_rank(RANKED, at_level(evidence, "lines")) == 2


def test_file_level_keeps_one_span_per_file() -> None:
    evidence = [chunk("a.py", 1, 5), chunk("a.py", 70, 75), chunk("b.py", 3, 4)]

    assert at_level(evidence, "files") == [file("a.py"), file("b.py")]
    assert at_level(evidence, "lines") == evidence


def test_recall_counts_evidence_spans_covered() -> None:
    evidence = [chunk("a.py", 50, 60), chunk("c.md", 2, 3)]

    assert recall_at_k(RANKED, evidence, k=2) == 0.5
    assert recall_at_k(RANKED, evidence, k=4) == 1.0
    assert recall_at_k(RANKED, [chunk("zzz.py", 1, 1), chunk("b.py", 9, 9)], k=10) == 0.5


def test_recall_needs_evidence() -> None:
    with pytest.raises(ValueError):
        recall_at_k(RANKED, [], k=3)


def test_hit_and_reciprocal_rank() -> None:
    assert hit_at_k(RANKED, [file("c.md")], k=4)
    assert not hit_at_k(RANKED, [file("c.md")], k=3)
    assert reciprocal_rank(RANKED, [file("a.py")]) == 1.0
    assert reciprocal_rank(RANKED, [file("c.md")]) == 0.25
    assert reciprocal_rank(RANKED, [file("zzz.py")]) == 0.0


def run(question_id: str, category: str, evidence: list[Span], ranked: list[Span]) -> QuestionRun:
    scores = [0.9 - 0.1 * i for i in range(len(ranked))]
    return QuestionRun(question_id, category, "dev", evidence, ranked, scores)


def test_evaluate_scores_both_levels_and_each_category() -> None:
    ranked = [chunk("x.py", 1, 10), chunk("x.py", 11, 20)]
    report = evaluate(
        [
            run("q1", "lookup", [chunk("x.py", 2, 3)], ranked),  # lines: first
            run("q2", "lookup", [chunk("x.py", 15, 15)], ranked),  # lines: second
            run("q3", "paraphrase", [chunk("y.py", 1, 1)], ranked),  # missed
            run("q4", "unanswerable", [], ranked),
        ],
        ks=[1, 2],
    )

    assert (report.answerable, report.unanswerable) == (3, 1)
    lines, files = report.overall["lines"], report.overall["files"]
    assert lines.hit_rate == {1: pytest.approx(1 / 3), 2: pytest.approx(2 / 3)}
    assert lines.mrr == pytest.approx((1 + 0.5 + 0) / 3)
    # At file level, q2's first chunk already counts.
    assert files.hit_rate[1] == pytest.approx(2 / 3)
    assert report.by_category["lookup"]["lines"].mrr == pytest.approx(0.75)
    assert report.by_category["paraphrase"]["lines"].questions == 1
    assert "unanswerable" not in report.by_category
    unanswerable = report.outcomes[3]
    assert not unanswerable.answerable
    assert unanswerable.top_score == pytest.approx(0.9)
    assert unanswerable.first_relevant_rank == {"files": None, "lines": None}


def test_evaluate_needs_a_question_with_evidence() -> None:
    with pytest.raises(ValueError):
        evaluate([], ks=[1])
    with pytest.raises(ValueError):
        evaluate([run("q1", "unanswerable", [], [])], ks=[1])
