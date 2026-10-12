"""Safe, in-memory reading of a GitHub repository tarball.

Repository archives are untrusted input. This module:
- never extracts anything to disk and never executes anything;
- reads the archive in streaming mode, so it is decompressed once, sequentially,
  with no backward seeks;
- verifies the gzip stream to its end (end marker and CRC), so a truncated or
  corrupted download fails loudly instead of producing a partial index;
- caps the number of entries and the total decompressed size, skipped entries and
  trailing data included, which defuses decompression bombs;
- requires GitHub's layout (a single top-level directory) and rejects unsafe paths
  (absolute, ``..``, backslashes, control characters);
- reads only regular files (no symlinks, hardlinks or devices).
"""

import gzip
import io
import logging
import tarfile
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict

from uaw.connectors.github.errors import InvalidArchiveError, RepositoryTooLargeError
from uaw.connectors.github.filters import SkipReason, classify_path
from uaw.domain.documents import SourceDocument

logger = logging.getLogger(__name__)

MAX_PATH_LENGTH = 1024
_DRAIN_CHUNK_BYTES = 64 * 1024
_MAX_DISPLAY_PATH_LENGTH = 200


@dataclass(frozen=True)
class ArchiveLimits:
    max_uncompressed_bytes: int
    max_entries: int
    max_file_bytes: int
    max_files: int


class SkippedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    reason: SkipReason


class ArchiveReadResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    documents: list[SourceDocument]
    skipped: list[SkippedFile]


def read_repository_archive(data: bytes, limits: ArchiveLimits) -> ArchiveReadResult:
    """Read the indexable text files of a GitHub ``.tar.gz`` archive.

    Raises:
        RepositoryTooLargeError: if the archive exceeds the entry or size limits.
        InvalidArchiveError: if the archive is corrupt, truncated or not GitHub-shaped.
    """
    reader = _ArchiveReader(limits)
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as gz:
            with tarfile.open(fileobj=gz, mode="r|") as tar:
                for member in tar:
                    reader.process(tar, member)
            reader.drain(gz)
    except (tarfile.TarError, EOFError, zlib.error, OSError) as exc:
        raise InvalidArchiveError("The repository archive could not be read.") from exc
    if reader.root is None:
        raise InvalidArchiveError("The repository archive is empty.")

    logger.info(
        "Archive read: %d entries, %d bytes uncompressed, %d documents, %d skipped",
        reader.entry_count,
        reader.uncompressed_bytes,
        len(reader.documents),
        len(reader.skipped),
    )
    return ArchiveReadResult(
        documents=sorted(reader.documents, key=lambda doc: doc.path),
        skipped=sorted(reader.skipped, key=lambda item: item.path),
    )


class _ArchiveReader:
    def __init__(self, limits: ArchiveLimits) -> None:
        self.limits = limits
        self.root: str | None = None
        self.entry_count = 0
        self.uncompressed_bytes = 0
        self.documents: list[SourceDocument] = []
        self.skipped: list[SkippedFile] = []

    def process(self, tar: tarfile.TarFile, member: tarfile.TarInfo) -> None:
        self.entry_count += 1
        if self.entry_count > self.limits.max_entries:
            raise RepositoryTooLargeError(
                f"The repository contains too many files (max {self.limits.max_entries})."
            )
        self._count_uncompressed(member.size)

        if self.root is None:
            self.root = _root_directory(member)
            return
        if member.isdir():
            return

        path = self._relative_path(member.name)
        if path is None:
            self._skip(_display_path(member.name), SkipReason.UNSAFE_PATH)
            return
        if not member.isreg():
            self._skip(str(path), SkipReason.NOT_REGULAR_FILE)
            return

        classification = classify_path(path)
        if isinstance(classification, SkipReason):
            self._skip(str(path), classification)
            return
        if member.size > self.limits.max_file_bytes:
            self._skip(str(path), SkipReason.TOO_LARGE)
            return
        if member.size == 0:
            self._skip(str(path), SkipReason.EMPTY)
            return
        if len(self.documents) >= self.limits.max_files:
            self._skip(str(path), SkipReason.FILE_LIMIT_REACHED)
            return

        fileobj = tar.extractfile(member)
        if fileobj is None:  # pragma: no cover - regular files always have content
            self._skip(str(path), SkipReason.NOT_REGULAR_FILE)
            return
        raw = fileobj.read(self.limits.max_file_bytes + 1)
        self._add_document(path, classification, raw)

    def drain(self, gz: gzip.GzipFile) -> None:
        """Read the rest of the gzip stream to verify it is complete and intact.

        ``tarfile`` stops at the end-of-archive marker, and in streaming mode it treats
        a truncated header as a normal end of archive. Reading to the end makes gzip
        check its end marker and CRC. Trailing bytes count toward the size limit.
        """
        while chunk := gz.read(_DRAIN_CHUNK_BYTES):
            self._count_uncompressed(len(chunk))

    def _count_uncompressed(self, size: int) -> None:
        self.uncompressed_bytes += max(size, 0)
        if self.uncompressed_bytes > self.limits.max_uncompressed_bytes:
            max_mb = self.limits.max_uncompressed_bytes // (1024 * 1024)
            raise RepositoryTooLargeError(
                f"The repository is too large once uncompressed (max {max_mb} MB)."
            )

    def _relative_path(self, name: str) -> PurePosixPath | None:
        """Strip the top-level directory and validate the rest as a plain relative path."""
        if not _is_printable_relative(name):
            return None
        parts = name.removesuffix("/").split("/")
        if any(part in ("", ".", "..") for part in parts):
            return None
        root, *relative = parts
        if root != self.root or not relative:
            return None
        return PurePosixPath(*relative)

    def _add_document(self, path: PurePosixPath, language: str, raw: bytes) -> None:
        # The whole file is scanned (files are small): PostgreSQL text cannot store NUL.
        if b"\x00" in raw:
            self._skip(str(path), SkipReason.BINARY)
            return
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            self._skip(str(path), SkipReason.NOT_UTF8)
            return
        self.documents.append(SourceDocument(path=str(path), language=language, content=content))

    def _skip(self, path: str, reason: SkipReason) -> None:
        self.skipped.append(SkippedFile(path=path, reason=reason))


def _root_directory(member: tarfile.TarInfo) -> str:
    """GitHub archives start with their single top-level directory (``owner-repo-sha/``)."""
    name = member.name.removesuffix("/")
    if (
        not member.isdir()
        or not _is_printable_relative(name)
        or "/" in name
        or name in ("", ".", "..")
    ):
        raise InvalidArchiveError("The repository archive has an unexpected layout.")
    return name


def _is_printable_relative(name: str) -> bool:
    return (
        len(name) <= MAX_PATH_LENGTH
        and "\\" not in name
        and not name.startswith("/")
        and not any(ord(char) < 32 or ord(char) == 127 for char in name)
    )


def _display_path(name: str) -> str:
    """Make an untrusted archive path safe to log, store and display."""
    escaped = name.encode("unicode_escape").decode("ascii")
    return escaped[:_MAX_DISPLAY_PATH_LENGTH]
