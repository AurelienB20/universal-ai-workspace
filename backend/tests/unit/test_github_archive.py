import gzip
import secrets
from dataclasses import replace

import pytest

from tests.tarballs import ROOT, Entry, file, hardlink, make_tarball, raw_file, symlink
from uaw.connectors.github.archive import ArchiveLimits, read_repository_archive
from uaw.connectors.github.errors import InvalidArchiveError, RepositoryTooLargeError
from uaw.connectors.github.filters import SkipReason

LIMITS = ArchiveLimits(
    max_uncompressed_bytes=10 * 1024 * 1024,
    max_entries=1000,
    max_file_bytes=1024,
    max_files=100,
)


def skipped_reasons(data: bytes, limits: ArchiveLimits = LIMITS) -> dict[str, SkipReason]:
    return {item.path: item.reason for item in read_repository_archive(data, limits).skipped}


def test_reads_supported_files_with_paths_relative_to_repository_root() -> None:
    data = make_tarball(
        file("src/app.py", "def main():\n    return 1\n"),
        file("README.md", "# Hello\n"),
        file("docs/guide.md", "Guide\n"),
    )

    result = read_repository_archive(data, LIMITS)

    assert [(doc.path, doc.language) for doc in result.documents] == [
        ("README.md", "markdown"),
        ("docs/guide.md", "markdown"),
        ("src/app.py", "python"),
    ]
    assert result.documents[2].content == "def main():\n    return 1\n"
    assert result.skipped == []


def test_strips_utf8_bom() -> None:
    data = make_tarball(file("a.py", b"\xef\xbb\xbfx = 1\n"))

    assert read_repository_archive(data, LIMITS).documents[0].content == "x = 1\n"


def test_reports_why_each_file_was_skipped() -> None:
    data = make_tarball(
        file("node_modules/lib.js"),
        file(".env", "SECRET=1\n"),
        file("package-lock.json", "{}"),
        file("logo.png", b"\x89PNG"),
        file("big.py", "x" * (LIMITS.max_file_bytes + 1)),
        file("empty.py", ""),
        file("binary.py", b"abc\x00def"),
        file("latin1.py", "café".encode("latin-1")),
        symlink("link.py", "/etc/passwd"),
        hardlink("hard.py", f"{ROOT}/empty.py"),
    )

    assert skipped_reasons(data) == {
        "node_modules/lib.js": SkipReason.IGNORED_DIRECTORY,
        ".env": SkipReason.SENSITIVE_FILE,
        "package-lock.json": SkipReason.GENERATED_FILE,
        "logo.png": SkipReason.UNSUPPORTED_TYPE,
        "big.py": SkipReason.TOO_LARGE,
        "empty.py": SkipReason.EMPTY,
        "binary.py": SkipReason.BINARY,
        "latin1.py": SkipReason.NOT_UTF8,
        "link.py": SkipReason.NOT_REGULAR_FILE,
        "hard.py": SkipReason.NOT_REGULAR_FILE,
    }


@pytest.mark.parametrize(
    "malicious_name",
    [
        f"{ROOT}/../evil.py",
        f"{ROOT}/src/../../evil.py",
        "/etc/evil.py",
        "other-root/evil.py",
        "toplevel.py",
        f"{ROOT}/a\\..\\evil.py",
        f"{ROOT}/./evil.py",
        f"{ROOT}//evil.py",
        f"{ROOT}/evil\n.py",
        f"{ROOT}/" + "a/" * 600 + "evil.py",
    ],
)
def test_rejects_unsafe_paths_and_keeps_safe_files(malicious_name: str) -> None:
    data = make_tarball(raw_file(malicious_name), file("ok.py"))

    result = read_repository_archive(data, LIMITS)

    assert [doc.path for doc in result.documents] == ["ok.py"]
    assert [item.reason for item in result.skipped] == [SkipReason.UNSAFE_PATH]


@pytest.mark.parametrize(
    "first_entry",
    [raw_file("../evil.py"), raw_file("README.md"), raw_file("evil/x.py")],
    ids=["traversal", "root-level-file", "file-not-directory"],
)
def test_archive_must_start_with_its_root_directory(first_entry: Entry) -> None:
    data = make_tarball(first_entry, file("ok.py"), with_root_dir=False)

    with pytest.raises(InvalidArchiveError):
        read_repository_archive(data, LIMITS)


def test_archive_without_entries_is_invalid() -> None:
    with pytest.raises(InvalidArchiveError):
        read_repository_archive(make_tarball(with_root_dir=False), LIMITS)


def test_data_hidden_after_the_end_of_archive_counts_toward_the_size_limit() -> None:
    # A valid tar followed by 2 MB of trailing zeros inside the same gzip stream.
    tar_bytes = gzip.decompress(make_tarball(file("a.py")))
    data = gzip.compress(tar_bytes + b"\x00" * (2 * 1024 * 1024))
    limits = replace(LIMITS, max_uncompressed_bytes=1024 * 1024)

    with pytest.raises(RepositoryTooLargeError):
        read_repository_archive(data, limits)


def test_unsafe_paths_are_escaped_before_being_reported() -> None:
    data = make_tarball(raw_file(f"{ROOT}/../evil\n\x1b[31m.py"))

    (skipped,) = read_repository_archive(data, LIMITS).skipped

    assert "\n" not in skipped.path
    assert "\x1b" not in skipped.path


def test_stops_indexing_after_max_files() -> None:
    limits = replace(LIMITS, max_files=2)
    data = make_tarball(file("a.py"), file("b.py"), file("c.py"))

    result = read_repository_archive(data, limits)

    assert [doc.path for doc in result.documents] == ["a.py", "b.py"]
    assert {item.path: item.reason for item in result.skipped} == {
        "c.py": SkipReason.FILE_LIMIT_REACHED
    }


def test_decompression_bomb_is_rejected() -> None:
    # 2 MB of zeros compresses to a few KB. The cap applies to skipped files too.
    limits = replace(LIMITS, max_uncompressed_bytes=1024 * 1024)
    data = make_tarball(file("bomb.bin", b"\x00" * (2 * 1024 * 1024)))
    assert len(data) < 20_000

    with pytest.raises(RepositoryTooLargeError):
        read_repository_archive(data, limits)


def test_too_many_entries_is_rejected() -> None:
    limits = replace(LIMITS, max_entries=5)
    data = make_tarball(*(file(f"f{i}.py") for i in range(10)))

    with pytest.raises(RepositoryTooLargeError):
        read_repository_archive(data, limits)


def _truncated_archive(keep_ratio: float) -> bytes:
    # Hex text barely compresses, so cutting the gzip stream really loses content.
    data = make_tarball(file("a.py", secrets.token_hex(20_000)), file("b.py"))
    return data[: int(len(data) * keep_ratio)]


def _corrupted_crc() -> bytes:
    data = bytearray(make_tarball(file("a.py")))
    data[-8] ^= 0xFF  # first byte of the gzip trailer's CRC32
    return bytes(data)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a tarball at all",
        _truncated_archive(0.5),
        _truncated_archive(0.99),
        # These two are only caught by reading the gzip stream to its end:
        make_tarball(file("a.py"))[:-8],
        _corrupted_crc(),
    ],
    ids=["empty", "garbage", "truncated-half", "truncated-end", "trailer-cut", "bad-crc"],
)
def test_corrupt_archives_raise_invalid_archive(data: bytes) -> None:
    with pytest.raises(InvalidArchiveError):
        read_repository_archive(data, LIMITS)
