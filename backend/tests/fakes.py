"""Test doubles for external services (GitHub, Voyage)."""

import hashlib
from collections.abc import Sequence

from uaw.connectors.github.client import RepositoryInfo
from uaw.connectors.github.connector import FetchedRepository
from uaw.connectors.github.url import GitHubRepoRef
from uaw.domain.documents import SourceDocument
from uaw.storage.models import EMBEDDING_DIMENSIONS

SHA = "c" * 40

DOCUMENTS = [
    SourceDocument(
        path="src/auth.py",
        language="python",
        content="".join(f"def check_{i}(token):\n    return token == {i}\n\n\n" for i in range(30)),
    ),
    SourceDocument(path="README.md", language="markdown", content="# Demo\n\nHello.\n"),
]


def fake_vector(text: str) -> list[float]:
    """Deterministic, non-zero vector derived from the text."""
    digest = hashlib.sha256(text.encode()).digest()
    return [(digest[i % len(digest)] + 1) / 256 for i in range(EMBEDDING_DIMENSIONS)]


class FakeEmbedder:
    def __init__(self, *, fail_on_call: int | None = None, error: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self._fail_on_call = fail_on_call
        self._error = error

    @property
    def model(self) -> str:
        return "fake-embedder"

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self._error is not None and len(self.calls) == self._fail_on_call:
            raise self._error
        return [fake_vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return fake_vector(text)


class FakeSource:
    def __init__(
        self,
        documents: list[SourceDocument] | None = None,
        *,
        sha: str = SHA,
        error: Exception | None = None,
    ) -> None:
        self.documents = DOCUMENTS if documents is None else documents
        self.sha = sha
        self.error = error
        self.fetched: list[GitHubRepoRef] = []

    async def fetch(self, ref: GitHubRepoRef) -> FetchedRepository:
        self.fetched.append(ref)
        if self.error is not None:
            raise self.error
        # GitHub reports the canonical casing, whatever the user typed.
        canonical = GitHubRepoRef(owner="Octo", name="Demo")
        return FetchedRepository(
            info=RepositoryInfo(
                ref=canonical, default_branch="main", size_kb=1, private=False, description=None
            ),
            commit_sha=self.sha,
            documents=self.documents,
            skipped=[],
        )
