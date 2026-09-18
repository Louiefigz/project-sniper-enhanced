"""Opt-in read of original completed V1 metadata, not source/render authority.

Only the actual live-sealed completed object supplies the original file holds,
source identity, persistent guard and OVERALL deadline. Four bounded metadata
artifacts are replayed once; source media is never opened or hashed. Later
checks retain that same lifetime without another metadata replay. Types and
hashes alone authenticate nothing: callers must supply the actual owned result.
Legacy observations/receipts and all public execution gates remain unchanged.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field, fields

from color.deadline import require_time
from color.grade_bt709_identity import Bt709IdentityMetadata, validate_bt709_identity_records
from color.grade_contract import SourceBinding
from color.grade_observation_profile import V1
from color.grade_observation_read import _lines
from color.grade_project_completion import (
    CompletedProjectObservation, _binding as completed_binding, _unchanged as completed_unchanged,
)
from color.grade_project_owned import _HeldFile, _assert_held_files, _typed_fields, observation_binding
from color.grade_source_class import ObservedStream, SourceRecordValidation
from cut_preview_io import read_bytes
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata


def _completed(value: CompletedProjectObservation) -> tuple:
    """Capture original completed/guard/deadline/file identities before any callback."""
    if type(value) is not CompletedProjectObservation:
        raise ValueError("BT709 identity read requires the actual live-sealed completed observation")
    if set(vars(value)) != {row.name for row in fields(value)} \
            or set(vars(value.context)) != {row.name for row in fields(value.context)}:
        raise RuntimeError("BT709 identity original completed methods or fields changed")
    completed_unchanged(value, value._binding)
    bound = value.observation
    if bound.records.validator_policy != "sniper-private-grade-frame-records-v2" \
            or bound.records.stream.source_metadata is not None:
        raise ValueError("BT709 identity read cannot relabel V2 observation metadata")
    return completed_binding(value), observation_binding(bound)


def _files(value: CompletedProjectObservation) -> tuple[_HeldFile, ...]:
    """Choose four exact original held paths, never discover new files or adopt hashes."""
    job, observed = value.result_path.parent, value.observation
    expected = ((job / "parents.json", None), (job / "execution/execution.json", observed.execution_sha256),
                (job / "execution/result/probe.json", observed.raw_probe_sha256),
                (job / "execution/result/frames.ffprobe", observed.raw_frames_sha256))
    result = []
    for path, sha in expected:
        matches = [row for row in value.files if row.path == path]
        if len(matches) != 1 or type(matches[0]) is not _HeldFile or (sha is not None and matches[0].sha256 != sha):
            raise RuntimeError("BT709 identity original metadata file/hash binding differs")
        result.append(matches[0])
    return tuple(result)


class _IdentityRead:
    """One original-lifetime metadata replay with final callback-independent checks."""

    def __init__(self, completed: CompletedProjectObservation) -> None:
        """Hold originals before any guard, stat sweep, byte reader or parser."""
        self.original = _completed(completed)
        self.completed, self.files = completed, _files(completed)
        self.deadline = completed.context.deadline
        self.fixed = (id(self.files), tuple(id(row) for row in self.files), type(self.deadline), self.deadline)
        self.loaded: list[tuple[dict, object]] = []

    def unchanged(self) -> None:
        """Do not invoke replaceable instance binding methods or rebaseline metadata."""
        if _completed(self.completed) != self.original or _files(self.completed) != self.files \
                or (id(self.files), tuple(id(row) for row in self.files), type(self.deadline), self.deadline) != self.fixed:
            raise RuntimeError("BT709 identity original completed metadata or cutoff changed")
        if any(not same_read_metadata(value, held) for value, held in self.loaded):
            raise RuntimeError("BT709 identity actual parsed metadata changed")
        require_time(self.deadline)

    def check(self) -> None:
        """Reuse the same persistent guard and overall cutoff, not the old grade phase."""
        _IdentityRead.unchanged(self)
        CompletedProjectObservation.assert_current(self.completed)
        _IdentityRead.unchanged(self)
        _assert_held_files(self.files, self.deadline)
        _IdentityRead.unchanged(self)

    def load(self, index: int) -> dict:
        """Hash/parse exactly one bounded original metadata buffer, never read it twice."""
        _IdentityRead.check(self)
        row, maximum = self.files[index], 64 * 1024 if index == 2 else 16 * 1024 ** 2
        raw = read_bytes(row.path, maximum)
        _IdentityRead.unchanged(self)
        if len(raw) != row.identity[6] or hashlib.sha256(raw).hexdigest() != row.sha256:
            raise RuntimeError("BT709 identity raw metadata differs from original held bytes")
        value = json.loads(raw)
        if type(value) is not dict:
            raise ValueError("BT709 identity original metadata must be an object")
        self.loaded.append((value, hold_read_metadata(value)))
        _IdentityRead.unchanged(self)
        return value


def _records(value: SourceRecordValidation) -> tuple:
    """Compare exact typed V1 scalars; dataclass equality can coerce int/float/bool."""
    if type(value) is not SourceRecordValidation or type(value.source) is not SourceBinding \
            or type(value.stream) is not ObservedStream or value.stream.source_metadata is not None:
        raise RuntimeError("BT709 identity replay has a different typed V1 record class")
    return (_typed_fields(value, ("source", "stream")), _typed_fields(value.source), _typed_fields(value.stream))


def _replay(read: _IdentityRead) -> Bt709IdentityMetadata:
    """Use held original raw evidence and require the same legacy normalized hash."""
    parents, execution, probe = (read.load(index) for index in range(3))
    worker = execution.get("worker", {})
    if type(execution.get("schemaVersion")) is not int or execution["schemaVersion"] != 1 \
            or execution.get("policy") != V1.policy or type(worker) is not dict \
            or "profile" in execution or "profile" in worker:
        raise ValueError("BT709 identity read requires the original exact V1 execution class")
    row = read.files[3]
    lines = _lines(row.path, {"sha256": row.sha256, "bytes": row.identity[6]})

    def timed_lines() -> Iterator[str]:
        """Check the original cutoff per bounded line, without per-line external guards."""
        for line in lines:
            require_time(read.deadline)
            yield line

    try:
        result = validate_bt709_identity_records((parents["binding"], parents["declaration"], probe),
                                                 timed_lines(), worker["decoder"])
    finally:
        lines.close()
    _IdentityRead.unchanged(read)
    if _records(result.records) != _records(read.completed.observation.records):
        raise RuntimeError("BT709 identity replay differs from actual original normalized observation")
    return result.metadata


def _binding(value: HeldBt709IdentityObservation) -> tuple:
    """Bind all exposed data/flags and original lifetime before and after callbacks."""
    if type(value._read) is not _IdentityRead or type(value.metadata) is not Bt709IdentityMetadata:
        raise RuntimeError("BT709 identity held evidence type changed")
    return (id(value), id(value.completed), id(value._read), id(value._read.original), value._read.original,
            id(value.metadata), _typed_fields(value.metadata),
            _typed_fields(value, ("completed", "metadata", "_read", "_origin")))


@dataclass(frozen=True, init=False)
class HeldBt709IdentityObservation:
    """Actual metadata-read evidence only; no new work, source admission or approval."""

    completed: CompletedProjectObservation
    metadata: Bt709IdentityMetadata
    executable: bool = field(default=False, init=False)
    gamut_measured: bool = field(default=False, init=False)
    grade_applicable: bool = field(default=False, init=False)
    base_render_applicable: bool = field(default=False, init=False)
    delivery_approved: bool = field(default=False, init=False)
    _read: _IdentityRead = field(repr=False)
    _origin: tuple = field(repr=False)

    def __init__(self) -> None:
        """JSON or a public constructor cannot manufacture an actual held read."""
        raise TypeError("BT709 identity evidence requires read_bt709_identity_observation")

    def assert_current(self) -> None:
        """Recheck original lifetime and small evidence only; never replay metadata again."""
        original = self._origin
        _unchanged(self, original)
        _IdentityRead.check(self._read)
        _unchanged(self, original)
        require_time(self._read.deadline)


def _unchanged(value: HeldBt709IdentityObservation, original: tuple) -> None:
    """Do not let final callbacks replace values, origin, original reader or approvals."""
    if value._origin is not original or _binding(value) != original or value.completed is not value._read.completed:
        raise RuntimeError("BT709 identity original held evidence changed")


def read_bt709_identity_observation(completed: CompletedProjectObservation) -> HeldBt709IdentityObservation:
    """Replay authenticated original metadata once without extending its caller lifetime."""
    read = _IdentityRead(completed)
    metadata = _replay(read)
    value = object.__new__(HeldBt709IdentityObservation)
    values = {"completed": completed, "metadata": metadata, "_read": read, "executable": False,
              "gamut_measured": False, "grade_applicable": False, "base_render_applicable": False,
              "delivery_approved": False}
    for name, item in values.items():
        object.__setattr__(value, name, item)
    object.__setattr__(value, "_origin", _binding(value))
    original = value._origin
    HeldBt709IdentityObservation.assert_current(value)
    _unchanged(value, original)
    # Raw parsed objects were checked through the final callback. Future reads
    # need only the original file holds and frozen small supplemental metadata.
    read.loaded.clear()
    require_time(read.deadline)
    return value
