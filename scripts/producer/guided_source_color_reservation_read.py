"""Cold/partial reservation metadata, never process settlement or cleanup authority.

The caller authenticates the original claim, raw reservation SHA, request hash
and resource namespace. Its original protected timer bounds setup and callbacks.
Only three metadata files are read; no sidecar, jobs, source, tool or daemon is
consulted. A different controller PID is allowed and proves no process absence.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from color.deadline import require_time
from cut_preview_io import digest
from guided_opening_claim import HeldOpeningClaim, _KEYS, _identity
from guided_opening_inputs import DOCUMENTS, _INPUT_KEYS, closed, hash_value
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_staging_contract import _uuid, validate_source_color_reservation
from guided_source_color_staging_files import (
    capture_staging_file, check_staging_file, read_staging_file, staging_file_binding, staging_path,
)


@dataclass(frozen=True)
class SourceColorReservationReadContext:
    """Borrow authenticated original claim, namespace, request and protected cutoff."""

    opening: HeldOpeningClaim
    producer_dir: Path
    resource_dir: Path
    source_color_hash: str
    deadline: float
    guard: Callable[[], None]


def _context(value: SourceColorReservationReadContext) -> tuple:
    """Hold exact original fields before callbacks, without adopting a new context."""
    if type(value) is not SourceColorReservationReadContext or type(value.opening) is not HeldOpeningClaim \
            or not callable(value.guard) or type(value.deadline) not in (int, float) or not math.isfinite(value.deadline):
        raise ValueError("source color reservation requires original typed claim/context")
    opening = value.opening
    return (id(value), id(opening), id(value.guard), value.deadline,
            str(staging_path(value.producer_dir)), str(staging_path(value.resource_dir)), hash_value(value.source_color_hash),
            str(staging_path(opening.path)), hash_value(opening.sha256), id(opening.value), opening.value)


def _paths(reference: tuple[Path, str], context: SourceColorReservationReadContext) -> tuple[Path, ...]:
    """Derive the only three readable paths before any external callback or raw IO."""
    if type(reference) is not tuple or len(reference) != 2:
        raise ValueError("source color reservation requires one authenticated raw reference")
    staging_path(reference[0])
    hash_value(reference[1])
    claim = closed(context.opening.value, _KEYS, "reservation original claim")
    root = context.producer_dir / "guided-v2-operations" / _uuid(claim["requestId"]) / "executions" / _uuid(claim["executionId"])
    expected = (context.resource_dir / "active.json", root / "execution-claim.json", root / "media-input/input.json")
    if reference[0] != expected[0] or context.opening.path != expected[1] or claim["inputPath"] != str(expected[2]) \
            or context.resource_dir.name != ".sniper-color-resource":
        raise ValueError("source color reservation escaped original execution/resource")
    hash_value(claim["inputSha256"])
    return expected


def _binding(read: _ReservationRead) -> tuple:
    """Retain original raw files and exact parser objects, never serialized owners."""
    return (id(read.context), id(read.reference), str(read.reference[0]), read.reference[1], id(read.callback), read.deadline,
            tuple(staging_file_binding(row) for row in read.files),
            tuple((staging_file_binding(row), id(value), value) for row, value in read.loaded))


def _unchanged(read: _ReservationRead) -> None:
    """Reject context or parsed-return mutation before any replacement callback runs."""
    if not same_read_metadata(_context(read.context), read.context_binding) or not same_read_metadata(_binding(read), read.fixed):
        raise RuntimeError("source color reservation original context/files/parsed metadata changed")
    if read.result is not None and not same_read_metadata((id(read.result), read.result), read.result_binding):
        raise RuntimeError("source color reservation original detached result changed")


def _check(read: _ReservationRead) -> None:
    """Bracket the same guard with metadata and all-file checks under original time."""
    _unchanged(read)
    require_time(read.deadline)
    read.callback()
    _unchanged(read)
    for row in (*read.files, *(item[0] for item in read.loaded)):
        check_staging_file(row)
    _unchanged(read)
    require_time(read.deadline)


class _ReservationRead:
    """Private three-file lifetime; no process PID comparison or resource mutation."""

    def __init__(self, reference: tuple[Path, str], context: SourceColorReservationReadContext) -> None:
        """Capture all initial inode/ancestry identities before the first callback."""
        self.context_binding = hold_read_metadata(_context(context))
        self.context, self.reference = context, reference
        self.deadline, self.callback = context.deadline, context.guard
        require_time(self.deadline)
        self.files = tuple(capture_staging_file(path) for path in _paths(reference, context))
        self.loaded: list = []
        self.result, self.result_binding = None, None
        self.fixed = hold_read_metadata(_binding(self))
        _check(self)

    def load(self, index: int, sha: str) -> dict:
        """Retain an actual bounded raw/parser return before any later callback."""
        _check(self)
        held, value = read_staging_file(self.files[index], sha, 8 * 1024 ** 2 if index == 0 else 128 * 1024)
        returned = hold_read_metadata((staging_file_binding(held), id(value), value))
        _unchanged(self)
        if not same_read_metadata((staging_file_binding(held), id(value), value), returned):
            raise RuntimeError("source color reservation actual parsed return changed")
        self.loaded.append((held, value))
        self.fixed = hold_read_metadata(_binding(self))
        _check(self)
        return value


def _original_input(read: _ReservationRead, claim: dict, value: dict) -> None:
    """Join original claim/input bytes without reading any other original document."""
    if not same_read_metadata(claim, hold_read_metadata(read.context.opening.value)):
        raise RuntimeError("source color reservation original claim raw projection differs")
    closed(value, _INPUT_KEYS, "reservation original input")
    closed(value["documents"], DOCUMENTS, "reservation original document refs")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or value["kind"] != "guided-opening-media-input" \
            or value["executionInputHash"] != digest({key: row for key, row in value.items() if key != "executionInputHash"}):
        raise RuntimeError("source color reservation original input role/hash differs")
    input_path = read.files[2].path
    _identity(claim, value, (input_path, claim["inputSha256"], input_path.parent.parent / "media-output"))


def _join(read: _ReservationRead, value: dict) -> None:
    """Bind planned names to original request, claim/runtime and supplied namespace."""
    context, opening = read.context, read.context.opening
    expected = {"claimPath": str(opening.path), "claimSha256": opening.sha256,
                **{key: opening.value[key] for key in ("inputPath", "inputSha256", "executionId", "executionInputHash",
                   "clockHash", "generationStartedAt", "budgetAdmissionHash", "beforeJournalHash")}}
    if not same_read_metadata(value["opening"], hold_read_metadata(expected)) \
            or not same_read_metadata(value["runtime"], hold_read_metadata(opening.value["runtime"])) \
            or value["producerDir"] != str(context.producer_dir) or value["sourceColorHash"] != context.source_color_hash:
        raise RuntimeError("source color reservation original claim/runtime/request lineage differs")


@dataclass(frozen=True, init=False)
class HeldSourceColorReservation:
    """Held planned names only; no process settlement, native cleanup or release authority."""

    value: dict
    container_names: tuple[str, ...]
    size_bytes: int
    _read: _ReservationRead = field(repr=False)
    _origin: tuple = field(repr=False)

    def __init__(self) -> None:
        """Only the original-reference reader creates a persistent metadata hold."""
        raise TypeError("source color reservation requires read_source_color_reservation")

    def assert_current(self) -> None:
        """Keep original raw/stat/context/deadline proof without rereading or new clocks."""
        original = self._origin
        _held_current(self, original)
        _check(self._read)
        _held_current(self, original)
        require_time(self._read.deadline)


def _held_current(value: HeldSourceColorReservation, original: tuple) -> None:
    """Do not let cloned or replaced planned-name projections become a held read."""
    if value._origin is not original or (id(value), id(value.value), id(value._read), id(value.container_names), value.size_bytes) != original \
            or type(value.size_bytes) is not int or value.size_bytes != len(value._read.loaded[-1][0].raw) \
            or value.value is not value._read.result or value.container_names != tuple(row["containerName"] for row in value.value["jobs"]):
        raise RuntimeError("source color reservation held reader identity changed")


def read_source_color_reservation(reference: tuple[Path, str], context: SourceColorReservationReadContext) -> HeldSourceColorReservation:
    """Read only reservation/claim/input; actual outer/nested settlement belongs to TS."""
    read = _ReservationRead(reference, context)
    claim = read.load(1, context.opening.sha256)
    original = read.load(2, context.opening.value["inputSha256"])
    _original_input(read, claim, original)
    reserved = read.load(0, reference[1])
    value = validate_source_color_reservation(reserved)
    read.result, read.result_binding = value, hold_read_metadata((id(value), value))
    _unchanged(read)
    _join(read, value)
    held = object.__new__(HeldSourceColorReservation)
    object.__setattr__(held, "value", value)
    object.__setattr__(held, "container_names", tuple(row["containerName"] for row in value["jobs"]))
    object.__setattr__(held, "size_bytes", len(read.loaded[-1][0].raw))
    object.__setattr__(held, "_read", read)
    object.__setattr__(held, "_origin", (id(held), id(value), id(read), id(held.container_names), held.size_bytes))
    held.assert_current()
    return held
