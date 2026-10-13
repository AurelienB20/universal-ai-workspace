import pytest

from uaw.connectors.github.links import line_permalink

SHA = "0123456789abcdef0123456789abcdef01234567"


def test_links_to_a_line_range_at_the_commit() -> None:
    url = line_permalink("Pallets/Flask", SHA, "src/flask/app.py", 10, 42)

    assert url == f"https://github.com/Pallets/Flask/blob/{SHA}/src/flask/app.py#L10-L42"


def test_single_line_uses_a_single_anchor() -> None:
    assert line_permalink("o/r", SHA, "a.py", 7, 7).endswith("/a.py#L7")


@pytest.mark.parametrize("path", ["README.md", "docs/guide.RST", "notes.adoc"])
def test_rendered_documents_link_to_their_source_view(path: str) -> None:
    # Line anchors only work on the source view of files GitHub renders.
    assert f"/{path}?plain=1#L1-L3" in line_permalink("o/r", SHA, path, 1, 3)


def test_special_characters_in_paths_are_encoded() -> None:
    url = line_permalink("o/r", SHA, "docs/my file#1?.py", 1, 2)

    assert url.endswith("/docs/my%20file%231%3F.py#L1-L2")
