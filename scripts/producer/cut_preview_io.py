"""Bounded, no-follow artifacts for private guided-cut previews."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import selectors
import subprocess
import time
from pathlib import Path

from cross_runtime_canonical_json import canonical_compact_json

MAX_JSON = 16 * 1024 * 1024
MAX_MEDIA = 2 * 1024 ** 3


def run_bounded(command: list[str], maximum: int = MAX_JSON, timeout: float = 900) -> subprocess.CompletedProcess:
    """Bound private child stdout/stderr while preserving the owned process group."""
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline, size = time.monotonic() + timeout, 0
    output = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ, "stdout")
            selector.register(child.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("cut preview child exceeded its command deadline")
                for key, _events in selector.select(min(remaining, 1)):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    size += len(data)
                    if size > maximum:
                        raise RuntimeError("cut preview child exceeded its output byte bound")
                    output[key.data].extend(data)
        code = child.wait(timeout=max(0.001, min(5, deadline - time.monotonic())))
        return subprocess.CompletedProcess(command, code, bytes(output["stdout"]), bytes(output["stderr"]))
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()


def digest(value: object) -> str:
    """Hash the shared cross-runtime canonical JSON representation."""
    return hashlib.sha256(canonical_compact_json(value).encode()).hexdigest()


def real_directory(path: Path) -> None:
    """Reject noncanonical or linked directory components."""
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise RuntimeError("cut preview directory must be canonical")
    for item in (path, *path.parents):
        info = item.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise RuntimeError("cut preview directory is unsafe")


def _identity(info: os.stat_result) -> tuple:
    """Fields that must stay fixed for one exact read."""
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_nlink)


def read_bytes(path: Path, maximum: int = MAX_JSON) -> bytes:
    """Read bounded bytes from one unchanged regular no-follow file."""
    real_directory(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
                or not 0 < before.st_size <= maximum:
            raise RuntimeError("cut preview artifact is not a bounded regular file")
        chunks, remaining = [], before.st_size
        while remaining:
            data = os.read(descriptor, min(remaining, 1024 * 1024))
            if not data:
                raise RuntimeError("cut preview artifact truncated during read")
            chunks.append(data)
            remaining -= len(data)
        if _identity(before) != _identity(os.fstat(descriptor)) \
                or _identity(before) != _identity(path.lstat()):
            raise RuntimeError("cut preview artifact changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def file_hash(path: Path, maximum: int = MAX_MEDIA) -> str:
    """Stream a bounded artifact hash while retaining inode identity."""
    real_directory(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
                or not 0 < before.st_size <= maximum:
            raise RuntimeError("cut preview hash input is unsafe or over budget")
        result, remaining = hashlib.sha256(), before.st_size
        while remaining:
            data = os.read(descriptor, min(remaining, 1024 * 1024))
            if not data:
                raise RuntimeError("cut preview hash input was truncated")
            result.update(data)
            remaining -= len(data)
        if _identity(before) != _identity(os.fstat(descriptor)) \
                or _identity(before) != _identity(path.lstat()):
            raise RuntimeError("cut preview hash input changed")
        return result.hexdigest()
    finally:
        os.close(descriptor)


def bound_json(path: Path, expected: str | None = None) -> dict:
    """Parse the same exact UTF-8 bytes whose digest was checked."""
    raw = read_bytes(path)
    if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("cut preview input hash changed")
    value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict:
        raise RuntimeError("cut preview input must be an object")
    return value


def write_new(path: Path, value: dict) -> None:
    """Publish only a new file; never overwrite even failed prior work."""
    real_directory(path.parent)
    raw = (canonical_compact_json(value) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)
