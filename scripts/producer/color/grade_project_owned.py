"""Internal typed grade-observation handoff, never a JSON execution capability.

The caller supplies its actual project/resource guard and original verified
source identity. Constructing these types does not acquire a lease, verify an
admission, declare known history, or qualify presenter rendering. No consumer
callback receives pending observations before immutable publication finishes.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import stat
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field, fields
from fractions import Fraction
from pathlib import Path

from color.deadline import require_time
from color.grade_contract import SourceBinding, parse_source_binding
from color.grade_observation_read import BoundGradeObservation
from color.grade_observation_geometry import SourceObservationMetadata
from color.grade_source_class import ObservedStream, SourceRecordValidation
from cross_runtime_canonical_json import canonical_compact_json
from cut_preview_io import file_hash, real_directory
from headless.external_media_verification import VerifiedSnapshotIdentity, snapshot_stat_identity


def _scalar(value: object) -> tuple:
    """Freeze small scalar metadata with exact types; never alias mutable records."""
    if type(value) in (str, int, float, bool, type(None)):
        return type(value), value
    if type(value) is Fraction:
        return Fraction, (type(value.numerator), value.numerator), (type(value.denominator), value.denominator)
    if type(value) is tuple and len(value) == 9 and all(type(part) is int for part in value):
        return tuple, tuple((int, part) for part in value)
    raise RuntimeError("owned grade contains unsupported typed metadata")


def _typed_fields(value: object, omit: tuple[str, ...] = ()) -> tuple:
    """Snapshot fixed dataclass metadata only, not raw probe/frame JSON or media."""
    return tuple((row.name, _scalar(getattr(value, row.name))) for row in fields(value) if row.name not in omit)


def observation_binding(observed: BoundGradeObservation) -> tuple:
    """Bind the actual returned object's identity and all small nested typed facts."""
    if type(observed) is not BoundGradeObservation or type(observed.records) is not SourceRecordValidation:
        raise RuntimeError("owned grade requires the actual returned BoundGradeObservation")
    records = observed.records
    if type(records.source) is not SourceBinding or type(records.stream) is not ObservedStream:
        raise RuntimeError("owned grade contains unsupported typed observation metadata")
    metadata = records.stream.source_metadata
    if metadata is not None and type(metadata) is not SourceObservationMetadata:
        raise RuntimeError("owned grade contains unsupported source metadata")
    return (id(observed), _typed_fields(observed, ("records",)), _typed_fields(records, ("source", "stream")),
            _typed_fields(records.source), _typed_fields(records.stream, ("source_metadata",)),
            None if metadata is None else _typed_fields(metadata))


def _assert_observation(observed: BoundGradeObservation, expected: tuple) -> None:
    """Reject post-reader/callback mutation without a raw-evidence replay."""
    if observation_binding(observed) != expected:
        raise RuntimeError("owned grade actual typed observation changed")


@dataclass(frozen=True)
class GradeProjectOwnedContext:
    """Borrow actual lifetime/source authority; do not create or renew either."""

    deadline: float
    guard: Callable[[], None]
    source: VerifiedSnapshotIdentity
    _binding: tuple = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate the original identity shape before any observation work."""
        if type(self.deadline) not in (int, float) or not math.isfinite(self.deadline) or not callable(self.guard):
            raise ValueError("owned grade requires an original deadline and live guard")
        source = self.source
        if type(source) is not VerifiedSnapshotIdentity or type(source.path) is not str \
                or type(source.sha256) is not str or re.fullmatch(r"[a-f0-9]{64}", source.sha256) is None \
                or type(source.size_bytes) is not int or source.size_bytes <= 0 \
                or type(source.stat_identity) is not tuple or len(source.stat_identity) != 9 \
                or any(type(item) is not int for item in source.stat_identity):
            raise ValueError("owned grade requires the original verified source identity")
        object.__setattr__(self, "_binding", self._current_binding())

    def _current_binding(self) -> tuple:
        """Retain exact scalar/source types as well as the original callback identity."""
        if type(self.source) is not VerifiedSnapshotIdentity:
            raise RuntimeError("owned grade original context changed")
        return type(self.deadline), self.deadline, id(self.guard), _typed_fields(self.source)

    def check(self) -> None:
        """Recheck original source stats under the caller's unchanged ownership guard."""
        original = self._binding
        if self._current_binding() != original:
            raise RuntimeError("owned grade original context changed")
        require_time(self.deadline)
        self.guard()
        if self._binding is not original or self._current_binding() != original:
            raise RuntimeError("owned grade original context changed during its guard")
        real_directory(Path(self.source.path).parent)
        current = os.lstat(self.source.path)
        if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or current.st_uid != os.geteuid() \
                or current.st_size != self.source.size_bytes or snapshot_stat_identity(current) != self.source.stat_identity:
            raise RuntimeError("owned grade original source identity changed")
        require_time(self.deadline)


@dataclass(frozen=True)
class _HeldFile:
    """A hash-verified artifact with its same-pass nine-field identity."""

    path: Path
    sha256: str
    identity: tuple[int, ...]


@dataclass(frozen=True)
class _PendingObservation:
    """Private pending value; never returned on failure or exposed by callback."""

    observation: BoundGradeObservation
    context: GradeProjectOwnedContext
    files: tuple[_HeldFile, ...]
    observation_binding: tuple


def _assert_held_files(files: tuple[_HeldFile, ...], deadline: float) -> None:
    """Keep the same bounded artifact identity sweep under the supplied held cutoff."""
    for row in files:
        require_time(deadline)
        real_directory(row.path.parent)
        if snapshot_stat_identity(row.path.lstat()) != row.identity:
            raise RuntimeError("owned grade held publication or evidence changed")


def _owned_reference_binding(value: OwnedProjectObservation) -> tuple:
    """Bind actual returned owner references and fixed-size identity metadata."""
    if type(value.context) is not GradeProjectOwnedContext or type(value.files) is not tuple \
            or not value.files or any(type(row) is not _HeldFile for row in value.files):
        raise RuntimeError("owned grade original returned owner references changed")
    context = value.context
    files = tuple((id(row), type(row.path), row.path, _scalar(row.sha256), _scalar(row.identity)) for row in value.files)
    return (id(value), id(value.observation), id(context), id(context.source), id(context.guard),
            id(context._binding), context._current_binding(), id(value.files), files,
            _scalar(value.deadline), id(value._observation_binding), value._observation_binding)


def _assert_owned_references(value: OwnedProjectObservation, original: tuple | None) -> None:
    """Only finish_owned's actual wrapper retains its construction-time authority."""
    if type(original) is not tuple or getattr(value, "_completion_origin", None) is not original \
            or _owned_reference_binding(value) != original:
        raise RuntimeError("owned grade original returned owner references changed")


@dataclass(frozen=True)
class OwnedProjectObservation:
    """Actual returned observation after publication; not grade/render approval."""

    observation: BoundGradeObservation
    context: GradeProjectOwnedContext
    files: tuple[_HeldFile, ...]
    deadline: float
    _observation_binding: tuple = field(repr=False)
    _completion_origin: tuple = field(init=False, repr=False, compare=False)

    def assert_current(self) -> None:
        """Keep the effective cap, source lifetime and held evidence unchanged."""
        require_time(self.deadline)
        _assert_observation(self.observation, self._observation_binding)
        original = getattr(self, "_completion_origin", None)
        _assert_owned_references(self, original)
        self.context.check()
        _assert_observation(self.observation, self._observation_binding)
        _assert_owned_references(self, original)
        _assert_held_files(self.files, self.deadline)
        require_time(self.deadline)
        _assert_observation(self.observation, self._observation_binding)
        _assert_owned_references(self, original)

    @property
    def result_path(self) -> Path:
        """The final entry is the exact newly published historical JSON result."""
        return self.files[-1].path

    @property
    def result_sha256(self) -> str:
        """Return the SHA of expected published bytes, not a later adopted hash."""
        return self.files[-1].sha256


class OwnedProjectObservationError(RuntimeError):
    """A failed project result never exposes its pending typed observation."""

    def __init__(self, result: dict) -> None:
        """Retain only the same bounded JSON diagnostics as the historical API."""
        super().__init__("owned project observation did not complete: " + str(result.get("errors", []))[:2000])
        self.result = deepcopy(result)


def _json_bytes(value: dict) -> bytes:
    """Match write_new's original exact canonical JSON transport."""
    return (canonical_compact_json(value) + "\n").encode("utf-8")


def _hold(path: Path, sha256: str, maximum: int) -> _HeldFile:
    """Hold exact already-declared bytes, never adopt a freshly discovered digest."""
    before = path.lstat()
    if type(sha256) is not str or re.fullmatch(r"[a-f0-9]{64}", sha256) is None \
            or file_hash(path, maximum) != sha256 or snapshot_stat_identity(path.lstat()) != snapshot_stat_identity(before):
        raise RuntimeError("owned grade evidence differs from its actual returned observation")
    return _HeldFile(path, sha256, snapshot_stat_identity(before))


def _observation(parts: tuple, context: GradeProjectOwnedContext) -> BoundGradeObservation:
    """Accept the actual reader type and exact source/parent/cleanup joins only."""
    observed, held, execution, _binding = parts
    if type(observed) is not BoundGradeObservation or type(observed.records) is not SourceRecordValidation:
        raise RuntimeError("owned grade requires the actual returned BoundGradeObservation")
    if type(held) is not dict or type(execution) is not dict or execution.get("status") != "complete" \
            or execution.get("cleanupVerified") is not True or observed.grade_applicable is not False \
            or observed.delivery_approved is not False:
        raise RuntimeError("owned grade observation lacks exact clean non-approval completion")
    binding = check_owned_source(held, context)
    if observed.records.source != binding \
            or any(execution.get(key) != context.source.sha256 for key in ("sourceBeforeSha256", "sourceAfterSha256")):
        raise RuntimeError("owned grade observation differs from original verified source or parents")
    return observed


def check_owned_source(held: dict, context: GradeProjectOwnedContext) -> SourceBinding:
    """Join the original hash-pass identity before any decoder can be launched."""
    context.check()
    binding = parse_source_binding(held["binding"])
    if held["sourcePath"] != context.source.path or binding.source_sha256 != context.source.sha256:
        raise RuntimeError("owned grade source differs from the initial verified identity")
    return binding


def _references(parts: tuple, directory: Path, result: dict) -> tuple[_HeldFile, ...]:
    """Recheck small parents and bounded raw evidence without redecoding source media."""
    observed, held, execution, _binding = parts
    producer = directory.parent.parent
    expected = held["expectedParents"]
    rows = [(producer / "edit_plan.json", expected["planSha256"], 2 * 1024 ** 2),
        (producer / "asset_manifest.json", expected["manifestSha256"], 2 * 1024 ** 2),
        (producer.parent / "project.json", expected["projectSha256"], 2 * 1024 ** 2),
        (directory / "input.json", result["inputSha256"], 128 * 1024),
        (directory / "parents.json", result["parentsSha256"], 16 * 1024 ** 2),
        (directory / "execution/execution.json", observed.execution_sha256, 16 * 1024 ** 2),
        (directory / "execution/result/probe.json", observed.raw_probe_sha256, 64 * 1024),
        (directory / "execution/result/frames.ffprobe", observed.raw_frames_sha256, 128 * 1024 ** 2)]
    if hashlib.sha256(_json_bytes(held)).hexdigest() != result["parentsSha256"] \
            or hashlib.sha256(_json_bytes(execution)).hexdigest() != observed.execution_sha256:
        raise RuntimeError("owned grade returned parent/execution bytes differ from retained evidence")
    return tuple(_hold(*row) for row in rows)


def retain_pending(parts: tuple, directory: Path, result: dict,
                   context: GradeProjectOwnedContext) -> _PendingObservation:
    """Keep validated real reader output private until final result publication."""
    _assert_observation(parts[0], parts[3])
    context.check()
    observed = _observation(parts, context)
    files = _references(parts, directory, result)
    context.check()
    _assert_observation(observed, parts[3])
    return _PendingObservation(observed, context, files, parts[3])


def finish_owned(pending: _PendingObservation, directory: Path, result: dict,
                 deadline: float) -> OwnedProjectObservation:
    """Publish no capability before the immutable report and all final checks pass."""
    require_time(deadline)
    if result.get("status") != "complete" or result.get("cleanupVerified") is not True:
        raise OwnedProjectObservationError(result)
    sha256 = hashlib.sha256(_json_bytes(result)).hexdigest()
    report = _hold(directory / "observation.json", sha256, 16 * 1024 ** 2)
    if stat.S_IMODE(report.identity[2]) != 0o400:
        raise RuntimeError("owned grade result publication is not immutable")
    owned = OwnedProjectObservation(pending.observation, pending.context, (*pending.files, report),
                                    deadline, pending.observation_binding)
    object.__setattr__(owned, "_completion_origin", _owned_reference_binding(owned))
    owned.assert_current()
    return owned
