"""Original opening dependencies for cheap repeated source-color work guards.

This internal holder borrows already admitted inputs, claim, executed pipeline
and the SAME opening clock. It hashes bounded control/code/tool files once;
original source snapshots come from the initial successful source-hash pass.
It grants no journal/lease, renderer, source-color, cache or approval authority.
Final whole-byte and audiovisual verification remains the caller's obligation.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from weakref import WeakKeyDictionary

from cut_preview_io import bound_json, digest
from guided_body_execution import (
    BodyHeldFile, _directory_states, _parent_paths, assert_body_files, hold_body_file,
)
from guided_opening_claim import HeldOpeningClaim, _canonical_path
from guided_opening_execution import OpeningExecutionClock
from guided_opening_inputs import OpeningInputs, closed, hash_value
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from headless.external_media_verification import (
    SourceVerificationRuntime, assert_verified_snapshots, snapshot_stat_identity,
)
from ingest_media_observation import VerifiedExecutionMedia

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAX_DEPENDENCY_BYTES = 512 * 1024 ** 2
_ORIGINALS = WeakKeyDictionary()
_RETAINED = WeakKeyDictionary()


def _arguments(inputs: OpeningInputs, claim: HeldOpeningClaim, pipeline: dict,
               clock: OpeningExecutionClock) -> tuple:
    """Retain caller objects and exact numeric types before any file capture."""
    if type(inputs) is not OpeningInputs or type(claim) is not HeldOpeningClaim \
            or type(inputs.verified_media) is not VerifiedExecutionMedia \
            or type(clock) is not OpeningExecutionClock or set(vars(clock)) != {"end", "events"} \
            or type(clock.events) is not list or type(clock.end) not in (int, float):
        raise RuntimeError("opening lifetime requires actual original inputs/claim/capture/clock")
    capture = inputs.verified_media
    if type(capture.snapshots) is not tuple or not capture.snapshots:
        raise RuntimeError("opening lifetime requires all original verified source snapshots")
    return (id(inputs), str(inputs.path), inputs.sha256, id(inputs.value), inputs.value,
            id(inputs.documents), inputs.documents, id(capture), id(capture.snapshots), capture,
            tuple(id(row) for row in capture.snapshots), id(claim), str(claim.path), claim.sha256,
            id(claim.value), claim.value, id(pipeline), pipeline, id(clock), clock.end, id(clock.events))


def _logical_path(root: Path, logical: object) -> Path:
    """Reject aliases before resolving any independently pinned code path."""
    if type(logical) is not str or not logical or "\\" in logical or logical.startswith("/") \
            or any(part in {"", ".", ".."} for part in logical.split("/")):
        raise RuntimeError("opening lifetime pinned path is malformed")
    return _canonical_path(str(root / logical))


def _pipeline_refs(inputs: OpeningInputs, pipeline: dict) -> list[tuple[Path, str]]:
    """Join the complete immutable snapshot and actual invoked code/tool closure."""
    expected = closed(inputs.value["pipeline"], {"snapshotRoot", "lockPath", "lockSha256", "digest"}, "pipeline")
    closed(pipeline, {"schemaVersion", "kind", "pipelineDigest", "lockSha256", "pinnedFileCount",
                      "executionClosure", "tools"}, "executed pipeline")
    lock_path = _canonical_path(expected["lockPath"])
    lock = bound_json(lock_path, hash_value(expected["lockSha256"]))
    rows, closure = lock["files"], pipeline["executionClosure"]
    if type(pipeline["schemaVersion"]) is not int or pipeline["schemaVersion"] != 1 \
            or pipeline["kind"] != "guided-opening-executed-pipeline" \
            or type(rows) is not list or not 1 <= len(rows) <= 20000 or type(closure) is not list \
            or not 1 <= len(closure) <= 20000 or digest(rows) != expected["digest"] \
            or pipeline["pipelineDigest"] != expected["digest"] or pipeline["lockSha256"] != expected["lockSha256"] \
            or type(pipeline["pinnedFileCount"]) is not int or pipeline["pinnedFileCount"] != len(rows):
        raise RuntimeError("opening lifetime executed pipeline differs from its original lock")
    snapshot = Path(expected["snapshotRoot"])
    if snapshot != lock_path.parent / "files":
        raise RuntimeError("opening lifetime snapshot is not owned by its original lock")
    refs = [(lock_path, expected["lockSha256"])]
    expected_code = {}
    for row in rows:
        closed(row, {"path", "hash"}, "pipeline file")
        refs.append((_logical_path(snapshot, row["path"]), hash_value(row["hash"])))
        if row["path"] in expected_code:
            raise RuntimeError("opening lifetime pipeline repeats a file")
        expected_code[row["path"]] = row["hash"]
    for row in closure:
        closed(row, {"path", "sha256"}, "executed file")
        if expected_code.get(row["path"]) != row["sha256"]:
            raise RuntimeError("opening lifetime invoked code is absent from the original snapshot")
        refs.append((_logical_path(REPOSITORY_ROOT, row["path"]), hash_value(row["sha256"])))
    for row in closed(pipeline["tools"], {"python", "ffmpeg", "ffprobe"}, "executed tools").values():
        closed(row, {"path", "sha256"}, "executed tool")
        refs.append((_canonical_path(row["path"]), hash_value(row["sha256"])))
    return refs


def _references(inputs: OpeningInputs, claim: HeldOpeningClaim, pipeline: dict) -> tuple[tuple[Path, str], ...]:
    """Deduplicate small dependencies without silently choosing a conflicting hash."""
    refs = [(inputs.path, inputs.sha256), (claim.path, claim.sha256)]
    refs.extend((Path(row["path"]), row["sha256"]) for row in inputs.value["documents"].values())
    refs.extend(_pipeline_refs(inputs, pipeline))
    runtime = claim.value["runtime"]
    refs.extend((Path(runtime[name]), runtime[sha]) for name, sha in (
        ("dockerPath", "dockerSha256"), ("imageApprovalPath", "imageApprovalSha256")))
    seen = {}
    for path, sha in refs:
        _canonical_path(str(path))
        hash_value(sha)
        if path in seen and seen[path] != sha:
            raise RuntimeError("opening lifetime dependency has conflicting original hashes")
        seen[path] = sha
    return tuple(seen.items())


def _retained_fields(value: OpeningSourceLifetime) -> tuple:
    """Private original holds must not be replaced with empty or fresh aliases."""
    return (id(value.capture), id(value.runtime), id(value.runtime.remaining), id(value.files),
            tuple((id(row), str(row.path), row.sha256, row.identity) for row in value.files),
            id(value.parents), tuple(str(row) for row in value.parents), value.parent_identity,
            str(value.socket), value.socket_identity)


class OpeningSourceLifetime:
    """One internal persistent owner; retired transient color markers are excluded."""

    def __init__(self, inputs: OpeningInputs, claim: HeldOpeningClaim,
                 pipeline: dict, clock: OpeningExecutionClock) -> None:
        """Capture original source/control ancestors before hashing bounded dependencies."""
        self.inputs, self.claim, self.pipeline, self.clock = inputs, claim, pipeline, clock
        _ORIGINALS[self] = (hold_read_metadata(_arguments(inputs, claim, pipeline, clock)),
                            hold_read_metadata(clock.events), len(clock.events))
        self.capture = inputs.verified_media
        self.runtime = SourceVerificationRuntime(lambda: OpeningExecutionClock.remaining(clock))
        refs = _references(inputs, claim, pipeline)
        self.socket = _canonical_path(claim.value["runtime"]["dockerSocketPath"])
        self.socket_identity = OpeningSourceLifetime._socket_identity(self)
        paths = tuple(BodyHeldFile(path, sha, ()) for path, sha in refs)
        sources = tuple(BodyHeldFile(Path(row.path), row.sha256, ()) for row in self.capture.snapshots)
        self.parents = _parent_paths((*paths, *sources, BodyHeldFile(self.socket, "", ())))
        self.parent_identity = _directory_states(self.parents)
        self.files = ()
        _RETAINED[self] = hold_read_metadata(_retained_fields(self))
        OpeningSourceLifetime.remaining(self)
        total, files = 0, []
        for path, sha in refs:
            OpeningSourceLifetime.remaining(self)
            held = hold_body_file(path, sha, min(64 * 1024 ** 2, MAX_DEPENDENCY_BYTES - total))
            files.append(held)
            total += held.identity[5]
        OpeningSourceLifetime.remaining(self)
        self.files = tuple(files)
        _RETAINED[self] = hold_read_metadata(_retained_fields(self))
        OpeningSourceLifetime.guard(self)

    def remaining(self) -> float:
        """Use the original clock method only; never rebaseline or renew it."""
        original, events, count = _ORIGINALS[self]
        expected = {"inputs", "claim", "pipeline", "clock", "capture", "runtime", "socket", "socket_identity",
                    "parents", "parent_identity", "files"}
        if set(vars(self)) != expected or self.capture is not self.inputs.verified_media \
                or not same_read_metadata(_arguments(self.inputs, self.claim, self.pipeline, self.clock), original) \
                or not same_read_metadata(self.clock.events[:count], events):
            raise RuntimeError("opening lifetime original input/claim/pipeline/clock changed")
        if self in _RETAINED and not same_read_metadata(_retained_fields(self), _RETAINED[self]):
            raise RuntimeError("opening lifetime original captured dependencies changed")
        return OpeningExecutionClock.remaining(self.clock)

    def _socket_identity(self) -> tuple:
        """Observe only the original admitted local control, with no daemon request."""
        info = self.socket.lstat()
        runtime = self.claim.value["runtime"]
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() \
                or str(info.st_dev) != runtime["dockerSocketDevice"] or str(info.st_ino) != runtime["dockerSocketInode"]:
            raise RuntimeError("opening lifetime original Docker socket changed")
        return snapshot_stat_identity(info)

    def guard(self) -> None:
        """Close original sources/files/ancestors and time without another byte read."""
        OpeningSourceLifetime.remaining(self)
        if _directory_states(self.parents) != self.parent_identity \
                or OpeningSourceLifetime._socket_identity(self) != self.socket_identity:
            raise RuntimeError("opening lifetime original source/control ancestry changed")
        assert_body_files(self.files, self.clock)
        assert_verified_snapshots(self.capture.snapshots, self.runtime)
        if _directory_states(self.parents) != self.parent_identity \
                or OpeningSourceLifetime._socket_identity(self) != self.socket_identity:
            raise RuntimeError("opening lifetime original source/control ancestry changed")
        OpeningSourceLifetime.remaining(self)
