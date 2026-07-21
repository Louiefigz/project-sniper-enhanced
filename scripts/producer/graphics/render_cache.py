"""Locked, proof-before-authority cache materialization for graphics."""
from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from headless.container_io import promote_regular


@dataclass(frozen=True)
class CacheRequest:
    """Stable location and extension for one content-addressed render."""

    directory: str
    key: str
    extension: str


def _lock_fd(path: str) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        fd = os.open(path, flags | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        fd = os.open(path, flags & ~os.O_CREAT, 0o600)
    if created:
        os.fchmod(fd, 0o600)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        os.close(fd)
        raise RuntimeError("render cache lock is not one user-owned regular file")
    return fd


@contextmanager
def _key_lock(path: str) -> Iterator[None]:
    fd = _lock_fd(path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def _private_stage(prefix: str, directory: str) -> Iterator[str]:
    with tempfile.TemporaryDirectory(prefix=prefix, dir=directory) as stage:
        os.chmod(stage, 0o700)
        yield stage


def _quarantine(path: str) -> None:
    suffix = f".rejected-{uuid.uuid4().hex}"
    for candidate in (path, path + ".proof.json", path + ".runtime.json",
                      path + ".input.tar"):
        if os.path.lexists(candidate):
            os.replace(candidate, candidate + suffix)


def _digest_fd(fd: int) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def _regular_digest(path: str) -> tuple[str, tuple[int, int, int, int]]:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.geteuid() or before.st_size <= 0):
            raise RuntimeError("cached render is not one user-owned regular file")
        digest = _digest_fd(fd)
        after = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns)
        if identity != (after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns):
            raise RuntimeError("cached render changed while hashing")
        return digest, identity
    finally:
        os.close(fd)


def _proved_hit(output: str, prove: Callable[[str], dict]) -> dict:
    digest, identity = _regular_digest(output)
    with _private_stage(
            ".cache-hit-proof-", os.path.dirname(output)) as stage:
        snapshot = os.path.join(stage, os.path.basename(output))
        promote_regular(output, snapshot, digest)
        runtime = output + ".runtime.json"
        if os.path.lexists(runtime):
            promote_regular(runtime, snapshot + ".runtime.json")
        archive = output + ".input.tar"
        if os.path.lexists(archive):
            promote_regular(archive, snapshot + ".input.tar")
        proof = prove(snapshot)
        if proof.get("asset", {}).get("sha256") != digest:
            raise RuntimeError("cache-hit proof is not bound to cached media")
        after_digest, after_identity = _regular_digest(output)
        if (digest, identity) != (after_digest, after_identity):
            raise RuntimeError("cached render changed during proof")
        sidecar = output + ".proof.json"
        if os.path.lexists(sidecar):
            os.replace(sidecar, sidecar + f".rejected-{uuid.uuid4().hex}")
        promote_regular(proof["sidecar"], sidecar)
        proof["sidecar"] = sidecar
        return proof


def _promote(candidate: str, output: str, proof: dict) -> dict:
    sidecar = proof.get("sidecar")
    if sidecar != candidate + ".proof.json":
        raise RuntimeError("render proof did not produce the candidate sidecar")
    expected = proof.get("asset", {}).get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise RuntimeError("render proof has no exact media digest")
    promoted = False
    try:
        promote_regular(candidate, output, expected)
        promoted = True
        if "runtimeAttestation" in proof:
            promote_regular(candidate + ".runtime.json",
                            output + ".runtime.json")
            promote_regular(candidate + ".input.tar", output + ".input.tar")
        promote_regular(sidecar, output + ".proof.json")
    except Exception:
        if promoted:
            _quarantine(output)
        raise
    proof["sidecar"] = output + ".proof.json"
    return proof


def _existing_hit(output: str, prove: Callable[[str], dict]) -> dict | None:
    if not os.path.lexists(output):
        return None
    try:
        return _proved_hit(output, prove)
    except (OSError, RuntimeError, ValueError):
        _quarantine(output)
        return None


def _render_miss(request: CacheRequest, output: str,
                 render: Callable[[str], None],
                 prove: Callable[[str], dict]) -> tuple[str, bool, dict]:
    with _private_stage(
            f".{request.key}.candidate-", request.directory) as stage:
        candidate = os.path.join(stage, f"render.{request.extension}")
        render(candidate)
        proof = prove(candidate)
        return output, False, _promote(candidate, output, proof)


def materialize(request: CacheRequest, render: Callable[[str], None],
                prove: Callable[[str], dict]) -> tuple[str, bool, dict]:
    """Return a proved hit or serialize one proved cache-miss promotion."""
    os.makedirs(request.directory, exist_ok=True)
    output = os.path.join(request.directory,
                          f"{request.key}.{request.extension}")
    lock = os.path.join(request.directory, f".{request.key}.lock")
    with _key_lock(lock):
        hit = _existing_hit(output, prove)
        if hit is not None:
            return output, True, hit
        return _render_miss(request, output, render, prove)
