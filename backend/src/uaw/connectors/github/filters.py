"""Decide which repository files are worth indexing, based on their path only.

The rules are allowlist-based: a file is indexed only if its type is explicitly
supported. Content checks (size, binary, encoding) happen in ``archive.py``.
"""

from enum import StrEnum
from pathlib import PurePosixPath


class SkipReason(StrEnum):
    UNSAFE_PATH = "unsafe_path"
    NOT_REGULAR_FILE = "not_regular_file"
    IGNORED_DIRECTORY = "ignored_directory"
    SENSITIVE_FILE = "sensitive_file"
    GENERATED_FILE = "generated_file"
    UNSUPPORTED_TYPE = "unsupported_type"
    TOO_LARGE = "too_large"
    EMPTY = "empty"
    BINARY = "binary"
    NOT_UTF8 = "not_utf8"
    FILE_LIMIT_REACHED = "file_limit_reached"


LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".swift": "swift",
    ".sh": "shell",
    ".bash": "shell",
    ".ps1": "powershell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".vue": "vue",
    ".svelte": "svelte",
    ".graphql": "graphql",
    ".proto": "protobuf",
    ".tf": "terraform",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "restructuredtext",
    ".txt": "text",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".ini": "ini",
    ".cfg": "ini",
    ".xml": "xml",
}

# Extensionless (or unusual) file names, compared case-insensitively.
LANGUAGE_BY_FILENAME: dict[str, str] = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
    "readme": "text",
    ".env.example": "dotenv",
    ".env.sample": "dotenv",
}

IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        "node_modules",
        "bower_components",
        "vendor",
        "dist",
        "build",
        "target",
        "out",
        "coverage",
        "__pycache__",
        ".venv",
        "venv",
        "site-packages",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".next",
        ".nuxt",
        ".gradle",
        ".idea",
        ".vscode",
    }
)

LOCKFILES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "uv.lock",
        "pipfile.lock",
        "cargo.lock",
        "gemfile.lock",
        "composer.lock",
        "go.sum",
    }
)

SENSITIVE_FILENAMES = frozenset(
    {".npmrc", ".pypirc", ".netrc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}
)
SENSITIVE_EXTENSIONS = frozenset({".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"})
_NON_SECRET_ENV_FILES = frozenset({".env.example", ".env.sample", ".env.template"})


def _is_sensitive(name: str, suffix: str) -> bool:
    if name.startswith(".env") and name not in _NON_SECRET_ENV_FILES:
        return True
    return name in SENSITIVE_FILENAMES or suffix in SENSITIVE_EXTENSIONS


def classify_path(path: PurePosixPath) -> str | SkipReason:
    """Return the file's language if it should be indexed, otherwise why it is skipped."""
    if any(part.lower() in IGNORED_DIRECTORIES for part in path.parts[:-1]):
        return SkipReason.IGNORED_DIRECTORY

    name = path.name.lower()
    suffix = path.suffix.lower()
    if _is_sensitive(name, suffix):
        return SkipReason.SENSITIVE_FILE
    if name in LOCKFILES or name.endswith((".min.js", ".min.css")):
        return SkipReason.GENERATED_FILE

    language = LANGUAGE_BY_FILENAME.get(name) or LANGUAGE_BY_EXTENSION.get(suffix)
    return language if language is not None else SkipReason.UNSUPPORTED_TYPE
