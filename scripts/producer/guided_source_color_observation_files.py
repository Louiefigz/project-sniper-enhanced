"""Original cold metadata lifetimes, not source, process or cleanup authority.

All paths are selected by the closed caller/staging contracts before the first
external callback. Metadata bytes are bounded and read once; original source
identities are only stat-checked. No clock, lease or live observation is made.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from color.deadline import require_time
from cut_preview_io import read_bytes
from guided_opening_inputs import OpeningInputs
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_preparation import _snapshots
from guided_source_color_staging_contract import _hash, _path
from guided_source_color_staging_files import _pairs
from headless.external_media_verification import (
    SourceVerificationRuntime, assert_verified_snapshots, snapshot_stat_identity,
)
from headless.grade_launch_files import directory_identity


@dataclass(frozen=True)
class ColdSourceColorObservationContext:
    """Borrow authenticated original metadata and the caller's SAME read cutoff."""

    inputs: OpeningInputs
    references: dict
    deadline: float
    guard: Callable[[], None]


def _context(value: ColdSourceColorObservationContext) -> tuple:
    """Capture typed original references before any reader or arbitrary callback."""
    if type(value) is not ColdSourceColorObservationContext or type(value.inputs) is not OpeningInputs \
            or type(value.references) is not dict or not callable(value.guard) \
            or type(value.deadline) not in (int, float) or not math.isfinite(value.deadline):
        raise ValueError("cold source color requires its original read context")
    inputs = value.inputs
    if type(inputs.path) is not type(Path()):
        raise ValueError("cold source color original input path type changed")
    return (id(value), id(inputs), id(value.references), value.references, id(value.guard), value.deadline,
            tuple((key, id(row)) for key, row in value.references.items()),
            tuple((key, id(row)) for key, row in value.references.get("implementation", {}).items()),
            str(inputs.path), inputs.sha256, id(inputs.value), inputs.value, id(inputs.documents), inputs.documents,
            id(inputs.verified_media), inputs.verified_media.entries_json, _snapshots(inputs.verified_media))


def _identity(path: Path) -> tuple:
    """Permit private records and pinned code, never aliases or special files."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
        raise RuntimeError("cold source color metadata is not an owned single-link regular file")
    return snapshot_stat_identity(info)


@dataclass(frozen=True)
class _File:
    """Initial inode/ancestry and byte ceiling, never a later claimed-hash baseline."""

    path: Path
    identity: tuple
    parents: tuple
    maximum: int


def check_observation_file(value: _File) -> None:
    """Compare original stat fields and all ancestors without rereading bytes."""
    if _identity(value.path) != value.identity or directory_identity(value.path.parent) != value.parents:
        raise RuntimeError("cold source color original metadata file or parent changed")


class ColdObservationRead:
    """Private finite read lifetime; no object from this class escapes the reader."""

    def __init__(self, section: dict, context: ColdSourceColorObservationContext) -> None:
        """Hold originals before IO; admission remains deferred until every path is held."""
        self.original = hold_read_metadata((_context(context), id(section), section))
        self.context, self.section = context, section
        self.deadline, self.callback = context.deadline, context.guard
        require_time(self.deadline)
        self.files: dict[str, _File] = {}
        self.loaded: list[tuple[object, object]] = []
        self.armed, self.busy = False, False
        self.source_parents = tuple(directory_identity(Path(row.path).parent)
                                    for row in context.inputs.verified_media.snapshots)
        self.runtime = SourceVerificationRuntime(lambda: require_time(self.deadline))
        self.metadata()

    def retain(self, value: object) -> object:
        """Capture an actual returned parser value before another helper/callback sees it."""
        self.loaded.append((value, hold_read_metadata(value)))
        return value

    def capture(self, path: Path, maximum: int) -> None:
        """All selected files must be captured before the first arbitrary callback."""
        if self.armed or str(_path(str(path))) != str(path):
            raise RuntimeError("cold source color cannot rebaseline a late file")
        require_time(self.deadline)
        row = _File(path, _identity(path), directory_identity(path.parent), maximum)
        if not 0 < row.identity[6] <= maximum:
            raise RuntimeError("cold source color metadata exceeds its original byte class")
        previous = self.files.get(str(path))
        if previous is not None and previous != row:
            raise RuntimeError("cold source color has conflicting file roles")
        self.files[str(path)] = row
        check_observation_file(row)
        require_time(self.deadline)

    def raw(self, reference: dict) -> bytes:
        """Hash one bounded metadata buffer against its independently supplied raw SHA."""
        self.metadata()
        row = self.files[reference["path"]]
        raw = read_bytes(row.path, row.maximum)
        check_observation_file(row)
        if hashlib.sha256(raw).hexdigest() != _hash(reference["sha256"]) \
                or type(reference["sizeBytes"]) is not int or len(raw) != reference["sizeBytes"]:
            raise RuntimeError("cold source color original raw reference differs")
        self.metadata()
        return raw

    def load(self, reference: dict) -> dict:
        """Reject duplicate/nonfinite JSON; retain the actual parsed return immediately."""
        raw = self.raw(reference)
        value = json.loads(raw.decode("utf8", errors="strict"), object_pairs_hook=_pairs)
        if type(value) is not dict:
            raise ValueError("cold source color metadata must be an object")
        self.retain(value)
        self.metadata()
        return value

    def unchanged(self) -> None:
        """Compare exact initial and parsed values without adopting any later baseline."""
        if not same_read_metadata((_context(self.context), id(self.section), self.section), self.original) \
                or any(not same_read_metadata(value, fixed) for value, fixed in self.loaded):
            raise RuntimeError("cold source color original context or parsed metadata changed")

    def metadata(self) -> None:
        """Final callback-free metadata/stat/source sweep ends on the original cutoff."""
        self.unchanged()
        require_time(self.deadline)
        for row in self.files.values():
            check_observation_file(row)
        snapshots = self.context.inputs.verified_media.snapshots
        assert_verified_snapshots(snapshots, self.runtime)
        if tuple(directory_identity(Path(row.path).parent) for row in snapshots) != self.source_parents:
            raise RuntimeError("cold source color original source ancestry changed")
        self.unchanged()
        require_time(self.deadline)

    def check(self) -> None:
        """Reuse only the caller's original guard, never recursive admission or a new timer."""
        if self.busy:
            raise RuntimeError("cold source color read callback reentered its lifetime")
        self.armed, self.busy = True, True
        try:
            self.metadata()
            self.callback()
            self.metadata()
        finally:
            self.busy = False
