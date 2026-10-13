"""Links to GitHub's web interface."""

from pathlib import PurePosixPath
from urllib.parse import quote

# GitHub renders these files as documents, where line anchors do not exist.
# ``?plain=1`` shows the source instead, so that ``#L10-L20`` highlights the lines.
RENDERED_EXTENSIONS = frozenset({".md", ".markdown", ".rst", ".adoc", ".asciidoc", ".org"})


def line_permalink(
    repository: str, commit_sha: str, path: str, start_line: int, end_line: int
) -> str:
    """Permanent link to lines of a file at one commit.

    The commit SHA (not a branch name) keeps the link pointing to the cited lines
    even after the file changes.
    """
    url = f"https://github.com/{repository}/blob/{commit_sha}/{quote(path, safe='/')}"
    if PurePosixPath(path).suffix.lower() in RENDERED_EXTENSIONS:
        url += "?plain=1"
    anchor = f"L{start_line}" if start_line == end_line else f"L{start_line}-L{end_line}"
    return f"{url}#{anchor}"
