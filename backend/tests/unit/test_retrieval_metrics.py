import pytest

from uaw.evaluation.metrics import (
    evaluate,
    first_relevant_rank,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
)

# Several chunks can come from the same file: ranks are chunk ranks.
RANKED = ["a.py", "a.py", "b.py", "c.md", "d.py"]


def test_first_relevant_rank_is_one_based() -> None:
    assert first_relevant_rank(RANKED, {"b.py"}) == 3
    assert first_relevant_rank(RANKED, {"zzz.py"}) is None


def test_recall_counts_distinct_relevant_files() -> None:
    assert recall_at_k(RANKED, {"a.py", "c.md"}, k=2) == 0.5
    assert recall_at_k(RANKED, {"a.py", "c.md"}, k=4) == 1.0
    assert recall_at_k(RANKED, {"a.py", "missing.py"}, k=10) == 0.5


def test_recall_needs_labels() -> None:
    with pytest.raises(ValueError):
        recall_at_k(RANKED, set(), k=3)


def test_hit_and_reciprocal_rank() -> None:
    assert hit_at_k(RANKED, {"c.md"}, k=4)
    assert not hit_at_k(RANKED, {"c.md"}, k=3)
    assert reciprocal_rank(RANKED, {"a.py"}) == 1.0
    assert reciprocal_rank(RANKED, {"c.md"}) == 0.25
    assert reciprocal_rank(RANKED, {"zzz.py"}) == 0.0


def test_evaluate_averages_over_questions() -> None:
    report = evaluate(
        [
            ("q1", ["x.py", "y.py"], {"x.py"}),  # first
            ("q2", ["x.py", "y.py"], {"y.py"}),  # second
            ("q3", ["x.py", "y.py"], {"z.py"}),  # missed
        ],
        ks=[1, 2],
    )

    assert report.questions == 3
    assert report.hit_rate == {1: pytest.approx(1 / 3), 2: pytest.approx(2 / 3)}
    assert report.recall == {1: pytest.approx(1 / 3), 2: pytest.approx(2 / 3)}
    assert report.mrr == pytest.approx((1 + 0.5 + 0) / 3)
    assert [o.first_relevant_rank for o in report.outcomes] == [1, 2, None]


def test_evaluate_needs_runs() -> None:
    with pytest.raises(ValueError):
        evaluate([], ks=[1])
