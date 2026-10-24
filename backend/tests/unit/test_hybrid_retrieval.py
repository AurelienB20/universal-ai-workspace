import uuid

import pytest

from uaw.retrieval.retriever import RetrievalOptions, fuse, is_test_path, ranked
from uaw.storage.fulltext import text_query, text_query_terms

A, B, C, D = (uuid.UUID(int=i) for i in range(1, 5))


def test_question_terms_keep_code_words_and_joined_names() -> None:
    terms = text_query_terms("What does PROPAGATE_EXCEPTIONS change?")

    assert terms == ["propagateexceptions", "propagate", "exceptions", "change"]


def test_stop_words_are_dropped_but_names_survive_whole() -> None:
    # "this" alone is a stop word; inside a name it is kept through the joined form.
    assert text_query_terms("How does after_this_request work?") == [
        "afterthisrequest",
        "after",
        "request",
        "work",
    ]
    assert text_query_terms("Comment tester une application ?") == ["tester", "application"]


def test_query_syntax_cannot_be_injected() -> None:
    # Only letters and digits reach to_tsquery.
    assert text_query("foo' | !bar & (baz) <-> qux:*") == "foo | bar | baz | qux"
    assert text_query("what is it?") is None
    assert text_query("") is None


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_basic.py", True),
        ("src/pkg/tests/helpers.py", True),
        ("src/test_utils.py", True),
        ("pkg/client_test.py", True),
        ("src/flask/testing.py", False),
        ("docs/testing.rst", False),
        ("src/contest.py", False),
    ],
)
def test_test_files_are_recognised(path: str, expected: bool) -> None:
    assert is_test_path(path) is expected


def test_rrf_adds_each_ranking_contribution() -> None:
    scores = fuse([([A, B, C], 1.0), ([C, D], 1.0)], k=60)

    assert scores[A] == pytest.approx(1 / 61)
    assert scores[C] == pytest.approx(1 / 63 + 1 / 61)  # found by both: ranked first
    assert max(scores, key=scores.__getitem__) == C


def test_a_ranking_weight_scales_its_contribution() -> None:
    scores = fuse([([A], 1.0), ([B], 0.5)], k=60)

    assert scores[B] == pytest.approx(0.5 / 61)
    assert fuse([([A], 1.0), ([B], 0.0)], k=60)[B] == 0.0


def test_test_files_can_be_ranked_lower() -> None:
    scores = {A: 0.04, B: 0.03}
    paths = {A: "tests/test_app.py", B: "src/app.py"}

    assert ranked(scores, paths.__getitem__, test_weight=1.0, limit=2) == [A, B]
    assert ranked(scores, paths.__getitem__, test_weight=0.5, limit=2) == [B, A]
    assert ranked(scores, paths.__getitem__, test_weight=0.5, limit=1) == [B]


def test_default_options_keep_the_plain_vector_ranking() -> None:
    assert not RetrievalOptions().reorders
    assert RetrievalOptions(mode="hybrid").reorders
    assert RetrievalOptions(test_weight=0.5).reorders


@pytest.mark.parametrize(
    "kwargs", [{"candidates": 0}, {"candidates": 101}, {"text_weight": -1}, {"test_weight": 0}]
)
def test_invalid_options_are_refused(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        RetrievalOptions(**kwargs)  # type: ignore[arg-type]
