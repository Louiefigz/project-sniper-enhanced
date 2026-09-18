"""Bounded original staging metadata holds, never source or deletion authority.

Use the existing private metadata inode/ancestry and no-follow byte primitives.
Only sidecar/reservation get the additive8MiB class; original opening files keep
their128KiB class. No job file, source snapshot, executable or socket is read.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import read_bytes
from guided_opening_inputs import hash_value
from headless.grade_launch_files import HeldLaunchFile, directory_identity, private_file_identity


def staging_path(value: object) -> Path:
    """Validate exact caller paths lexically before following any directory entry."""
    if type(value) is not type(Path()) or value.anchor != "/" or ".." in value.parts \
            or "\\" in str(value) or any(ord(char) < 32 for char in str(value)):
        raise ValueError("source color staging requires exact canonical Path references")
    return value


@dataclass(frozen=True)
class StagingFileCapture:
    """Initial metadata identity captured before the first external callback."""

    path: Path
    identity: tuple
    parents: tuple


def capture_staging_file(path: Path) -> StagingFileCapture:
    """Capture an original named metadata inode without reading its bytes."""
    staging_path(path)
    parents = directory_identity(path.parent)
    value = StagingFileCapture(path, private_file_identity(path), parents)
    check_staging_file(value)
    return value


def check_staging_file(value: StagingFileCapture | HeldLaunchFile) -> None:
    """Recheck fixed original metadata, not a replacement method on the record."""
    if private_file_identity(value.path) != value.identity or directory_identity(value.path.parent) != value.parents:
        raise RuntimeError("source color original staging file or ancestry changed")


def staging_file_binding(value: StagingFileCapture | HeldLaunchFile) -> tuple:
    """Retain exact objects/stat tuples and immutable raw bytes without rehashing."""
    raw = (id(value.raw), value.raw) if type(value) is HeldLaunchFile else None
    return (id(value), type(value).__name__, str(value.path), value.identity, value.parents, raw)


def _pairs(value: list[tuple[str, object]]) -> dict:
    """Reject duplicate JSON fields rather than adopting a later value."""
    result = dict(value)
    if len(result) != len(value):
        raise ValueError("source color staging JSON repeats a field")
    return result


def read_staging_file(capture: StagingFileCapture, expected: str, maximum: int) -> tuple[HeldLaunchFile, dict]:
    """Read once against the initial capture and exact authenticated raw SHA."""
    hash_value(expected)
    if type(maximum) is not int or maximum not in (128 * 1024, 8 * 1024 ** 2):
        raise ValueError("source color staging raw byte class is unsupported")
    check_staging_file(capture)
    raw = read_bytes(capture.path, maximum)
    held = HeldLaunchFile(capture.path, raw, capture.identity, capture.parents)
    check_staging_file(held)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("source color staging raw bytes differ from original reference")
    value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs)
    if type(value) is not dict:
        raise ValueError("source color staging raw document is not an object")
    return held, value
