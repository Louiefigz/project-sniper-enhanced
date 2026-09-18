"""Small exact metadata holds and new-only grade launch publications.

These files are evidence, never an authority to discover, delete or adopt work.
Publication fsyncs both the file and its held private directory; partial files
remain on every failure. No media bytes or subprocesses are read or executed.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from cross_runtime_canonical_json import canonical_compact_json
from cut_preview_io import read_bytes, real_directory
from headless.durable_files import open_private_dir, open_private_file, write_all
from headless.external_media_verification import snapshot_stat_identity


def directory_identity(path: Path) -> tuple:
    """Hold canonical parent inodes without binding mutable directory contents."""
    real_directory(path)
    return tuple((str(item), info.st_dev, info.st_ino, info.st_mode, info.st_uid)
                 for item in (path, *path.parents) for info in (item.lstat(),))


def private_file_identity(path: Path) -> tuple:
    """Accept actual historical private 0600 and new read-only 0400 records."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() \
            or stat.S_IMODE(info.st_mode) not in (0o400, 0o600):
        raise RuntimeError("grade launch metadata must be owned private single-link bytes")
    return snapshot_stat_identity(info)


@dataclass(frozen=True)
class HeldLaunchFile:
    """Raw bytes and same-pass identities, not a deserialized execution owner."""

    path: Path
    raw: bytes
    identity: tuple
    parents: tuple

    @property
    def sha256(self) -> str:
        """Return the raw-file digest, never a resealed JSON digest."""
        return hashlib.sha256(self.raw).hexdigest()

    def value(self) -> dict:
        """Return a fresh data-only projection without exposing the held bytes."""
        result = json.loads(self.raw.decode("utf8", errors="strict"))
        if type(result) is not dict:
            raise RuntimeError("grade launch metadata must be a JSON object")
        return result

    def check(self) -> None:
        """Reject changed bytes, links, modes or any original parent replacement."""
        if directory_identity(self.path.parent) != self.parents \
                or private_file_identity(self.path) != self.identity:
            raise RuntimeError("grade launch held metadata identity changed")


def hold_launch_file(path: Path, expected: str) -> HeldLaunchFile:
    """Read bounded raw metadata against an independently supplied digest."""
    parents = directory_identity(path.parent)
    before = private_file_identity(path)
    raw = read_bytes(path, 128 * 1024)
    held = HeldLaunchFile(path, raw, before, parents)
    held.check()
    if held.sha256 != expected:
        raise RuntimeError("grade launch raw metadata hash changed")
    held.value()
    return held


def publish_launch_file(directory: Path, name: str, value: dict) -> HeldLaunchFile:
    """Durably publish one fixed new file; never retry, replace or remove it."""
    if name not in ("launch-intent.json", "launch-response.json"):
        raise ValueError("grade launch publication name is unsupported")
    raw = (canonical_compact_json(value) + "\n").encode("utf8")
    if len(raw) > 128 * 1024:
        raise RuntimeError("grade launch publication exceeds metadata bound")
    parents = directory_identity(directory)
    directory_fd = open_private_dir(str(directory))
    try:
        descriptor = open_private_file(directory_fd, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            write_all(descriptor, raw)
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(directory_fd)
        info = os.fstat(directory_fd)
        if directory_identity(directory) != parents or (info.st_dev, info.st_ino) != parents[0][1:3]:
            raise RuntimeError("grade launch publication directory changed")
        return hold_launch_file(directory / name, hashlib.sha256(raw).hexdigest())
    finally:
        os.close(directory_fd)
