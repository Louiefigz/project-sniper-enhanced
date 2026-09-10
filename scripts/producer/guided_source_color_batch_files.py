"""Bounded batch control/code holds, never source hashing or execution authority.

The shared implementation verifier performs the required code-byte comparison.
This module retains the surrounding original file identities, including extra
declared inventory members, without hashing any source or code a second time.
"""
from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from color.deadline import require_time
from cut_preview_io import read_bytes
from guided_body_execution import _directory_states, _parent_paths
from guided_opening_inputs import hash_value
from headless.external_media_verification import snapshot_stat_identity
from headless.grade_launch_files import HeldLaunchFile, directory_identity, private_file_identity


@dataclass(frozen=True)
class _CodeFile:
    """Declared code identity around shared verification, not an independent hash proof."""

    path: Path
    identity: tuple


@dataclass(frozen=True)
class BatchCodeInventory:
    """Retain one original bounded code inventory without a cross-call cache."""

    files: tuple[_CodeFile, ...]
    parents: tuple[Path, ...]
    directories: tuple

    def assert_current(self, deadline: float) -> None:
        """Recheck all original files and shared ancestry under the caller's cutoff."""
        require_time(deadline)
        if _directory_states(self.parents) != self.directories:
            raise RuntimeError("source color batch implementation ancestry changed")
        for row in self.files:
            require_time(deadline)
            if snapshot_stat_identity(row.path.lstat()) != row.identity:
                raise RuntimeError("source color batch implementation file changed")
        if _directory_states(self.parents) != self.directories:
            raise RuntimeError("source color batch implementation ancestry changed")
        require_time(deadline)


def hold_batch_inventory(path: Path, expected: str, deadline: float) -> HeldLaunchFile:
    """Hold the exact bounded implementation document before shared verification."""
    require_time(deadline)
    hash_value(expected)
    parents, identity = directory_identity(path.parent), private_file_identity(path)
    raw = read_bytes(path, 16 * 1024 ** 2)
    result = HeldLaunchFile(path, raw, identity, parents)
    result.check()
    if result.sha256 != expected:
        raise RuntimeError("source color batch implementation inventory hash changed")
    require_time(deadline)
    return result


def _code_path(row: object) -> Path:
    """Reject duplicate/unsafe inventory spellings before filesystem work."""
    if type(row) is not dict or set(row) != {"path", "sha256"}:
        raise RuntimeError("source color batch implementation row is malformed")
    value = row["path"]
    hash_value(row["sha256"])
    if type(value) is not str or not 0 < len(value) <= 4096 or "\\" in value \
            or any(ord(char) < 32 for char in value) or str(Path(value)) != value \
            or Path(value).anchor != "/" or ".." in Path(value).parts:
        raise RuntimeError("source color batch implementation path is not canonical")
    return Path(value)


def hold_batch_code(inventory: HeldLaunchFile, deadline: float) -> BatchCodeInventory:
    """Capture only code stats before its one actual shared hash verification."""
    rows = inventory.value().get("files")
    if type(rows) is not list or not 1 <= len(rows) <= 4000:
        raise RuntimeError("source color batch implementation inventory is unbounded")
    paths = tuple(_code_path(row) for row in rows)
    if len(set(paths)) != len(paths):
        raise RuntimeError("source color batch implementation repeats a path")
    placeholders = tuple(_CodeFile(path, ()) for path in paths)
    parents = _parent_paths(placeholders)
    directories = _directory_states(parents)
    files, total = [], 0
    for path in paths:
        require_time(deadline)
        info = path.lstat()
        total += info.st_size
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= 64 * 1024 ** 2 \
                or total > 512 * 1024 ** 2:
            raise RuntimeError("source color batch implementation files exceed their bound")
        files.append(_CodeFile(path, snapshot_stat_identity(info)))
    result = BatchCodeInventory(tuple(files), parents, directories)
    result.assert_current(deadline)
    return result
