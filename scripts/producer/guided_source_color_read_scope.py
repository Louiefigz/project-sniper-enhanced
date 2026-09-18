"""One cold source-color read lifetime, not a live render/resource owner.

The server must supply the actual stopped-process sidecar and final-cleanup
archive references. Original receipt authority is supplied separately. This
scope keeps finite original control/code/tool/source identities through later
readback stages. It neither opens active.json nor observes the old Docker
socket. Native packet checks still run inside the caller's existing phase.
"""
from __future__ import annotations

import hashlib
import json
import stat
from copy import deepcopy
from functools import partial
from pathlib import Path
from weakref import WeakKeyDictionary

from cut_preview_io import MAX_JSON, digest, read_bytes
from guided_body_execution import BodyHeldFile, _identity, _parent_paths, _directory_states
from guided_opening_execution import OpeningExecutionClock
from guided_opening_inputs import OpeningInputs
from guided_opening_claim import HeldOpeningClaim
from guided_opening_lifetime import _pipeline_refs
from guided_opening_pipeline import observe_pipeline, read_closure_refs, verify_read_closure
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_base_context import assert_source_color_plan
from guided_source_color_media_evidence import EVIDENCE_NAME, EVIDENCE_SCOPE
from guided_source_color_observation_files import ColdSourceColorObservationContext
from guided_source_color_observation_rows import observation_reference, same_observation_data as same
from guided_source_color_read_transport import validate_source_color_read_transport
from guided_source_color_read_entry import assert_source_color_read_entry
from guided_source_color_read_clock import source_color_read_clock_fields, source_color_read_remaining
from guided_source_color_staging_contract import _path, _uuid
from guided_source_color_staging_files import _pairs
from headless.external_media_verification import SourceVerificationRuntime, assert_verified_snapshots
from color.grade_contract import closed

_ORIGINALS = WeakKeyDictionary()
_RETAINED = WeakKeyDictionary()
_REPLAYS = WeakKeyDictionary()
_PREFIXES = WeakKeyDictionary()


def _arguments(scope: SourceColorReadScope) -> tuple:
    """Retain typed caller references before the first file read or callback."""
    root, claim, clock, held, entry = scope.controls
    return (id(scope.inputs), str(scope.inputs.path), scope.inputs.sha256,
            id(scope.inputs.value), scope.inputs.value, id(scope.inputs.documents), scope.inputs.documents,
            id(scope.inputs.verified_media), scope.inputs.verified_media.entries_json,
            tuple((id(row), row) for row in scope.inputs.verified_media.snapshots),
            id(scope.record), scope.record, str(root), id(claim), str(claim.path), claim.sha256, claim.value,
            id(clock), clock.end, id(clock.events), id(held), held.input_sha256, str(held.claim_path),
            held.claim_sha256, held.receipt_sha256, held.receipt_hash, id(scope.transport), id(entry))


def _json(path: Path, sha: str, maximum: int) -> dict:
    """Bound JSON against an independently supplied raw SHA; reject duplicate/nonfinite data."""
    raw = read_bytes(path, maximum)
    if hashlib.sha256(raw).hexdigest() != sha:
        raise RuntimeError("source-color cold read original raw reference differs")
    value = json.loads(raw.decode("utf8", errors="strict"), object_pairs_hook=_pairs)
    if type(value) is not dict:
        raise ValueError("source-color cold read metadata must be an object")
    hold_read_metadata(value)
    return value


def _section(value: dict, reference: dict) -> None:
    """Close the new evidence role without accepting quality or approval assertions."""
    expected = {"schemaVersion": 1, "kind": "guided-opening-source-color-media-evidence", "scope": EVIDENCE_SCOPE,
                "gamutMeasured": False, "gradeApplied": False, "colorQualified": False,
                "openingApproved": False, "deliveryApproved": False}
    closed(value, set(expected) | {"observations", "pictureConsumption", "fullProgram", "receiptHash"}, "source-color evidence")
    same({key: value[key] for key in expected}, expected)
    same(value["receiptHash"], reference["receiptHash"])
    same(digest({key: row for key, row in value.items() if key != "receiptHash"}), reference["receiptHash"])


def _retained(scope: SourceColorReadScope) -> tuple:
    """Freeze setup holds, not just the caller's mutable serialized metadata."""
    return (id(scope.files), tuple((key, id(row), str(row.path), row.sha256, row.identity) for key, row in scope.files.items()),
            tuple(str(path) for path in scope.parents), scope.parent_states[1],
            tuple(str(path) for path in scope.source_parents), scope.source_states,
            id(scope.runtime), id(scope.runtime.remaining), id(scope.loaded),
            tuple((id(value), id(fixed)) for value, fixed in scope.loaded),
            id(scope.evidence), id(scope.pipeline), id(scope.references), id(scope.context), id(scope.context.guard),
            id(scope.context.inputs), id(scope.context.references), scope.context.deadline)


class SourceColorReadScope:
    """Finite original-file holds and retained replay handles; never execution authority."""

    def __init__(self, inputs: OpeningInputs, record: dict, controls: tuple, transport: object) -> None:
        """Capture selected metadata/dependencies before the existing whole-code verification."""
        validate_source_color_read_transport(transport)
        if transport is None or type(inputs) is not OpeningInputs or type(record) is not dict \
                or type(controls) is not tuple or len(controls) != 5 or type(controls[1]) is not HeldOpeningClaim \
                or not isinstance(controls[2], OpeningExecutionClock):
            raise ValueError("source-color cold read requires explicit stopped/final references")
        source_color_read_clock_fields(controls[2])
        assert_source_color_read_entry(controls[4], controls[2])
        self.inputs, self.record, self.controls, self.transport = inputs, record, controls, transport
        _ORIGINALS[self] = hold_read_metadata(_arguments(self))
        _PREFIXES[self] = len(controls[2].events), hold_read_metadata(controls[2].events)
        self.files, self.parents, self.parent_states = {}, (), ()
        self.observations, self.consumption = None, None
        _REPLAYS[self] = (None, None)
        self.loaded = []
        self.runtime = SourceVerificationRuntime(lambda: source_color_read_remaining(controls[2]))
        self.source_parents = _parent_paths(tuple(BodyHeldFile(Path(row.path), row.sha256, ()) for row in inputs.verified_media.snapshots))
        self.source_states = _directory_states(self.source_parents)
        assert_source_color_plan(inputs)
        self._initial()
        self.references = self._references()
        self.loaded.append((self.references, hold_read_metadata(self.references)))
        for path, sha in _pipeline_refs(inputs, record["pipeline"]):
            self._capture(path, sha, 64 * 1024 ** 2)
        read_refs = read_closure_refs(self.references["implementation"]["pipelineLock"], record["pipeline"],
                                     lambda path, sha: self._capture(path, sha, 64 * 1024 ** 2))
        SourceColorReadScope.check(self)
        self.pipeline = observe_pipeline(inputs)
        same(self.pipeline, record["pipeline"])
        self.loaded.append((self.pipeline, hold_read_metadata(self.pipeline)))
        SourceColorReadScope.check(self)
        verify_read_closure(read_refs, partial(SourceColorReadScope.check, self))
        self.context = ColdSourceColorObservationContext(inputs, self.references, controls[2].end, partial(SourceColorReadScope.check, self))
        _RETAINED[self] = hold_read_metadata(_retained(self))
        SourceColorReadScope.check(self)

    def _capture(self, path: Path, sha: str, maximum: int) -> None:
        """Retain original stat/ancestry before bytes, never a late or conflicting baseline."""
        if self in _RETAINED:
            raise RuntimeError("source-color cold read cannot add a late file baseline")
        _path(str(path))
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum:
            raise RuntimeError("source-color cold read file exceeds its regular bounded role")
        row = BodyHeldFile(path, sha, _identity(info))
        if str(path) in self.files and self.files[str(path)] != row:
            raise RuntimeError("source-color cold read file has conflicting original roles")
        self.files[str(path)] = row
        self.parents = _parent_paths(tuple(self.files.values()))
        states = _directory_states(self.parents)
        previous = dict(zip(self.parent_states[0], self.parent_states[1])) if self.parent_states else {}
        if any(previous.get(path, state) != state for path, state in zip(self.parents, states)):
            raise RuntimeError("source-color cold read original ancestry changed during capture")
        self.parent_states = self.parents, states
        SourceColorReadScope.assert_metadata(self)

    def _load(self, path: Path, sha: str, maximum: int) -> dict:
        """Use the original capture and retain the actual parsed return immediately."""
        if str(path) not in self.files:
            raise RuntimeError("source-color cold read attempted an uncaptured file")
        SourceColorReadScope.assert_metadata(self)
        value = _json(path, sha, maximum)
        self.loaded.append((value, hold_read_metadata(value)))
        SourceColorReadScope.assert_metadata(self)
        return value

    def _initial(self) -> None:
        """Capture exact result/claim/input/sidecar/archive/evidence and document paths."""
        root, claim, _clock, held, _entry = self.controls
        transport = self.transport
        execution = root.parent
        if str(root) != claim.value["outputRoot"] or transport.input_path != execution / "source-color/input.json" \
                or transport.archive_path != execution / "cleanup-attempts" / transport.archive_path.parent.name / "reservation.json":
            raise ValueError("source-color cold read transport escaped its original execution")
        _uuid(transport.archive_path.parent.name, True)
        reference = closed(self.record["sourceColorEvidence"], {"path", "sha256", "sizeBytes", "receiptHash"}, "source-color evidence ref")
        observation_reference({key: reference[key] for key in ("path", "sha256", "sizeBytes")}, root / EVIDENCE_NAME, MAX_JSON)
        rows = [(self.inputs.path, self.inputs.sha256, 128 * 1024), (claim.path, claim.sha256, 128 * 1024),
                (root / "media-result.json", held.receipt_sha256, MAX_JSON),
                (transport.input_path, transport.input_sha256, 8 * 1024 ** 2),
                (transport.archive_path, transport.archive_sha256, 8 * 1024 ** 2),
                (root / EVIDENCE_NAME, reference["sha256"], MAX_JSON)]
        rows.extend((Path(row["path"]), row["sha256"], MAX_JSON) for row in self.inputs.value["documents"].values())
        for path, sha, maximum in rows:
            self._capture(path, sha, maximum)
        same(self._load(root / "media-result.json", held.receipt_sha256, MAX_JSON), self.record)
        self.evidence = self._load(root / EVIDENCE_NAME, reference["sha256"], MAX_JSON)
        same(self.files[str(root / EVIDENCE_NAME)].identity[5], reference["sizeBytes"])
        _section(self.evidence, reference)

    def _references(self) -> dict:
        """Use stopped/final argv refs; the old active reference is data, never opened."""
        root, claim, _clock, _held, _entry = self.controls
        transport, pipeline = self.transport, self.inputs.value["pipeline"]
        staged = self._load(transport.input_path, transport.input_sha256, 8 * 1024 ** 2)
        producer = root.parents[4]
        expected = producer / "guided-v2-operations" / claim.value["requestId"] / "executions" / claim.value["executionId"]
        if root.parent != expected:
            raise ValueError("source-color cold read producer differs from original claim namespace")
        sidecar = {"path": str(transport.input_path), "sha256": transport.input_sha256,
                   "sizeBytes": self.files[str(transport.input_path)].identity[5]}
        archive = {"path": str(transport.archive_path), "sha256": transport.archive_sha256,
                   "sizeBytes": self.files[str(transport.archive_path)].identity[5]}
        same(archive, {**staged["reservation"], "path": str(transport.archive_path)})
        lock_path, lock_sha = Path(pipeline["lockPath"]), pipeline["lockSha256"]
        self._capture(lock_path, lock_sha, MAX_JSON)
        lock = self._load(lock_path, lock_sha, MAX_JSON)
        approval = Path(claim.value["runtime"]["imageApprovalPath"])
        self._capture(approval, claim.value["runtime"]["imageApprovalSha256"], 1024 ** 2)
        approval_ref = {"path": str(approval), "sha256": claim.value["runtime"]["imageApprovalSha256"],
                        "sizeBytes": self.files[str(approval)].identity[5]}
        return {"sidecar": sidecar, "reservation": deepcopy(staged["reservation"]), "archive": archive,
                "producerDir": str(producer), "openingClaim": claim.value,
                "implementation": {"pipelineLock": lock, "executedPipeline": self.record["pipeline"], "imageApproval": approval_ref}}

    def assert_metadata(self) -> None:
        """Close original arguments/files/sources with no caller callbacks or source rehash."""
        allowed = {"inputs", "record", "controls", "transport", "files", "parents", "parent_states", "observations",
                   "consumption", "loaded", "runtime", "source_parents", "source_states", "evidence", "references", "pipeline", "context"}
        if type(self) is not SourceColorReadScope or set(vars(self)) - allowed:
            raise RuntimeError("source-color cold read scope instance or methods changed")
        assert_source_color_read_entry(self.controls[4], self.controls[2])
        validate_source_color_read_transport(self.transport)
        if not same_read_metadata(_arguments(self), _ORIGINALS[self]) \
                or any(not same_read_metadata(value, fixed) for value, fixed in self.loaded):
            raise RuntimeError("source-color cold read original metadata changed")
        if self in _RETAINED and not same_read_metadata(_retained(self), _RETAINED[self]) \
                or any(actual is not fixed for actual, fixed in zip((self.observations, self.consumption), _REPLAYS[self])):
            raise RuntimeError("source-color cold read original file/replay holders changed")
        clock = self.controls[2]
        count, prefix = _PREFIXES[self]
        if not same_read_metadata(clock.events[:count], prefix):
            raise RuntimeError("source-color cold read original clock events changed")
        source_color_read_remaining(clock)
        states = self.parent_states[1] if self.parent_states else ()
        if _directory_states(self.parents) != states \
                or any(_identity(row.path.lstat()) != row.identity for row in self.files.values()) \
                or _directory_states(self.parents) != states:
            raise RuntimeError("source-color cold read original file or ancestry changed")
        if _directory_states(self.source_parents) != self.source_states:
            raise RuntimeError("source-color cold read original source ancestry changed")
        assert_verified_snapshots(self.inputs.verified_media.snapshots, self.runtime)
        if _directory_states(self.source_parents) != self.source_states:
            raise RuntimeError("source-color cold read original source ancestry changed")
        source_color_read_remaining(clock)

    def check(self) -> None:
        """Borrow only the same finite metadata/source cutoff, not old runtime ownership."""
        SourceColorReadScope.assert_metadata(self)

    def replay_observations(self) -> None:
        """Retain complete original raw replay for later stat-only final checks."""
        from guided_source_color_observation_read import hold_source_color_observations
        if self.observations is not None:
            raise RuntimeError("source-color cold observations cannot be replayed twice")
        observed = hold_source_color_observations(self.evidence["observations"], self.context)
        SourceColorReadScope.check(self)
        self.observations = observed
        _REPLAYS[self] = (observed, None)
        SourceColorReadScope.check(self)

    def replay_consumption(self) -> None:
        """Bind the current original base to replayed sources and actual packet identity."""
        from guided_source_color_consumption_read import SourceColorConsumptionReadContext, hold_source_color_consumption
        from guided_source_color_observation_read import HeldColdSourceColorObservations
        if self.observations is None or self.consumption is not None:
            raise RuntimeError("source-color cold base read requires one completed original observation replay")
        HeldColdSourceColorObservations.check(self.observations)
        bindings = {"evidenceRef": self.record["sourceColorEvidence"], "fullProgram": self.record["fullProgram"],
                    "observations": self.observations.record, "outputRoot": str(self.controls[0]), "tools": self.pipeline["tools"]}
        context = SourceColorConsumptionReadContext(self.inputs, bindings, self.controls[2].end, self.context.guard)
        consumed = hold_source_color_consumption(self.evidence, context)
        SourceColorReadScope.check(self)
        self.consumption = consumed
        _REPLAYS[self] = (self.observations, consumed)
        SourceColorReadScope.final_check(self)

    def final_check(self) -> None:
        """Reject missing groups and changes after later AV stages without another decoder."""
        if self.observations is None or self.consumption is None:
            raise RuntimeError("source-color cold read has incomplete observation/base coverage")
        from guided_source_color_observation_read import HeldColdSourceColorObservations
        from guided_source_color_consumption_read import HeldSourceColorConsumption
        SourceColorReadScope.check(self)
        HeldColdSourceColorObservations.check(self.observations)
        HeldSourceColorConsumption.check(self.consumption)
        HeldColdSourceColorObservations.assert_metadata(self.observations)
        HeldSourceColorConsumption.assert_metadata(self.consumption)
        SourceColorReadScope.assert_metadata(self)
