"""Attempt-private imports and atomic outputs for prebound composition."""

from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
from dataclasses import dataclass
from typing import Callable

from .container_io import promote_regular
from .durable_files import (
    exact_directory_entries,
    open_private_dir,
    open_private_file,
    private_child_dir,
    write_all,
)
from .quality_pass_contract import ArtifactRefV1

_MAX_NAME_BYTES = 220


def _name(value: object) -> str:
    valid = type(value) is str and value not in {"", ".", ".."}
    valid = valid and "/" not in value and "\\" not in value
    valid = valid and unicodedata.normalize("NFC", value) == value
    valid = valid and not any(
        ord(char) < 32 or ord(char) == 127 for char in value
    )
    try:
        encoded = value.encode("utf-8") if valid else b""
    except UnicodeEncodeError:
        encoded = b""
    if not 0 < len(encoded) <= _MAX_NAME_BYTES:
        raise RuntimeError("candidate artifact name is invalid")
    return value


def _write_once(dir_fd: int, name: str, raw: bytes) -> None:
    if type(raw) is not bytes:
        raise RuntimeError("candidate artifact bytes are invalid")
    fd = open_private_file(dir_fd, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(dir_fd)


def _open_output(root_fd: int, name: str) -> tuple[int, tuple[int, int]]:
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    fd = os.open(name, flags, dir_fd=root_fd)
    info = os.fstat(fd)
    safe = stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    safe = safe and info.st_uid == os.geteuid() and info.st_size > 0
    if not safe:
        os.close(fd)
        raise RuntimeError("candidate output is not one owned regular file")
    return fd, (info.st_dev, info.st_ino)


@dataclass
class CandidateStore:
    """Held private root and exact-ref import capability."""

    root: str
    root_fd: int
    resolver: Callable[[ArtifactRefV1], str]

    @classmethod
    def open(
        cls, root: str, resolver: Callable[[ArtifactRefV1], str]
    ) -> "CandidateStore":
        root_fd = open_private_dir(root)
        try:
            if not callable(resolver) or not exact_directory_entries(
                root_fd, set()
            ):
                raise RuntimeError(
                    "candidate root must be a new empty directory"
                )
            child_fd = private_child_dir(root_fd, "inputs")
            os.close(child_fd)
            return cls(root, root_fd, resolver)
        except BaseException:
            os.close(root_fd)
            raise

    def close(self) -> None:
        os.close(self.root_fd)

    def write(self, name: str, raw: bytes) -> ArtifactRefV1:
        """Durably publish one immutable candidate JSON artifact."""
        checked = _name(name)
        _write_once(self.root_fd, checked, raw)
        return ArtifactRefV1(
            checked, hashlib.sha256(raw).hexdigest(), len(raw)
        )

    def import_artifact(self, ref: ArtifactRefV1, name: str) -> str:
        """Copy exact referenced bytes into the candidate input snapshot."""
        checked = _name(name)
        source = self.resolver(ref)
        valid = (
            type(source) is str
            and os.path.isabs(source)
            and os.path.realpath(source) == source
            and os.path.normpath(source) == source
        )
        if not valid:
            raise RuntimeError("artifact resolver returned an ambient path")
        destination = os.path.join(self.root, "inputs", checked)
        promote_regular(source, destination, ref.sha256, ref.size_bytes)
        return destination

    def promote(self, pending: str, final: str) -> str:
        """Publish one private output without replacing an existing name."""
        pending_name, final_name = _name(pending), _name(final)
        if pending_name == final_name:
            raise RuntimeError("candidate output names alias")
        fd, identity = _open_output(self.root_fd, pending_name)
        try:
            os.fchmod(fd, 0o600)
            os.fsync(fd)
            os.link(
                pending_name,
                final_name,
                src_dir_fd=self.root_fd,
                dst_dir_fd=self.root_fd,
                follow_symlinks=False,
            )
            final_info = os.stat(
                final_name, dir_fd=self.root_fd, follow_symlinks=False
            )
            if (final_info.st_dev, final_info.st_ino) != identity:
                raise RuntimeError("candidate output changed during promotion")
            os.unlink(pending_name, dir_fd=self.root_fd)
            os.fsync(self.root_fd)
            retained = os.stat(
                final_name, dir_fd=self.root_fd, follow_symlinks=False
            )
            stable = (retained.st_dev, retained.st_ino) == identity
            stable = stable and os.fstat(fd).st_nlink == 1
            if not stable:
                raise RuntimeError("candidate output changed after promotion")
        finally:
            os.close(fd)
        return os.path.join(self.root, final_name)
