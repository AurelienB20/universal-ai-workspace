"""The answer text is read out of JSON fragments cut anywhere."""

import json
import random

import pytest

from uaw.generation.json_stream import REPLACEMENT, AnswerTextExtractor

ANSWERS = [
    "Signed with HMAC [S1].",
    "",
    'Quotes " and backslashes \\ and a slash /',
    "Lines\nand\ttabs\r\n, a form feed \f and a backspace \b",
    "Accents : déjà vu, naïve, Œuvre",
    "Emoji 🔐 and a CJK 鍵, outside the basic plane: \U0001d518",
    "```python\nif not hmac.compare_digest(a, b):\n    raise BadSignature\n```",
    'A fake key inside: "insufficient_context": true, {"answer": "x"}',
    "\u0001 control characters \u001f",
]


def document(answer: str, *, ascii_only: bool, answer_first: bool = True) -> str:
    fields = {"answer": answer, "insufficient_context": False}
    if not answer_first:
        fields = {"insufficient_context": True, "answer": answer}
    return json.dumps(fields, ensure_ascii=ascii_only)


def extract(fragments: list[str]) -> str:
    extractor = AnswerTextExtractor()
    return "".join(extractor.feed(fragment) for fragment in fragments)


@pytest.mark.parametrize("answer", ANSWERS)
@pytest.mark.parametrize("ascii_only", [True, False])
def test_every_cut_point_gives_the_same_text(answer: str, ascii_only: bool) -> None:
    text = document(answer, ascii_only=ascii_only)

    assert extract([text]) == answer
    # One character at a time: every escape and surrogate pair is cut somewhere.
    assert extract(list(text)) == answer
    for cut in range(len(text) + 1):
        assert extract([text[:cut], text[cut:]]) == answer


@pytest.mark.parametrize("seed", range(20))
def test_random_fragments(seed: int) -> None:
    rng = random.Random(seed)
    answer = "".join(rng.choice(ANSWERS) for _ in range(5))
    text = document(answer, ascii_only=rng.random() < 0.5)
    fragments, start = [], 0
    while start < len(text):
        size = rng.randint(1, 12)
        fragments.append(text[start : start + size])
        start += size

    assert extract(fragments) == answer


def test_text_arrives_as_the_fragments_do() -> None:
    extractor = AnswerTextExtractor()

    assert extractor.feed('{"answer": "Sig') == "Sig"
    assert extractor.feed("ned \\") == "ned "
    assert extractor.feed("u00e9 [S1]") == "é [S1]"
    assert extractor.feed('", "insufficient_context": false}') == ""


def test_the_answer_is_found_after_other_fields() -> None:
    assert extract([document("After", ascii_only=True, answer_first=False)]) == "After"


def test_whitespace_and_nested_values_are_skipped() -> None:
    text = '{\n  "meta": {"answer": "nested"},\n  "tags": ["answer"],\n  "answer" : "top"\n}'

    assert extract(list(text)) == "top"


def test_a_lone_surrogate_is_replaced() -> None:
    assert extract(['{"answer": "a\\ud83d b"}']) == f"a{REPLACEMENT} b"
    assert extract(['{"answer": "a\\ude00b"}']) == f"a{REPLACEMENT}b"


def test_an_incomplete_document_shows_what_arrived() -> None:
    # A truncated or refused stream: the draft is shown, validation rejects it later.
    assert extract(['{"answer": "Half an ans']) == "Half an ans"


def test_no_answer_field_gives_no_text() -> None:
    assert extract(['{"insufficient_context": true, "reason": "none"}']) == ""
