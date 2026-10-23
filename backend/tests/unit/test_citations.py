from tests.generation_fakes import sources
from uaw.generation.citations import resolve_citations

SOURCES = sources("auth.py", "tokens.py", "README.md")


def test_valid_citations_map_to_files_lines_and_links() -> None:
    resolved = resolve_citations("Tokens are signed [S2] and checked [S1].", SOURCES)

    assert resolved.text == "Tokens are signed [S2] and checked [S1]."
    assert [(c.id, c.path, c.start_line, c.end_line) for c in resolved.citations] == [
        ("S2", "tokens.py", 1, 3),
        ("S1", "auth.py", 1, 3),
    ]
    assert resolved.citations[0].url.endswith("/tokens.py#L1-L3")
    assert resolved.unknown_ids == []


def test_invented_ids_are_removed_from_the_text() -> None:
    resolved = resolve_citations("Signed [S9]. Checked [S1][S7]. Done [S0, S2].", SOURCES)

    assert resolved.text == "Signed. Checked [S1]. Done [S2]."
    assert [c.id for c in resolved.citations] == ["S1", "S2"]
    assert resolved.unknown_ids == ["S9", "S7", "S0"]


def test_grouped_and_repeated_citations_are_normalized() -> None:
    resolved = resolve_citations("A [S1, S3]. B [S3;S1]. C [ S1 ].", SOURCES)

    assert resolved.text == "A [S1][S3]. B [S3][S1]. C [S1]."
    assert [c.id for c in resolved.citations] == ["S1", "S3"]  # each listed once


def test_text_without_citations_is_unchanged() -> None:
    text = "No sources here, only code: `items[0]` and [link](https://x.y)."

    resolved = resolve_citations(text, SOURCES)

    assert resolved.text == text
    assert resolved.citations == []


def test_spacing_is_kept_in_code_when_a_citation_is_removed() -> None:
    resolved = resolve_citations("x = a ; b [S9]\n```\nf(a , b)\n```", SOURCES)

    assert resolved.text == "x = a ; b\n```\nf(a , b)\n```"
