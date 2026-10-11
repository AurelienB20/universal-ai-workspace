from pathlib import PurePosixPath

import pytest

from uaw.connectors.github.filters import SkipReason, classify_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/app.py", "python"),
        ("web/App.TSX", "typescript"),
        ("README.md", "markdown"),
        ("README", "text"),
        ("docker/Dockerfile", "dockerfile"),
        ("Makefile", "makefile"),
        (".github/workflows/ci.yml", "yaml"),
        (".env.example", "dotenv"),
        ("config/settings.toml", "toml"),
    ],
)
def test_supported_files(path: str, expected: str) -> None:
    assert classify_path(PurePosixPath(path)) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("node_modules/lib/index.js", SkipReason.IGNORED_DIRECTORY),
        ("frontend/node_modules/x.js", SkipReason.IGNORED_DIRECTORY),
        ("vendor/pkg/a.go", SkipReason.IGNORED_DIRECTORY),
        ("Build/out.js", SkipReason.IGNORED_DIRECTORY),
        (".git/config", SkipReason.IGNORED_DIRECTORY),
        (".env", SkipReason.SENSITIVE_FILE),
        ("deploy/.env.production", SkipReason.SENSITIVE_FILE),
        ("certs/server.pem", SkipReason.SENSITIVE_FILE),
        ("keys/id_rsa", SkipReason.SENSITIVE_FILE),
        (".npmrc", SkipReason.SENSITIVE_FILE),
        ("package-lock.json", SkipReason.GENERATED_FILE),
        ("uv.lock", SkipReason.GENERATED_FILE),
        ("static/app.min.js", SkipReason.GENERATED_FILE),
        ("logo.png", SkipReason.UNSUPPORTED_TYPE),
        ("data.bin", SkipReason.UNSUPPORTED_TYPE),
        ("LICENSE", SkipReason.UNSUPPORTED_TYPE),
    ],
)
def test_skipped_files(path: str, expected: SkipReason) -> None:
    assert classify_path(PurePosixPath(path)) == expected


def test_a_file_named_like_an_ignored_directory_is_kept() -> None:
    # Only parent directories are matched against the ignore list.
    assert classify_path(PurePosixPath("docs/build.md")) == "markdown"
