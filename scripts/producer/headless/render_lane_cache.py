"""Attempt-owned cache binding for the dedicated headless render lane."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass

_OWNER_NAME = ".owner.json"
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}")


class CacheOwnershipError(RuntimeError):
    """A cache path or owner receipt is unsafe or belongs to another attempt."""


@dataclass(frozen=True)
class CacheBinding:
    """Validated directories and identity receipt for one attempt cache."""

    cache_dir: str
    temp_dir: str
    receipt_sha256: str
    cache_device: int
    cache_inode: int


def _canonical(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                       sort_keys=True) + "\n").encode("ascii")


def _open_private_dir(path: str) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise CacheOwnershipError(f"cannot safely open private directory: {path}") from exc
    info = os.fstat(fd)
    safe = (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700)
    if safe:
        return fd
    os.close(fd)
    raise CacheOwnershipError("attempt cache directories must be owned mode 0700")


def _private_child(parent_fd: int, name: str) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        os.chmod(name, 0o700, dir_fd=parent_fd, follow_symlinks=False)
    except FileExistsError:
        pass
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise CacheOwnershipError(f"cannot safely open attempt child: {name}") from exc
    info = os.fstat(fd)
    safe = (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700)
    if safe:
        return fd
    os.close(fd)
    raise CacheOwnershipError(f"attempt child {name} must be owned mode 0700")


def _expected_receipt(identity: tuple[str, str, str, str],
                      info: os.stat_result) -> dict:
    attempt_id, request_digest, build_digest, image_id = identity
    if not _IDENTITY.fullmatch(attempt_id):
        raise CacheOwnershipError("attempt ID is invalid")
    if not _DIGEST.fullmatch(request_digest) or not _DIGEST.fullmatch(build_digest):
        raise CacheOwnershipError("request and build digests must be lowercase SHA-256")
    if not _IMAGE.fullmatch(image_id):
        raise CacheOwnershipError("renderer image ID is invalid")
    return {
        "attemptId": attempt_id,
        "buildDigest": build_digest,
        "cacheDevice": info.st_dev,
        "cacheInode": info.st_ino,
        "imageId": image_id,
        "requestDigest": request_digest,
        "schemaVersion": 1,
    }


def _write_all(fd: int, encoded: bytes) -> None:
    view = memoryview(encoded)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise CacheOwnershipError("short cache-owner receipt write")
        view = view[written:]


def _bind_receipt(cache_fd: int, expected: dict) -> str:
    encoded = _canonical(expected)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(_OWNER_NAME, flags, 0o600, dir_fd=cache_fd)
    except FileExistsError:
        return _verify_receipt(cache_fd, expected)
    try:
        os.fchmod(fd, 0o600)
        info = os.fstat(fd)
        safe = (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600)
        if not safe:
            raise CacheOwnershipError("new cache-owner receipt is unsafe")
        _write_all(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(cache_fd)
    return _verify_receipt(cache_fd, expected)


def _open_receipt(cache_fd: int) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(_OWNER_NAME, flags, dir_fd=cache_fd)
    except OSError as exc:
        raise CacheOwnershipError("cannot safely read cache-owner receipt") from exc


def _read_bounded(fd: int) -> bytes:
    chunks, remaining = [], 16_385
    while remaining:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_receipt(cache_fd: int) -> bytes:
    fd = _open_receipt(cache_fd)
    try:
        info = os.fstat(fd)
        raw = _read_bounded(fd)
    finally:
        os.close(fd)
    safe = (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600 and len(raw) <= 16_384)
    if not safe:
        raise CacheOwnershipError("cache-owner receipt is unsafe")
    return raw


def _verify_receipt(cache_fd: int, expected: dict) -> str:
    raw = _read_receipt(cache_fd)
    if raw != _canonical(expected):
        raise CacheOwnershipError("cache-owner receipt does not match this attempt")
    return hashlib.sha256(raw).hexdigest()


def assert_cache_binding(cache_fd: int, binding: CacheBinding) -> None:
    """Bind one held cache directory to its original inode and owner receipt."""
    info = os.fstat(cache_fd)
    safe = (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700)
    if not safe or (info.st_dev, info.st_ino) != (
            binding.cache_device, binding.cache_inode):
        raise CacheOwnershipError("cache directory identity changed")
    receipt = hashlib.sha256(_read_receipt(cache_fd)).hexdigest()
    if receipt != binding.receipt_sha256:
        raise CacheOwnershipError("cache owner receipt identity changed")


def _close_all(fds: tuple[int | None, ...]) -> None:
    for fd in fds:
        if fd is not None:
            os.close(fd)


def prepare_attempt_cache(attempt_root: str, identity: tuple[str, str, str, str]
                          ) -> CacheBinding:
    """Create or revalidate `<attempt>/work/graphics-cache` and its owner."""
    root = os.path.abspath(attempt_root)
    if root != attempt_root or os.path.realpath(root) != root:
        raise CacheOwnershipError("attempt root must be canonical and symlink-free")
    root_fd = _open_private_dir(root)
    work_fd = cache_fd = temp_fd = None
    try:
        work_fd = _private_child(root_fd, "work")
        cache_fd = _private_child(work_fd, "graphics-cache")
        temp_fd = _private_child(work_fd, "tmp")
        info = os.fstat(cache_fd)
        expected = _expected_receipt(identity, info)
        receipt = _bind_receipt(cache_fd, expected)
    finally:
        _close_all((temp_fd, cache_fd, work_fd, root_fd))
    return CacheBinding(
        os.path.join(root, "work", "graphics-cache"),
        os.path.join(root, "work", "tmp"), receipt, info.st_dev, info.st_ino)
