"""Authenticated-reference staging read, never admission or execution authority.

The caller authenticates the original claim/input and sidecar raw references,
resource namespace and persistent guard. Python record types alone prove none
of that provenance. Job refs/declarations/parents stay data; no job files, media,
runtime tools, leases, timers, launch owners or cleanup capabilities are made.
"""
from __future__ import annotations

import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from color.deadline import require_time
from color.grade_contract import identifier
from cut_preview_io import digest
from guided_opening_claim import HeldOpeningClaim, _KEYS, _identity
from guided_opening_inputs import DOCUMENTS, OpeningInputs, _INPUT_KEYS, closed, hash_value
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_staging_contract import validate_source_color_staging
from guided_source_color_staging_files import (
    capture_staging_file, check_staging_file, read_staging_file, staging_file_binding, staging_path,
)


@dataclass(frozen=True)
class SourceColorStagingReadContext:
    """Borrow original inputs, namespace, persistent callback and absolute cutoff."""

    inputs: OpeningInputs
    opening: HeldOpeningClaim
    producer_dir: Path
    resource_dir: Path
    deadline: float
    guard: Callable[[], None]


def _context(context: SourceColorStagingReadContext) -> tuple:
    """Read typed caller fields directly before and after every external callback."""
    if type(context) is not SourceColorStagingReadContext or type(context.inputs) is not OpeningInputs \
            or type(context.opening) is not HeldOpeningClaim or not callable(context.guard) \
            or type(context.deadline) not in (int, float) or not math.isfinite(context.deadline):
        raise ValueError("source color staging requires original typed input/claim/context")
    inputs, opening = context.inputs, context.opening
    return (id(context), id(inputs), id(opening), id(context.guard), context.deadline,
            str(staging_path(context.producer_dir)), str(staging_path(context.resource_dir)),
            str(staging_path(inputs.path)), hash_value(inputs.sha256), id(inputs.value), inputs.value,
            id(inputs.documents), inputs.documents, id(inputs.verified_media),
            str(staging_path(opening.path)), hash_value(opening.sha256), id(opening.value), opening.value)


def _paths(reference: tuple[Path, str], context: SourceColorStagingReadContext) -> tuple[Path, ...]:
    """Derive every readable file independently before any callback or raw read."""
    if type(reference) is not tuple or len(reference) != 2:
        raise ValueError("source color staging requires one authenticated raw reference")
    sidecar, sha = reference
    staging_path(sidecar)
    hash_value(sha)
    claim = closed(context.opening.value, _KEYS, "staging original claim")
    execution = context.producer_dir / "guided-v2-operations" / claim["requestId"] / "executions" / claim["executionId"]
    expected = (execution / "source-color/input.json", context.resource_dir / "active.json",
                execution / "execution-claim.json", execution / "media-input/input.json")
    if sidecar != expected[0] or context.opening.path != expected[2] or context.inputs.path != expected[3] \
            or context.resource_dir.name != ".sniper-color-resource":
        raise ValueError("source color staging reference escaped the original execution/resource")
    _identity(claim, context.inputs.value, (context.inputs.path, context.inputs.sha256, execution / "media-output"))
    return expected


def _binding(read: _StagingRead) -> tuple:
    """Retain actual parsed return objects and original raw/file/context lifetimes."""
    return (id(read.context), id(read.reference), str(read.reference[0]), read.reference[1],
            id(read.callback), read.deadline, read.parent_pid, os.getppid(), tuple(staging_file_binding(row) for row in read.files),
            tuple((staging_file_binding(row), id(value), value) for row, value in read.loaded))


def _unchanged(read: _StagingRead) -> None:
    """Compare originals without adopting a later parser or context baseline."""
    if not same_read_metadata(_context(read.context), read.context_binding) \
            or not same_read_metadata(_binding(read), read.fixed):
        raise RuntimeError("source color staging original context/files/parsed metadata changed")
    if read.result is not None and not same_read_metadata((id(read.result), read.result), read.result_binding):
        raise RuntimeError("source color staging original detached result changed")


def _check(read: _StagingRead) -> None:
    """Use the SAME persistent guard and finish with original time after all checks."""
    _unchanged(read)
    require_time(read.deadline)
    read.callback()
    _unchanged(read)
    for row in (*read.files, *(item[0] for item in read.loaded)):
        check_staging_file(row)
    _unchanged(read)
    require_time(read.deadline)


class _StagingRead:
    """Private four-file read with no source, job, process or runtime-tool work."""

    def __init__(self, reference: tuple[Path, str], context: SourceColorStagingReadContext) -> None:
        """Capture initial file identities before calling the original external guard."""
        self.context_binding = hold_read_metadata(_context(context))
        self.context, self.reference = context, reference
        self.deadline, self.callback = context.deadline, context.guard
        self.parent_pid = os.getppid()
        require_time(self.deadline)
        paths = _paths(reference, context)
        self.files = tuple(capture_staging_file(path) for path in paths)
        self.loaded: list = []
        self.result, self.result_binding = None, None
        self.fixed = hold_read_metadata(_binding(self))
        _check(self)

    def load(self, index: int, sha: str) -> dict:
        """Retain the actual byte/parser return before another caller callback."""
        _check(self)
        maximum = 8 * 1024 ** 2 if index < 2 else 128 * 1024
        held, value = read_staging_file(self.files[index], sha, maximum)
        returned = hold_read_metadata((staging_file_binding(held), id(value), value))
        _unchanged(self)
        if not same_read_metadata((staging_file_binding(held), id(value), value), returned):
            raise RuntimeError("source color staging actual parsed return changed")
        self.loaded.append((held, value))
        self.fixed = hold_read_metadata(_binding(self))
        _check(self)
        return value


def _original_input(read: _StagingRead, claim: dict, value: dict) -> None:
    """Join actual retained original input, clock and selected-order metadata only."""
    inputs = read.context.inputs
    if not same_read_metadata(claim, hold_read_metadata(read.context.opening.value)) \
            or not same_read_metadata(value, hold_read_metadata(inputs.value)):
        raise RuntimeError("source color staging original claim/input raw projection differs")
    closed(value, _INPUT_KEYS, "staging original input")
    closed(value["documents"], DOCUMENTS, "staging original document refs")
    if value["schemaVersion"] != 1 or type(value["schemaVersion"]) is not int \
            or value["kind"] != "guided-opening-media-input" \
            or value["executionInputHash"] != digest({key: row for key, row in value.items() if key != "executionInputHash"}):
        raise RuntimeError("source color staging original input role/hash differs")
    authority, bindings = inputs.documents["authority"], inputs.documents["frameBindings"]
    orders = sorted(row["order"] for row in bindings["graphics"] if row["startFrame"] < authority["review"]["endFrameExclusive"])
    if claim["selectedGraphicOrders"] != orders or claim["clockHash"] != authority["clockHash"] \
            or claim["generationStartedAt"] != authority["generationStartedAt"]:
        raise RuntimeError("source color staging original clock/order lineage differs")


def _source_order(inputs: OpeningInputs) -> list[str]:
    """Derive only metadata first-kept order, never admit or observe source bytes."""
    cuts = inputs.documents["acceptedPlan"]["cutTrack"]
    candidate = inputs.documents["candidatePlan"]["cutTrack"]
    if type(cuts) is not list or not 1 <= len(cuts) <= 10000 \
            or not same_read_metadata(candidate, hold_read_metadata(cuts)):
        raise RuntimeError("source color staging requires unchanged nonempty original cuts")
    result = []
    for row in cuts:
        if type(row) is not dict:
            raise ValueError("source color staging kept cut metadata is malformed")
        source_id = identifier(row.get("sourceId"))
        if source_id not in result:
            result.append(source_id)
    return result


def _join(read: _StagingRead, sidecar: dict, reservation: dict) -> None:
    """Tie parsed sidecar data to independently held original lineage and namespace."""
    context, opening = read.context, read.context.opening
    expected = {"claimPath": str(opening.path), "claimSha256": opening.sha256,
                **{key: opening.value[key] for key in ("inputPath", "inputSha256", "executionId", "executionInputHash",
                   "clockHash", "generationStartedAt", "budgetAdmissionHash", "beforeJournalHash")}}
    if not same_read_metadata(sidecar["opening"], hold_read_metadata(expected)) \
            or not same_read_metadata(reservation["runtime"], hold_read_metadata(opening.value["runtime"])) \
            or sidecar["producerDir"] != str(context.producer_dir):
        raise RuntimeError("source color staging original opening/runtime/producer lineage differs")
    if type(reservation["ownerPid"]) is not int or reservation["ownerPid"] != read.parent_pid \
            or [row["sourceId"] for row in sidecar["jobs"]] != _source_order(context.inputs):
        raise RuntimeError("source color staging original live parent/source order differs")
    ref = sidecar["reservation"]
    if ref["path"] != str(context.resource_dir / "active.json") or type(ref["sizeBytes"]) is not int \
            or ref["sizeBytes"] != len(read.loaded[-1][0].raw):
        raise RuntimeError("source color staging original reservation path/size differs")


@dataclass(frozen=True, init=False)
class HeldSourceColorStaging:
    """Data-only read evidence; never a worker, resource lease or cleanup handle."""

    value: dict
    _read: _StagingRead = field(repr=False)
    _origin: tuple = field(repr=False)

    def __init__(self) -> None:
        """Only the authenticated-reference reader may create a held read result."""
        raise TypeError("source color staging requires read_source_color_staging")

    def assert_current(self) -> None:
        """Recheck original metadata/stat lifetime without raw rehash or new clock."""
        original = self._origin
        _held_current(self, original)
        _check(self._read)
        _held_current(self, original)
        require_time(self._read.deadline)


def _held_current(value: HeldSourceColorStaging, original: tuple) -> None:
    """Do not turn mutable JSON, a cloned wrapper or replaced read into authority."""
    if value._origin is not original or (id(value), id(value.value), id(value._read)) != original \
            or value.value is not value._read.result:
        raise RuntimeError("source color staging held reader identity changed")


def read_source_color_staging(reference: tuple[Path, str], context: SourceColorStagingReadContext) -> HeldSourceColorStaging:
    """Read authenticated metadata only; original caller owns every provenance claim."""
    read = _StagingRead(reference, context)
    claim = read.load(2, context.opening.sha256)
    original = read.load(3, context.inputs.sha256)
    _original_input(read, claim, original)
    sidecar = read.load(0, reference[1])
    ref = closed(sidecar.get("reservation"), {"path", "sha256", "sizeBytes"}, "staging reservation ref")
    if ref["path"] != str(context.resource_dir / "active.json"):
        raise RuntimeError("source color staging reservation escaped original resource")
    reservation = read.load(1, hash_value(ref["sha256"]))
    value = validate_source_color_staging(sidecar, reservation)
    read.result, read.result_binding = value, hold_read_metadata((id(value), value))
    _unchanged(read)
    _join(read, value, reservation)
    held = object.__new__(HeldSourceColorStaging)
    object.__setattr__(held, "value", value)
    object.__setattr__(held, "_read", read)
    object.__setattr__(held, "_origin", (id(held), id(value), id(read)))
    held.assert_current()
    return held
