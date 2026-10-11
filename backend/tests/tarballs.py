"""Build in-memory .tar.gz archives shaped like GitHub's, including malicious ones."""

import io
import tarfile
from dataclasses import dataclass

ROOT = "octo-hello-1a2b3c4"


@dataclass(frozen=True)
class Entry:
    name: str  # full name inside the archive
    data: bytes = b""
    kind: bytes = tarfile.REGTYPE
    linkname: str = ""


def file(path: str, data: bytes | str = "content\n") -> Entry:
    """A regular file under the archive's root directory."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return Entry(name=f"{ROOT}/{path}", data=raw)


def raw_file(name: str, data: bytes = b"content\n") -> Entry:
    """A regular file with an arbitrary (possibly malicious) archive name."""
    return Entry(name=name, data=data)


def symlink(path: str, target: str) -> Entry:
    return Entry(name=f"{ROOT}/{path}", kind=tarfile.SYMTYPE, linkname=target)


def hardlink(path: str, target: str) -> Entry:
    return Entry(name=f"{ROOT}/{path}", kind=tarfile.LNKTYPE, linkname=target)


def make_tarball(*entries: Entry, with_root_dir: bool = True) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        if with_root_dir:
            root = tarfile.TarInfo(f"{ROOT}/")
            root.type = tarfile.DIRTYPE
            tar.addfile(root)
        for entry in entries:
            info = tarfile.TarInfo(entry.name)
            info.type = entry.kind
            info.linkname = entry.linkname
            if entry.kind == tarfile.REGTYPE:
                info.size = len(entry.data)
                tar.addfile(info, io.BytesIO(entry.data))
            else:
                tar.addfile(info)
    return buffer.getvalue()
