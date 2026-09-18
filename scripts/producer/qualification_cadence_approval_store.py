"""Crash-safe immutable storage for cadence-approval receipts."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ingest_admission_contract import canonical_bytes
from qualification_mezzanine_files import regular_directory


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("cadence approval write made no progress")
        offset += written


def _sync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) \
        | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_canonical(output: Path, document: dict) -> None:
    """Stage, fsync, and hard-link one complete receipt without overwrite."""
    regular_directory(output.parent, "cadence approval output directory")
    if output.suffix.lower() != ".json" or os.path.lexists(output):
        raise RuntimeError("cadence approval output must be one new JSON file")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{output.name}.", dir=output.parent)
    try:
        os.fchmod(descriptor, 0o400)
        _write_all(descriptor, canonical_bytes(document))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, output, follow_symlinks=False)
        _sync_directory(output.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.lexists(temporary):
            os.unlink(temporary)
            _sync_directory(output.parent)
