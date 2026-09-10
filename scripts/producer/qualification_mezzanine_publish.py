"""Descriptor-bound staging and publication for qualification media."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from qualification_mezzanine_files import FileFact


@dataclass(frozen=True)
class AttemptDirectory:
    """Private staging directory held beneath one stable parent descriptor."""

    path: Path
    name: str
    parent_fd: int
    device: int
    inode: int


@dataclass(frozen=True)
class PublishFile:
    """One exact staged inode and its final no-replace name."""

    stage_name: str
    final_name: str
    fact: FileFact


@dataclass(frozen=True)
class PublishedFile:
    """Identity of one final name created by this publication attempt."""

    name: str
    device: int
    inode: int


@dataclass(frozen=True)
class PublishedPair:
    """Exact final inodes owned by one completed two-link publication."""

    attempt: AttemptDirectory
    files: tuple[PublishedFile, ...]


def _directory_flags() -> int:
    return (os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0))


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _matches_fact(info: os.stat_result, fact: FileFact) -> bool:
    expected = (
        fact.device, fact.inode, fact.size_bytes, fact.mtime_ns, fact.ctime_ns)
    observed = (
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
        info.st_ctime_ns)
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1 \
        and observed == expected


def new_attempt(parent: Path) -> AttemptDirectory:
    """Create a 0700 staging directory through a stable parent descriptor."""
    parent_fd = os.open(parent, _directory_flags())
    created = False
    try:
        for _attempt in range(8):
            name = f".qualification-{uuid.uuid4().hex}"
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
                created = True
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeError("could not allocate qualification staging directory")
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        valid = (
            stat.S_ISDIR(info.st_mode)
            and not stat.S_ISLNK(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o700
        )
        if not valid:
            raise RuntimeError("qualification staging directory is unsafe")
        return AttemptDirectory(
            parent / name, name, parent_fd, info.st_dev, info.st_ino)
    except BaseException:
        try:
            if created:
                shutil.rmtree(name, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
        raise


def assert_attempt_path(attempt: AttemptDirectory) -> None:
    """Require the Docker-facing pathname to retain the created directory."""
    info = os.lstat(attempt.path)
    if (not stat.S_ISDIR(info.st_mode)
            or _identity(info) != (attempt.device, attempt.inode)):
        raise RuntimeError("qualification staging pathname changed")


def _attempt_fd(attempt: AttemptDirectory) -> int:
    descriptor = os.open(
        attempt.name, _directory_flags(), dir_fd=attempt.parent_fd)
    info = os.fstat(descriptor)
    if _identity(info) != (attempt.device, attempt.inode):
        os.close(descriptor)
        raise RuntimeError("qualification staging identity changed")
    return descriptor


def seal_stage_media(
    attempt: AttemptDirectory,
    name: str,
    fact: FileFact,
) -> FileFact:
    """Rebind and fsync the observed media through a no-follow descriptor."""
    stage_fd = _attempt_fd(attempt)
    descriptor = -1
    try:
        descriptor = os.open(
            name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=stage_fd)
        before = os.fstat(descriptor)
        if not _matches_fact(before, fact):
            raise RuntimeError("qualified output changed before sealing")
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        current = os.stat(name, dir_fd=stage_fd, follow_symlinks=False)
        stable = (
            stat.S_ISREG(after.st_mode)
            and stat.S_IMODE(after.st_mode) == 0o400
            and _identity(after) == _identity(before)
            and after.st_size == before.st_size
            and after.st_mtime_ns == before.st_mtime_ns
            and _identity(current) == _identity(after)
        )
        if not stable:
            raise RuntimeError("qualified output changed while sealing")
        return FileFact(
            str(attempt.path / name), fact.sha256, fact.size_bytes,
            after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(stage_fd)


def write_stage(
    attempt: AttemptDirectory,
    name: str,
    payload: bytes,
) -> FileFact:
    """Create, flush, and bind one read-only evidence stage file."""
    stage_fd = _attempt_fd(attempt)
    descriptor = -1
    try:
        descriptor = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0), 0o400, dir_fd=stage_fd)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RuntimeError("qualification evidence write stalled")
            view = view[written:]
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("qualification evidence stage is unsafe")
        return FileFact(
            str(attempt.path / name), hashlib.sha256(payload).hexdigest(),
            len(payload), info.st_dev, info.st_ino, info.st_mtime_ns,
            info.st_ctime_ns)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(stage_fd)


def _unlink_owned(attempt: AttemptDirectory, owned: PublishedFile) -> None:
    try:
        current = os.stat(
            owned.name, dir_fd=attempt.parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if _identity(current) != (owned.device, owned.inode):
        raise RuntimeError(
            f"refusing to unlink changed publication target: {owned.name}")
    os.unlink(owned.name, dir_fd=attempt.parent_fd)


def rollback_pair(publication: PublishedPair) -> None:
    """Remove only final names whose inodes this attempt created."""
    errors: list[BaseException] = []
    for owned in reversed(publication.files):
        try:
            _unlink_owned(publication.attempt, owned)
        except BaseException as exc:
            errors.append(exc)
    os.fsync(publication.attempt.parent_fd)
    if errors:
        raise RuntimeError("qualification publication rollback was incomplete") \
            from errors[0]


def _publish_pair(
    attempt: AttemptDirectory,
    files: tuple[PublishFile, ...],
) -> PublishedPair:
    if len(files) != 2 or len({item.final_name for item in files}) != 2:
        raise RuntimeError("qualification publication requires two distinct files")
    stage_fd = _attempt_fd(attempt)
    descriptors: list[int] = []
    created: list[PublishedFile] = []
    try:
        for item in files:
            if Path(item.final_name).name != item.final_name:
                raise RuntimeError("qualification final name is not confined")
            descriptor = os.open(
                item.stage_name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=stage_fd)
            descriptors.append(descriptor)
            source = os.fstat(descriptor)
            if not _matches_fact(source, item.fact):
                raise RuntimeError("qualification stage changed before publication")
            os.link(
                item.stage_name, item.final_name, src_dir_fd=stage_fd,
                dst_dir_fd=attempt.parent_fd, follow_symlinks=False)
            owned = PublishedFile(
                item.final_name, source.st_dev, source.st_ino)
            created.append(owned)
            final = os.stat(
                item.final_name, dir_fd=attempt.parent_fd,
                follow_symlinks=False)
            if _identity(final) != _identity(source):
                raise RuntimeError("qualification publication linked wrong inode")
        os.fsync(attempt.parent_fd)
        return PublishedPair(attempt, tuple(created))
    except BaseException:
        rollback_pair(PublishedPair(attempt, tuple(created)))
        raise
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
        os.close(stage_fd)


@contextmanager
def publication_transaction(
    attempt: AttemptDirectory,
    files: tuple[PublishFile, ...],
) -> Iterator[PublishedPair]:
    """Roll back exact created inodes on any exception, including cancellation."""
    publication = _publish_pair(attempt, files)
    try:
        yield publication
    except BaseException:
        rollback_pair(publication)
        raise


def cleanup_attempt(attempt: AttemptDirectory, strict: bool = True) -> None:
    """Remove only the staging directory created beneath the held parent."""
    try:
        info = os.stat(
            attempt.name, dir_fd=attempt.parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (not stat.S_ISDIR(info.st_mode)
            or _identity(info) != (attempt.device, attempt.inode)):
        if strict:
            raise RuntimeError("refusing to remove changed staging directory")
        return
    shutil.rmtree(attempt.name, dir_fd=attempt.parent_fd)
    os.fsync(attempt.parent_fd)


def close_attempt(attempt: AttemptDirectory) -> None:
    """Release the stable parent descriptor after cleanup/publication."""
    os.close(attempt.parent_fd)
