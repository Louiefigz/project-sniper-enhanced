"""Stable no-follow byte identity for scene media crossing into Palmier."""
from __future__ import annotations

import hashlib
import os
import stat


class SceneMediaError(RuntimeError):
    """Scene media is not one stable, owned, canonical regular file."""


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
        value.st_uid, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
    )


def _digest_descriptor(fd: int) -> tuple[str, os.stat_result]:
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb", closefd=False) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest(), os.fstat(handle.fileno())


def stable_scene_media_hash(path: object) -> tuple[str, str]:
    """Return canonical path/hash after one stable descriptor-bound read."""
    if not isinstance(path, str) or not os.path.isabs(path) \
            or os.path.normpath(path) != path or os.path.realpath(path) != path:
        raise SceneMediaError("scene media path must be canonical and absolute")
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise SceneMediaError("scene media could not be opened safely") from exc
    try:
        before = os.fstat(fd)
        valid = stat.S_ISREG(before.st_mode) and before.st_nlink == 1 \
            and before.st_uid == os.geteuid() and before.st_size > 0
        if not valid:
            raise SceneMediaError(
                "scene media must be one nonempty owned regular file")
        digest, after = _digest_descriptor(fd)
        if _identity(before) != _identity(after) \
                or _identity(after) != _identity(
                    os.stat(path, follow_symlinks=False)):
            raise SceneMediaError("scene media changed while being read")
    except OSError as exc:
        raise SceneMediaError("scene media identity could not be proved") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    return path, digest
