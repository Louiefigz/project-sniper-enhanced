"""One byte-level USTAR representation for retained render inputs."""
from __future__ import annotations

import io
import tarfile


def _entry(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o444
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    archive.addfile(info, io.BytesIO(data))


def canonical_tar_bytes(entries: dict[str, bytes]) -> bytes:
    """Serialize an exact sorted USTAR archive with no extension headers."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, data in sorted(entries.items()):
            _entry(tar, name, data)
    return buffer.getvalue()
