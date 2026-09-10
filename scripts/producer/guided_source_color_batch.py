"""All-used-source job preflight, never a runner, lease or color qualification.

Only original prepared source identities and exact existing job/preclaim bytes
are joined here. Native observation, source hashes and job creation remain
outside this module. The persistent preparation guard is never replaced by a
transient launch guard; every launch retains the original overall cutoff.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from color.deadline import require_time
from color.grade_contract import identifier
from color.grade_observation_profile import V2
from color.grade_project_input import read_grade_project_input, verify_grade_project_implementation
from guided_opening_inputs import hash_value
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_batch_files import BatchCodeInventory, hold_batch_code, hold_batch_inventory
from guided_source_color_hold import HeldSourceColorPreparation, _binding as preparation_binding
from guided_source_color_preparation import PreparedSourceColorJob
from headless.external_media_verification import VerifiedSnapshotIdentity
from headless.grade_launch_files import HeldLaunchFile, hold_launch_file
from headless.grade_launch_intent import OwnedGradeLaunch, read_grade_launch_metadata


@dataclass(frozen=True)
class SourceColorJobRef:
    """Original caller-held references, not authorization by dataclass construction."""

    source_id: str
    input_path: Path
    input_sha256: str
    launch: OwnedGradeLaunch


@dataclass(frozen=True)
class _PreparedColorJob:
    """Exact data for a future sequential owner; no callable execution capability."""

    value: dict
    directory: Path
    launch: OwnedGradeLaunch
    source: VerifiedSnapshotIdentity

    @property
    def source_id(self) -> str:
        """Preserve the actual original job source identifier."""
        return self.value["sourceId"]


def _ref_binding(row: SourceColorJobRef) -> tuple:
    """Retain original object identities, SHA/path spelling and launch scalar types."""
    if type(row) is not SourceColorJobRef or type(row.launch) is not OwnedGradeLaunch:
        raise RuntimeError("source color batch requires exact original job refs")
    return (id(row), row.source_id, type(row.input_path).__name__, str(row.input_path), row.input_sha256,
            id(row.launch), id(row.launch._original), row.launch.binding())


def _validate_refs(preparation: HeldSourceColorPreparation, refs: tuple[SourceColorJobRef, ...]) -> None:
    """Reject omissions, reordering and reused jobs before any callback or file read."""
    if type(preparation) is not HeldSourceColorPreparation or type(refs) is not tuple \
            or not 1 <= len(refs) <= 128 or type(preparation.jobs) is not tuple:
        raise RuntimeError("source color batch requires bounded actual preparation and refs")
    for row in refs:
        _ref_binding(row)
        identifier(row.source_id)
        hash_value(row.input_sha256)
        if type(row.input_path) is not type(Path()) or row.input_path.anchor != "/" \
                or row.input_path.name != "input.json" or ".." in row.input_path.parts:
            raise RuntimeError("source color batch job input path is invalid")
        if row.launch.binding() != row.launch._original or type(row.launch.deadline) is not type(preparation.context.deadline) \
                or row.launch.deadline != preparation.context.deadline:
            raise RuntimeError("source color batch launch must retain the original overall cutoff")
    if tuple(row.source_id for row in refs) != tuple(row.binding.source_id for row in preparation.jobs) \
            or len({row.input_path for row in refs}) != len(refs) \
            or len({row.launch.claim_path for row in refs}) != len(refs):
        raise RuntimeError("source color batch refs must match every used source in original order")


def _facts(value: object) -> tuple:
    """Detach held metadata without copying callbacks or hashing raw observations."""
    if type(value) is HeldLaunchFile:
        return (id(value), str(value.path), value.raw, value.identity, value.parents)
    if type(value) is BatchCodeInventory:
        return (id(value), tuple((str(row.path), row.identity) for row in value.files),
                tuple(map(str, value.parents)), value.directories)
    if type(value) is _PreparedColorJob:
        return (id(value), value.value, str(value.directory), id(value.launch), value.launch.binding(),
                id(value.source), value.source)
    raise RuntimeError("source color batch retained an unsupported record")


class _BatchRead:
    """One private original-lifetime fence spanning all sources and returned data."""

    def __init__(self, preparation: HeldSourceColorPreparation, refs: tuple[SourceColorJobRef, ...]) -> None:
        """Snapshot original arguments before invoking the persistent preparation guard."""
        _validate_refs(preparation, refs)
        self.preparation, self.refs = preparation, refs
        self.deadline = preparation.context.deadline
        self.retained: list[tuple[object, object]] = []
        self.jobs: list[_PreparedColorJob] = []
        self.original = self.arguments()

    def arguments(self) -> tuple:
        """Keep original preparation/context/refs, including equal-valued substitutions."""
        value = self.preparation
        return (id(value), id(value._origin), id(value.context), type(value.context.deadline).__name__,
                value.context.deadline, id(value.jobs), id(value.inputs), id(self.refs),
                tuple(_ref_binding(row) for row in self.refs), type(self.deadline).__name__, self.deadline,
                preparation_binding(value), value._read.arguments())

    def unchanged(self) -> None:
        """Reject metadata changes after the last callback or filesystem helper."""
        if self.arguments() != self.original:
            raise RuntimeError("source color batch original arguments changed")
        for value, expected in self.retained:
            if not same_read_metadata(_facts(value), expected):
                raise RuntimeError("source color batch original held record changed")

    def retain(self, value: object) -> None:
        """Bind exact returned file/data objects immediately before another callback."""
        self.retained.append((value, hold_read_metadata(_facts(value))))

    def check(self) -> None:
        """Use only the persistent original guard; transient launch guards are not called."""
        self.unchanged()
        require_time(self.deadline)
        self.preparation.assert_current()
        self.unchanged()
        for value, _expected in self.retained:
            if type(value) is HeldLaunchFile:
                value.check()
            if type(value) is BatchCodeInventory:
                value.assert_current(self.deadline)
        self.unchanged()
        require_time(self.deadline)
        self.unchanged()
        require_time(self.deadline)


def _join_job(value: dict, prepared: PreparedSourceColorJob, read: _BatchRead) -> None:
    """Compare unchanged source/declaration/profile/saved parents to actual preparation."""
    metadata = prepared.record()
    expected = {key: metadata[key] for key in ("sourceId", "declaration", "expected", "schemaVersion", "policy")}
    expected["producerDir"] = str(read.preparation.context.parents.producer_dir)
    if prepared.profile is V2:
        expected["profile"] = prepared.profile.token
    if not same_read_metadata({key: value.get(key) for key in expected}, hold_read_metadata(expected)):
        raise RuntimeError("source color batch job differs from original prepared source")


def _request(prepared: PreparedSourceColorJob) -> dict:
    """Build only a profile-bound metadata expectation, not a running work deadline."""
    result = {"sourceSha256": prepared.source.sha256, "frameCount": prepared.binding.frame_count,
              "timeoutSeconds": prepared.profile.max_seconds}
    if prepared.profile is V2:
        result.update(schemaVersion=2, profile=prepared.profile.token)
    return result


def _launch_files(read: _BatchRead, ref: SourceColorJobRef, prepared: PreparedSourceColorJob) -> None:
    """Join actual returned launch parents to this exact opening and grade input."""
    claim, files, snapshot = read_grade_launch_metadata(ref.launch, prepared.source.path,
                                                       _request(prepared), ref.input_path.parent / "execution")
    if type(files) is not tuple or len(files) != 4 or any(type(row) is not HeldLaunchFile for row in files):
        raise RuntimeError("source color batch launch metadata omitted original raw parents")
    for row in files:
        read.retain(row)
    inputs = read.preparation.inputs
    if (files[0].path, files[0].sha256) != (ref.launch.claim_path, ref.launch.claim_sha256) \
            or (files[1].path, files[1].sha256) != (ref.input_path, ref.input_sha256) \
            or (files[3].path, files[3].sha256) != (inputs.path, inputs.sha256) \
            or snapshot != inputs.value["pipeline"]["snapshotRoot"]:
        raise RuntimeError("source color batch launch belongs to different original inputs")
    if not same_read_metadata(claim, hold_read_metadata(files[0].value())) \
            or not same_read_metadata(inputs.value, hold_read_metadata(files[3].value())):
        raise RuntimeError("source color batch launch raw-parent projection changed")


def _prepare_job(read: _BatchRead, ref: SourceColorJobRef, prepared: PreparedSourceColorJob) -> None:
    """Validate one existing input/code/preclaim without creating its execution directory."""
    read.check()
    original = hold_launch_file(ref.input_path, ref.input_sha256)
    read.retain(original)
    value = read_grade_project_input(ref.input_path, ref.input_sha256, prepared.profile.token)
    job = _PreparedColorJob(value, ref.input_path.parent, ref.launch, prepared.source)
    read.retain(job)
    if not same_read_metadata(value, hold_read_metadata(original.value())):
        raise RuntimeError("source color batch actual job input projection changed")
    _join_job(value, prepared, read)
    inventory = hold_batch_inventory(ref.input_path.parent / "implementation.json", value["implementationSha256"], read.deadline)
    read.retain(inventory)
    read.retain(hold_batch_code(inventory, read.deadline))
    verify_grade_project_implementation(ref.input_path.parent, value)
    _launch_files(read, ref, prepared)
    read.jobs.append(job)
    read.check()


@dataclass(frozen=True, init=False)
class PreparedSourceColorBatch:
    """Whole-set preflight data with its original lifetime, never a runner or lease."""

    preparation: HeldSourceColorPreparation
    jobs: tuple[_PreparedColorJob, ...]
    executable: bool = field(default=False, init=False)
    grade_applicable: bool = field(default=False, init=False)
    delivery_approved: bool = field(default=False, init=False)
    _read: _BatchRead = field(repr=False)
    _origin: tuple = field(repr=False)

    def __init__(self) -> None:
        """Do not reconstruct a live data hold from JSON or caller-selected records."""
        raise TypeError("source color batch requires prepare_source_color_batch")

    def binding(self) -> tuple:
        """Retain the actual returned batch and private original read references."""
        return (id(self), id(self.preparation), id(self._read), id(self._read.original), id(self.jobs),
                tuple(id(row) for row in self.jobs), tuple(id(row) for row in self._read.jobs),
                id(self._read.retained), tuple((id(row), id(expected)) for row, expected in self._read.retained),
                type(self.executable), self.executable, type(self.grade_applicable), self.grade_applicable,
                type(self.delivery_approved), self.delivery_approved)

    def assert_current(self) -> None:
        """No callback, clone or late metadata change can produce a replacement baseline."""
        original = self._origin
        if self.binding() != original:
            raise RuntimeError("source color batch original lifetime changed")
        self._read.check()
        if self._origin is not original or self.binding() != original:
            raise RuntimeError("source color batch original lifetime changed")
        require_time(self._read.deadline)


def prepare_source_color_batch(preparation: HeldSourceColorPreparation,
                                refs: tuple[SourceColorJobRef, ...]) -> PreparedSourceColorBatch:
    """Finish every original used-source preflight before exposing any prepared job."""
    read = _BatchRead(preparation, refs)
    read.check()
    for ref, prepared in zip(refs, preparation.jobs):
        _prepare_job(read, ref, prepared)
    result = object.__new__(PreparedSourceColorBatch)
    values = {"preparation": preparation, "jobs": tuple(read.jobs), "_read": read,
              "executable": False, "grade_applicable": False, "delivery_approved": False}
    for name, value in values.items():
        object.__setattr__(result, name, value)
    object.__setattr__(result, "_origin", result.binding())
    result.assert_current()
    return result
