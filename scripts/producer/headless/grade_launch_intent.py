"""Preclaimed grade launch evidence, never recovery or lease authority.
The caller retains project/resource/source authority and original time/guard.
This adapter reads metadata and publishes evidence without launching anything;
source byte verification and unconditional daemon cleanup remain policy-owned.
"""
from __future__ import annotations

import math
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from color.deadline import require_time
from color.grade_observation_profile import observation_profile, parse_request, project_profile
from cut_preview_io import bound_json, digest
from guided_opening_claim import _KEYS as _OPENING_KEYS, _identity as opening_identity, verify_runtime_controls
from guided_opening_inputs import DOCUMENTS, _INPUT_KEYS
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from headless.container_policy import DockerRuntime
from headless.external_media_verification import snapshot_stat_identity
from headless.grade_launch_files import HeldLaunchFile, directory_identity, hold_launch_file, publish_launch_file

_SHA = re.compile(r"[a-f0-9]{64}")
_KEYS = {"schemaVersion", "kind", "scope", "jobId", "inputPath", "inputSha256", "executionDir",
    "sourcePath", "sourceSha256", "frameCount", "profile", "containerName", "openingClaimPath",
    "openingClaimSha256", "runtime"}


def _sha(value: object) -> str:
    """Require a lowercase raw SHA without coercion."""
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError("grade launch raw SHA is invalid")
    return value


def _path(value: object) -> Path:
    """Reject alternative spellings before any filesystem access."""
    if type(value) is not str or not value.startswith("/") or "\\" in value \
            or any(ord(char) < 32 for char in value) or str(Path(value)) != value \
            or any(part in (".", "..") for part in value.split("/")):
        raise ValueError("grade launch path must have exact canonical spelling")
    return Path(value)


@dataclass(frozen=True)
class OwnedGradeLaunch:
    """Borrow the original callback/deadline and externally held claim digest."""

    claim_path: Path
    claim_sha256: str
    deadline: float
    guard: Callable[[], None]
    _original: tuple = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Freeze caller fields before the first callback or file read."""
        if type(self.claim_path) is not type(Path()) or _path(str(self.claim_path)) != self.claim_path \
                or type(self.deadline) not in (float, int) or not math.isfinite(self.deadline) \
                or not callable(self.guard):
            raise ValueError("grade launch requires exact original context")
        _sha(self.claim_sha256)
        object.__setattr__(self, "_original", self.binding())

    def binding(self) -> tuple:
        """Keep numeric types and callback identity, not equality alone."""
        return (id(type(self.claim_path)), str(self.claim_path), id(type(self.claim_sha256)), self.claim_sha256,
                id(type(self.deadline)), self.deadline, id(self.guard))


def _claim(value: dict, source: str, request: dict, directory: Path) -> None:
    """Match the closed preclaim to the actual policy arguments."""
    if set(value) != _KEYS or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 \
            or value["kind"] != "owned-grade-launch-claim" \
            or value["scope"] != "preclaimed-source-observation-not-recovery-or-approval":
        raise ValueError("grade launch claim schema is unsupported")
    job = UUID(value["jobId"]) if type(value["jobId"]) is str else None
    if job is None or job.version != 4 or str(job) != value["jobId"] \
            or value["containerName"] != f"sniper-grade-observation-{job.hex}":
        raise ValueError("grade launch exact job/container name is invalid")
    expected = {"executionDir": str(directory), "sourcePath": source, "sourceSha256": request["sourceSha256"],
                "frameCount": request["frameCount"], "profile": request.get("profile")}
    if not same_read_metadata({key: value[key] for key in expected}, hold_read_metadata(expected)):
        raise ValueError("grade launch source/request/execution differs from preclaim")
    for key in ("inputSha256", "sourceSha256", "openingClaimSha256"):
        _sha(value[key])
    for key in ("inputPath", "executionDir", "sourcePath", "openingClaimPath"):
        _path(value[key])


def _parents(claim: dict) -> tuple:
    """Hold actual grade and opening inputs; do not substitute a current pointer."""
    grade = hold_launch_file(_path(claim["inputPath"]), claim["inputSha256"])
    value = grade.value()
    producer = _path(value["producerDir"])
    job = producer / ".sniper-grade-observations" / claim["jobId"]
    if value["jobId"] != claim["jobId"] or grade.path != job / "input.json" \
            or _path(claim["executionDir"]) != job / "execution" \
            or project_profile(value) != observation_profile(claim["profile"]):
        raise ValueError("grade launch input is not the exact original project job")
    parent = hold_launch_file(_path(claim["openingClaimPath"]), claim["openingClaimSha256"])
    opening = parent.value()
    if set(opening) != _OPENING_KEYS or type(opening["schemaVersion"]) is not int \
            or opening["schemaVersion"] != 1 or opening["kind"] != "guided-opening-execution-claim" \
            or opening["scope"] != "private-opening-owned-execution-not-approval":
        raise ValueError("grade launch opening parent role is invalid")
    original = hold_launch_file(_path(opening["inputPath"]), _sha(opening["inputSha256"]))
    inputs = original.value()
    if set(inputs) != _INPUT_KEYS or type(inputs["schemaVersion"]) is not int or inputs["schemaVersion"] != 1 \
            or inputs["kind"] != "guided-opening-media-input" \
            or type(inputs["documents"]) is not dict or set(inputs["documents"]) != DOCUMENTS \
            or inputs["executionInputHash"] != digest({key: row for key, row in inputs.items() if key != "executionInputHash"}):
        raise ValueError("grade launch original opening input is invalid")
    opening_identity(opening, inputs, (original.path, original.sha256, _path(opening["outputRoot"])))
    if any(opening[key] != inputs[key] for key in ("executionInputHash", "executionId")) \
            or not same_read_metadata(opening["runtime"], hold_read_metadata(claim["runtime"])):
        raise ValueError("grade launch original opening/runtime differs from preclaim")
    snapshot = str(_path(inputs["pipeline"]["snapshotRoot"]))
    verify_runtime_controls(claim["runtime"], snapshot)
    return (grade, parent, original), snapshot


def _command_matches(held: HeldGradeLaunch, runtime: DockerRuntime, command: list[str]) -> None:
    """Compare the unchanged policy's actual builder, never a second argv recipe."""
    from headless.grade_observation_policy import _launch_command

    expected, _worker_sha = _launch_command(runtime, (held.directory, held.name, held.source), held.request)
    if not same_read_metadata(command, hold_read_metadata(expected)):
        raise RuntimeError("grade launch command differs from original source/request/name")


@dataclass
class HeldGradeLaunch:
    """One in-memory preclaimed launch lifetime; no JSON can resume this object."""

    owner: OwnedGradeLaunch
    source: str
    request: dict
    directory: Path
    _claim: dict = field(init=False, repr=False)
    _files: tuple = field(init=False, repr=False)
    _snapshot: str = field(init=False, repr=False)
    _fixed: tuple = field(init=False, repr=False)
    _state: str = field(default="held", init=False, repr=False)
    _runtime_command: tuple | None = field(default=None, init=False, repr=False)
    _records: tuple = field(default=(), init=False, repr=False)

    @property
    def name(self) -> str:
        """Return only the original job-derived exact container name."""
        return self._claim["containerName"]

    @property
    def deadline(self) -> float:
        """Expose the same original deadline, never a fresh request clock."""
        return self.owner.deadline

    def _arguments(self) -> tuple:
        """Retain all original metadata, references, directory and source identity."""
        return (id(self.owner), self.owner.binding(), id(type(self.source)), self.source, id(self.request),
                self.request, type(self.directory).__name__, str(self.directory), self._claim,
                self._snapshot, tuple((id(row), row.raw, str(row.path), row.identity, row.parents) for row in self._files))

    def _assert(self) -> None:
        """Check detached originals and every raw parent around each callback."""
        if self.owner.binding() != self.owner._original or not same_read_metadata(self._arguments(), self._fixed[0]):
            raise RuntimeError("grade launch original arguments changed")
        if directory_identity(self.directory) != self._fixed[1] \
                or directory_identity(Path(self.source).parent) != self._fixed[2] \
                or snapshot_stat_identity(os.lstat(self.source)) != self._fixed[3]:
            raise RuntimeError("grade launch original directory/source identity changed")
        for row in self._files:
            row.check()
        for row, expected in self._records:
            current = (id(row), str(row.path), row.raw, row.identity, row.parents)
            if not same_read_metadata(current, expected):
                raise RuntimeError("grade launch original publication binding changed")
            row.check()
        if self._runtime_command is not None and not same_read_metadata(
                self._runtime_command[:2], self._runtime_command[2]):
            raise RuntimeError("grade launch actual runtime/command changed")

    def check(self) -> None:
        """Use the original guard and cutoff without launching or decoding."""
        self._assert()
        require_time(self.deadline)
        self.owner.guard()
        self._assert()
        verify_runtime_controls(self._claim["runtime"], self._snapshot)
        require_time(self.deadline)

    def before_launch(self, runtime: DockerRuntime, command: list[str]) -> str:
        """Persist the prelaunch record once before the policy enters Docker."""
        if self._state != "held":
            raise RuntimeError("grade launch intent cannot be reused")
        self._state = "publishing-intent"
        self._runtime_command = (runtime, command, hold_read_metadata((runtime, command)))
        self.check()
        controls = self._claim["runtime"]
        if type(runtime) is not DockerRuntime or (runtime.docker, runtime.socket, runtime.image_id, runtime.user_id) \
                != tuple(controls[key] for key in ("dockerPath", "dockerSocketPath", "imageId", "userId")):
            raise RuntimeError("grade launch runtime differs from original controls")
        approval = bound_json(Path(controls["imageApprovalPath"]), controls["imageApprovalSha256"])
        if not same_read_metadata(runtime.approval, hold_read_metadata(approval)):
            raise RuntimeError("grade launch runtime approval changed")
        if type(command) is not list or not command or any(type(item) is not str for item in command):
            raise ValueError("grade launch command must be the actual fixed argv")
        _command_matches(self, runtime, command)
        record = {"schemaVersion": 1, "kind": "owned-grade-launch-intent", "claimSha256": self.owner.claim_sha256,
                  "containerName": self.name, "inputSha256": self._claim["inputSha256"],
                  "requestHash": digest(self.request), "runtimeHash": digest(controls), "launchCommandHash": digest(command)}
        self._publication = publish_launch_file(self.directory, "launch-intent.json", record)
        self._retain(self._publication)
        self.check()
        self._state = "intent-published"
        return self._publication.sha256

    def after_launch(self, container_id: str) -> None:
        """Retain an exact response before callbacks; failure still needs cleanup."""
        if self._state != "intent-published" or type(container_id) is not str or not _SHA.fullmatch(container_id):
            raise RuntimeError("grade launch response is not an exact new container ID")
        self._state = "publishing-response"
        self._publication.check()
        self._response = publish_launch_file(self.directory, "launch-response.json", {
            "schemaVersion": 1, "kind": "owned-grade-launch-response", "claimSha256": self.owner.claim_sha256,
            "launchIntentSha256": self._publication.sha256, "containerName": self.name, "containerId": container_id})
        self._retain(self._response)
        self.check()
        self._response.check()
        self._state = "response-published"

    def _retain(self, row: HeldLaunchFile) -> None:
        """Bind newly returned raw publication metadata before another callback."""
        value = (id(row), str(row.path), row.raw, row.identity, row.parents)
        self._records += ((row, hold_read_metadata(value)),)


def _metadata_arguments(owner: OwnedGradeLaunch, source: str, request: dict, directory: Path) -> tuple:
    """Retain exact entry arguments across all metadata and live identity reads."""
    if type(owner) is not OwnedGradeLaunch:
        raise ValueError("grade launch requires the original owned context")
    return (id(owner), id(owner._original), owner.binding(), id(request), request, source, str(directory))


def read_grade_launch_metadata(owner: OwnedGradeLaunch, source: str, request: dict,
                               directory: Path) -> tuple[dict, tuple[HeldLaunchFile, ...], str]:
    """Read data-only preclaim parents without creating or requiring executionDir."""
    original = hold_read_metadata(_metadata_arguments(owner, source, request, directory))
    if owner.binding() != owner._original:
        raise ValueError("grade launch requires the original owned context")
    require_time(owner.deadline)
    _path(source)
    if type(directory) is not type(Path()):
        raise ValueError("grade launch directory must be an exact Path")
    parent_identity = directory_identity(directory.parent)
    parsed = parse_request(request)
    claim = hold_launch_file(owner.claim_path, owner.claim_sha256)
    value = claim.value()
    _claim(value, source, parsed, directory)
    if owner.claim_path.is_relative_to(directory):
        raise ValueError("grade launch external preclaim cannot be inside execution")
    parents, snapshot = _parents(value)
    refs = (claim, *parents)
    for row in refs:
        row.check()
    final_parent = directory_identity(directory.parent)
    require_time(owner.deadline)
    current = _metadata_arguments(owner, source, request, directory)
    if not same_read_metadata(current, original) or owner.binding() != owner._original \
            or final_parent != parent_identity:
        raise RuntimeError("grade launch original metadata arguments changed during read")
    if not same_read_metadata(value, hold_read_metadata(claim.value())):
        raise RuntimeError("grade launch original claim projection changed during read")
    return value, refs, snapshot


def hold_grade_launch(owner: OwnedGradeLaunch, source: str, request: dict, directory: Path) -> HeldGradeLaunch:
    """Require actual empty execution and source identity before the live handle."""
    original = hold_read_metadata(_metadata_arguments(owner, source, request, directory))
    value, refs, snapshot = read_grade_launch_metadata(owner, source, request, directory)
    execution_identity = directory_identity(directory)
    if execution_identity[0][4] != os.geteuid() or stat.S_IMODE(execution_identity[0][3]) & 0o077 or next(directory.iterdir(), None) is not None:
        raise RuntimeError("grade launch requires an empty private owned execution directory")
    info = os.lstat(source)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_size <= 0:
        raise RuntimeError("grade launch source must be the original owned regular file")
    source_parent = directory_identity(Path(source).parent)
    if not same_read_metadata(_metadata_arguments(owner, source, request, directory), original):
        raise RuntimeError("grade launch original metadata arguments changed before live capture")
    held = HeldGradeLaunch(owner, source, request, directory)
    held._claim, held._files, held._snapshot = value, refs, snapshot
    held._fixed = (hold_read_metadata(held._arguments()), execution_identity,
                   source_parent, snapshot_stat_identity(info))
    held.check()
    if not same_read_metadata(_metadata_arguments(owner, source, request, directory), original):
        raise RuntimeError("grade launch original metadata arguments changed during live capture")
    return held
