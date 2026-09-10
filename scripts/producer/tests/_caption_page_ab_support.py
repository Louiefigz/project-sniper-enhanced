"""Opt-in TEST A/B support: bounded real tool capture and immutable-file checks.

Nothing runs on import. This is not source/approval authority or production
fallback. The caller must authorize a source-stable local-media test window.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from headless.process_runner import ProcessRequest, run_text
from palmier.process_deadline import process_timeout

MAX_FILE_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class TestPageDeadline:
    """One monotonic allowance shared by hashes, both comparator legs and writes."""

    expires_at: float

    def remaining(self) -> float:
        """Reject expiry instead of manufacturing a fresh positive remainder."""
        value = self.expires_at - time.monotonic()
        if value <= 0:
            raise RuntimeError("TEST page A/B original deadline expired")
        return value


def file_observation(path: str, guard: Callable[[], object]) -> dict:
    """Hash one no-follow single-link regular file under the shared deadline."""
    guard()
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        result = _hash_descriptor(descriptor, path, guard)
    finally:
        os.close(descriptor)
    guard()
    return result


def _hash_descriptor(descriptor: int, path: str, guard: Callable[[], object]) -> dict:
    """Reject before/after aliases, size changes and growth during bounded reads."""
    before, digest = os.fstat(descriptor), hashlib.sha256()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
            or not 0 < before.st_size <= MAX_FILE_BYTES:
        raise RuntimeError("TEST A/B file is not bounded single-link regular media/code")
    remaining = before.st_size
    while remaining:
        guard()
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            raise RuntimeError("TEST A/B held file was truncated")
        remaining -= len(chunk)
        digest.update(chunk)
    after, named = os.fstat(descriptor), os.lstat(path)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
    if any(getattr(before, key) != getattr(after, key)
           or getattr(before, key) != getattr(named, key) for key in fields):
        raise RuntimeError("TEST A/B held file changed")
    return {"path": path, "sha256": digest.hexdigest(),
            **{key: getattr(before, key) for key in fields}}


def write_new(path: Path, data: bytes) -> None:
    """Retain private exact output bytes; never replace a prior result or input."""
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def write_json(path: Path, value: dict) -> None:
    """Keep floats intact in TEST evidence; this is not a production receipt."""
    write_new(path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def expected_json(path: str, held: dict, guard: Callable[[], object]) -> dict:
    """Read exact small held metadata, rejecting FIFO/symlink replacement before open."""
    guard()
    if held["st_size"] > 64 * 1024:
        raise RuntimeError("TEST expected metadata is too large")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        current = os.fstat(descriptor)
        if not stat.S_ISREG(current.st_mode) or current.st_size != held["st_size"]:
            raise RuntimeError("TEST expected metadata changed before read")
        raw = os.read(descriptor, 64 * 1024 + 1)
    finally:
        os.close(descriptor)
    if hashlib.sha256(raw).hexdigest() != held["sha256"]:
        raise RuntimeError("TEST expected metadata bytes changed")
    guard()
    return json.loads(raw)


class PageCommandRecorder:
    """Record exact argv/return/pipes/timing from the existing owned runner."""

    def __init__(self, root: Path, cwd: str, label: str) -> None:
        """Use only the harness's already-created new private output root."""
        self.root, self.cwd, self.label = root, cwd, label
        self.rows: list[dict] = []

    def old_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        """Bound old argv without changing its full-decode or parse semantics."""
        request = ProcessRequest(tuple(command), "", self.cwd, dict(os.environ),
                                 process_timeout(), max_output_bytes=16 * 1024 * 1024)
        return self(request)

    def __call__(self, request: ProcessRequest) -> subprocess.CompletedProcess[str]:
        """No exception becomes a valid proof; known pipe output is kept verbatim."""
        number, started = len(self.rows), time.monotonic()
        row = {"command": list(request.command), "timeoutSeconds": request.timeout_seconds}
        self.rows.append(row)
        try:
            result = run_text(request)
            row["returncode"] = result.returncode
            self._channels(number, result, request.pass_fds)
            return result
        except BaseException as error:
            row["error"] = {"type": type(error).__name__, "message": str(error)[:4000]}
            raise
        finally:
            row["elapsedMs"] = (time.monotonic() - started) * 1000
            write_json(self.root / f"{self.label}-{number:02d}.command.json", row)

    def _channels(self, number: int, result: subprocess.CompletedProcess[str],
                  descriptors: tuple[int, ...]) -> None:
        """Capture channels without changing the parent's inherited FD offset."""
        prefix = self.root / f"{self.label}-{number:02d}"
        write_new(Path(str(prefix) + ".stdout"), result.stdout.encode("utf8"))
        write_new(Path(str(prefix) + ".stderr"), result.stderr.encode("utf8"))
        if descriptors:
            raw = os.pread(descriptors[0], 64 * 1024 + 1, 0)
            write_new(Path(str(prefix) + ".progress"), raw)
