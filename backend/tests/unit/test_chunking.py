import itertools
import random

import pytest
from pydantic import ValidationError

from uaw.chunking.chunker import chunk_document
from uaw.chunking.lines import ChunkingConfig, is_blank, split_lines
from uaw.domain.chunks import Chunk
from uaw.domain.documents import SourceDocument

CONFIG = ChunkingConfig(max_chars=2000, min_chars=400, overlap_lines=2)
PADDING = "  # padding padding padding\n"  # makes each body line ~40 characters


def doc(content: str, language: str = "python") -> SourceDocument:
    return SourceDocument(path="src/example.py", language=language, content=content)


def py_function(name: str, body_lines: int, indent: str = "") -> str:
    body = "".join(f"{indent}    x_{i} = {i}{PADDING}" for i in range(body_lines))
    return f"{indent}def {name}():\n{body}\n"


def assert_invariants(document: SourceDocument, chunks: list[Chunk]) -> None:
    """Properties every chunking strategy must guarantee."""
    lines = split_lines(document.content)
    covered: set[int] = set()
    previous_start = previous_end = 0
    for chunk in chunks:
        # The citation guarantee: the chunk is exactly its line range.
        assert chunk.content == "".join(lines[chunk.start_line - 1 : chunk.end_line])
        assert not is_blank(lines[chunk.start_line - 1])
        assert not is_blank(lines[chunk.end_line - 1])
        # Chunks move forward: no duplicates, no chunk contained in the previous one.
        assert chunk.start_line > previous_start
        assert chunk.end_line > previous_end
        if chunk.end_line > chunk.start_line:
            assert len(chunk.content) <= CONFIG.max_chars
        previous_start, previous_end = chunk.start_line, chunk.end_line
        covered.update(range(chunk.start_line, chunk.end_line + 1))

    non_blank = {i + 1 for i, line in enumerate(lines) if not is_blank(line)}
    assert non_blank <= covered, "every non-blank line must belong to a chunk"


# --- line splitting ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("a", ["a"]),
        ("a\n", ["a\n"]),
        ("a\nb", ["a\n", "b"]),
        ("a\n\nb\n", ["a\n", "\n", "b\n"]),
        ("a\r\nb\r\n", ["a\r\n", "b\r\n"]),
        # Characters str.splitlines() would split on, but GitHub does not:
        ("a\x0cb\nc", ["a\x0cb\n", "c"]),
        ("a\N{LINE SEPARATOR}b\x85c\n", ["a\N{LINE SEPARATOR}b\x85c\n"]),
    ],
)
def test_split_lines_only_splits_on_newline(text: str, expected: list[str]) -> None:
    assert split_lines(text) == expected
    assert "".join(split_lines(text)) == text


def test_line_numbers_match_github_despite_form_feeds() -> None:
    content = "import os\n\x0c\ndef f():\n    return os.sep\n"

    (chunk,) = chunk_document(doc(content), CONFIG)

    assert (chunk.start_line, chunk.end_line) == (1, 4)


# --- configuration and model -----------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [{"min_chars": 0}, {"min_chars": 2000, "max_chars": 2000}, {"overlap_lines": -1}],
)
def test_invalid_config_is_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        ChunkingConfig(**kwargs)


def test_chunk_rejects_inverted_line_range() -> None:
    with pytest.raises(ValidationError):
        Chunk(path="a", language="python", start_line=5, end_line=4, content="x")


@pytest.mark.parametrize("content", ["", "\n\n", "   \n\t\n"])
def test_blank_documents_produce_no_chunks(content: str) -> None:
    assert chunk_document(doc(content), CONFIG) == []


# --- code ----------------------------------------------------------------------------


def test_code_chunks_align_with_functions_and_keep_decorators() -> None:
    content = (
        py_function("first", 20)
        + "\n@decorator\n"
        + py_function("second", 20)
        + "\n# Explains third.\n"
        + py_function("third", 20)
    )
    document = doc(content)

    chunks = chunk_document(document, CONFIG)

    assert [c.content.splitlines()[0] for c in chunks] == [
        "def first():",
        "@decorator",
        "# Explains third.",
    ]
    assert_invariants(document, chunks)


def test_small_functions_are_grouped() -> None:
    document = doc("".join(py_function(f"f{i}", 2) for i in range(12)))

    chunks = chunk_document(document, CONFIG)

    assert 1 < len(chunks) < 12
    assert all(c.content.startswith("def ") for c in chunks)
    assert all(len(c.content) >= CONFIG.min_chars for c in chunks[:-1])
    assert_invariants(document, chunks)


def test_forced_cut_prefers_a_definition_over_a_bigger_chunk() -> None:
    # A small function followed by a class too big to share a chunk with it: the cut
    # must fall on the class definition, not somewhere inside the class.
    small = py_function("small", 3)
    big_class = "class Big:\n" + "".join(f'    """doc line {i}{PADDING}' for i in range(60))
    document = doc(small + "\n" + big_class)

    chunks = chunk_document(document, CONFIG)

    assert chunks[0].content == small.rstrip("\n") + "\n"
    assert chunks[1].content.startswith("class Big:")
    assert_invariants(document, chunks)


def test_long_class_is_split_between_methods() -> None:
    # Each method has a blank line in its body: a weaker boundary than between methods.
    methods = "".join(
        f"\n    def m{i}(self):\n"
        + "".join(f"        a_{j} = {j}{PADDING}" for j in range(7))
        + "\n"
        + "".join(f"        b_{j} = {j}{PADDING}" for j in range(7))
        for i in range(8)
    )
    document = doc("class Big:\n" + methods)

    chunks = chunk_document(document, CONFIG)

    assert len(chunks) > 1
    assert all(c.content.startswith("    def m") for c in chunks[1:])
    assert_invariants(document, chunks)


def test_block_without_boundaries_is_cut_with_overlap() -> None:
    document = doc(py_function("huge", 200))

    chunks = chunk_document(document, CONFIG)

    assert len(chunks) > 3
    for previous, current in itertools.pairwise(chunks):
        assert current.start_line == previous.end_line - CONFIG.overlap_lines + 1
    assert_invariants(document, chunks)


def test_line_longer_than_max_chars_is_kept_whole() -> None:
    long_line = "data = '" + "x" * 5000 + "'\n"
    document = doc("import os\n" + long_line + "print(data)\n")

    chunks = chunk_document(document, CONFIG)

    assert any(c.content == long_line for c in chunks)
    assert_invariants(document, chunks)


# --- markdown --------------------------------------------------------------------------

MARKDOWN = """Intro paragraph.

# Project

Overview.

## Install

```bash
# not a heading
pip install project
```

### Windows

Use WSL.

## Usage

Run it.
"""


def test_markdown_is_split_by_section_with_breadcrumbs() -> None:
    document = doc(MARKDOWN, language="markdown")

    chunks = chunk_document(document, CONFIG)

    assert [(c.section, c.start_line, c.end_line) for c in chunks] == [
        (None, 1, 1),
        ("Project", 3, 5),
        ("Project > Install", 7, 12),
        ("Project > Install > Windows", 14, 16),
        ("Project > Usage", 18, 20),
    ]
    assert "# not a heading" in chunks[2].content
    assert_invariants(document, chunks)


@pytest.mark.parametrize("line", ["#hashtag", "####### seven", "    # indented code"])
def test_lines_that_are_not_atx_headings(line: str) -> None:
    document = doc(f"# Title\n\n{line}\n", language="markdown")

    (chunk,) = chunk_document(document, CONFIG)

    assert chunk.section == "Title"


def test_long_section_is_split_and_keeps_its_section() -> None:
    paragraphs = "".join(f"Paragraph {i} " + "lorem ipsum " * 10 + "\n\n" for i in range(40))
    document = doc("# Guide\n\n" + paragraphs, language="markdown")

    chunks = chunk_document(document, CONFIG)

    assert len(chunks) > 1
    assert {c.section for c in chunks} == {"Guide"}
    assert_invariants(document, chunks)


# --- invariants on random input -------------------------------------------------------


@pytest.mark.parametrize("seed", range(50))
def test_invariants_hold_on_random_documents(seed: int) -> None:
    rng = random.Random(seed)
    pieces = [
        "",
        "    ",
        "def f():",
        "    return 1",
        "class A:",
        "@decorator",
        "# Heading",
        "## Sub",
        "```",
        "\x0c",
        "text " * rng.randint(1, 80),
        "x" * rng.randint(100, 3000),
    ]
    lines = [rng.choice(pieces) for _ in range(rng.randint(0, 300))]
    content = "\n".join(lines) + rng.choice(["", "\n", "\r\n"])

    for language in ("python", "markdown", "text"):
        document = doc(content, language=language)
        assert_invariants(document, chunk_document(document, CONFIG))
