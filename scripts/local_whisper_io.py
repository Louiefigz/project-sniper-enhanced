"""Bound local Whisper child groups and retained JSON/provenance reads.

All work consumes the caller's already-started local-ASR clock. The existing
runner reaps each leaf group; outer-owner hard-kill recovery is a separate scope.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from typing import BinaryIO

from local_asr_deadline import (
    LocalAsrDeadline, LocalAsrDeadlineError, LocalWhisperError,
    current_local_asr_deadline,
)
from local_asr_worker import run_local_asr_leaf
from producer.headless.process_runner import ProcessDeadlineError, ProcessRequest

MAX_TOOL_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_WHISPER_JSON_BYTES = 64 * 1024 * 1024
READ_BYTES = 1024 * 1024
_IDENTITY = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")


def run_local_tool(command: list[str]) -> subprocess.CompletedProcess:
    """Use the existing owned-group runner with decreasing time and bounded pipes."""
    deadline = current_local_asr_deadline()
    executable = shutil.which(command[0])
    if executable is None:
        raise LocalWhisperError(f"local ASR executable not found: {command[0]}")
    request = ProcessRequest(
        command=(os.path.abspath(executable), *command[1:]), stdin_text="",
        cwd=os.getcwd(), environment=dict(os.environ),
        timeout_seconds=min(3600.0, deadline.remaining()),
        max_output_bytes=MAX_TOOL_OUTPUT_BYTES)
    try:
        result = run_local_asr_leaf(request)
    except ProcessDeadlineError as exc:
        raise LocalAsrDeadlineError("local ASR aggregate work deadline exceeded") from exc
    except (OSError, RuntimeError, UnicodeError) as exc:
        raise LocalWhisperError(f"local ASR owned subprocess failed: {exc}") from exc
    deadline.guard()
    return result


def _hash_stream(stream: BinaryIO, deadline: LocalAsrDeadline) -> str:
    """Check before and after each bounded read, including the EOF observation."""
    digest = hashlib.sha256()
    while True:
        deadline.guard()
        chunk = stream.read(READ_BYTES)
        deadline.guard()
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def hash_provenance(path: str) -> str:
    """Retain exact full-byte hashes and before/after mutation detection."""
    deadline = current_local_asr_deadline()
    resolved = Path(path).resolve()
    before = resolved.stat()
    if not resolved.is_file():
        raise LocalWhisperError(f"provenance input is not a file: {resolved}")
    with resolved.open("rb") as stream:
        result = _hash_stream(stream, deadline)
    after = resolved.stat()
    deadline.guard()
    if any(getattr(before, key) != getattr(after, key) for key in _IDENTITY):
        raise LocalWhisperError(f"provenance input changed while hashing: {resolved}")
    return result


def _json_bytes(stream: BinaryIO, deadline: LocalAsrDeadline) -> bytes:
    """Bound allocation without truncating a large result into valid evidence."""
    result = bytearray()
    while True:
        deadline.guard()
        chunk = stream.read(READ_BYTES)
        deadline.guard()
        if not chunk:
            return bytes(result)
        if len(result) + len(chunk) > MAX_WHISPER_JSON_BYTES:
            raise LocalWhisperError("local Whisper JSON exceeds its 64 MiB byte bound")
        result.extend(chunk)


def read_whisper_json(path: Path) -> dict:
    """Read a complete bounded regular-file result and reject late parsing success."""
    deadline = current_local_asr_deadline()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_WHISPER_JSON_BYTES:
            raise LocalWhisperError("local Whisper JSON must be a nonempty regular file within 64 MiB")
        payload = _json_bytes(stream, deadline)
        after = os.fstat(stream.fileno())
    if any(getattr(before, key) != getattr(after, key) for key in _IDENTITY):
        raise LocalWhisperError("local Whisper JSON changed while reading")
    deadline.guard()
    result = json.loads(payload)
    deadline.guard()
    if not isinstance(result, dict):
        raise LocalWhisperError("local Whisper JSON must be an object")
    return result
