"""Pure staged color metadata joins, never file, source, owner or cleanup authority.

Callers must authenticate raw sidecar/reservation bytes and the original opening
claim separately. Declared group endpoints are not actual source frame counts.
No filesystem operation, decoder, timer or live execution object is used here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import PurePosixPath
import re
from uuid import UUID

from color.grade_contract import _groups, _text, closed, identifier, integer
from color.grade_observation_profile import observation_profile
from cross_runtime_canonical_json import canonical_compact_json
from cut_preview_io import digest

_SIDECAR = {"schemaVersion", "kind", "scope", "opening", "producerDir", "sourceColor",
            "expected", "reservation", "jobs", "executable", "gradeApplicable", "deliveryApproved"}
_RESERVATION = {"schemaVersion", "kind", "scope", "producerDir", "opening", "sourceColorHash",
                "sidecarPath", "ownerPid", "runtime", "jobs"}
_OPENING = {"claimPath", "claimSha256", "inputPath", "inputSha256", "executionId", "executionInputHash",
            "clockHash", "generationStartedAt", "budgetAdmissionHash", "beforeJournalHash"}
_PLAN = {"sourceId", "jobId", "directory", "inputPath", "implementationPath", "launchClaimPath", "executionDir", "containerName"}
_REFERENCES = {"input": "inputPath", "implementation": "implementationPath", "launchClaim": "launchClaimPath"}
_RUNTIME = {"dockerPath", "dockerSha256", "dockerSocketPath", "dockerSocketDevice", "dockerSocketInode",
            "imageId", "userId", "imageApprovalPath", "imageApprovalSha256", "runtimeRepoRoot"}
_DECLARATION = {"schemaVersion", "sourceId", "sourceProfile", "cameraProfile", "historyState", "transformHistory", "lightingGroups"}
_SHA = re.compile(r"[0-9a-f]{64}")


def _hash(value: object) -> str:
    """Require a literal raw or semantic digest without authenticating its origin."""
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError("source color staging SHA is malformed")
    return value


def _path(value: object) -> PurePosixPath:
    """Check spelling only; future execution directories need not exist."""
    if type(value) is not str or not 1 < len(value) <= 4096 or not value.startswith("/") \
            or "\\" in value or any(ord(char) < 32 for char in value) \
            or any(part in {"", ".", ".."} for part in value.split("/")[1:]):
        raise ValueError("source color staging path is not canonical absolute POSIX")
    return PurePosixPath(value)


def _uuid(value: object, job: bool = False) -> str:
    """Jobs are v4; original opening identifiers retain the existing TS1..8 class."""
    if type(value) is not str:
        raise ValueError("source color staging UUID is malformed")
    parsed = UUID(value)
    if str(parsed) != value or parsed.version not in ({4} if job else range(1, 9)):
        raise ValueError("source color staging UUID version/spelling differs")
    return value


def _literal(row: dict, expected: dict) -> None:
    """Reject bool/int equality and every changed role or false authority flag."""
    if any(type(row[key]) is not type(value) or row[key] != value for key, value in expected.items()):
        raise ValueError("source color staging role, version or false flags differ")


def _reference(value: object, expected: PurePosixPath | None = None) -> dict:
    """Raw refs are data; value-only validation cannot prove these bytes exist."""
    row = closed(value, {"path", "sha256", "sizeBytes"}, "source color raw reference")
    file = _path(row["path"])
    if expected is not None and file != expected:
        raise ValueError("source color staging reference path differs")
    _hash(row["sha256"])
    integer(row["sizeBytes"], 1, 8 * 1024 ** 2)
    return row


def _timestamp(value: object) -> None:
    """Preserve exact UTC milliseconds without consulting or creating a clock."""
    if type(value) is not str or len(value) != 24 or not value.endswith("Z"):
        raise ValueError("source color original generation timestamp is malformed")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
        raise ValueError("source color original generation timestamp differs")


def _opening(value: object, producer: PurePosixPath) -> PurePosixPath:
    """Derive exact execution/sidecar paths from the held opening claim reference."""
    row = closed(value, _OPENING, "source color opening reference")
    claim = _path(row["claimPath"])
    relative = claim.relative_to(producer)
    parts = relative.parts
    if len(parts) != 5 or parts[0] != "guided-v2-operations" or parts[2] != "executions" \
            or parts[4] != "execution-claim.json" or _uuid(parts[3]) != _uuid(row["executionId"]):
        raise ValueError("source color opening claim path differs from its execution")
    _uuid(parts[1])
    if _path(row["inputPath"]) != claim.parent / "media-input/input.json":
        raise ValueError("source color original input path differs")
    for key in _OPENING - {"claimPath", "inputPath", "executionId", "generationStartedAt"}:
        _hash(row[key])
    _timestamp(row["generationStartedAt"])
    return claim.parent / "source-color/input.json"


def _runtime(value: object) -> None:
    """Mirror TS closed runtime shape only; existing runtime verification performs IO."""
    row = closed(value, _RUNTIME, "source color runtime controls")
    for key in ("dockerPath", "dockerSocketPath", "imageApprovalPath", "runtimeRepoRoot"):
        _path(row[key])
    for key in ("dockerSha256", "imageApprovalSha256"):
        _hash(row[key])
    for key in ("dockerSocketDevice", "dockerSocketInode"):
        if type(row[key]) is not str or re.fullmatch(r"0|[1-9][0-9]{0,63}", row[key]) is None:
            raise ValueError("source color runtime socket identity is malformed")
    if type(row["imageId"]) is not str or re.fullmatch(r"sha256:[a-f0-9]{64}", row["imageId"]) is None \
            or type(row["userId"]) is not str or re.fullmatch(r"[1-9][0-9]{0,9}:[1-9][0-9]{0,9}", row["userId"]) is None:
        raise ValueError("source color runtime image/user shape is malformed")


def _selection(value: object, source_id: str) -> None:
    """Validate declared shape using existing grade semantics, never invent a SourceBinding."""
    selected = closed(value, {"profile", "declaration"}, "source color selection")
    profile = observation_profile(selected["profile"])
    row = closed(selected["declaration"], _DECLARATION, "source color declaration")
    _literal(row, {"schemaVersion": profile.version, "sourceId": source_id})
    profiles, histories = (("bt709-sdr",), ("known",)) if profile.version == 1 else (("xvycc709", "unknown"), ("known", "unknown"))
    if type(row["sourceProfile"]) is not str or row["sourceProfile"] not in profiles \
            or type(row["historyState"]) is not str or row["historyState"] not in histories:
        raise ValueError("source color explicit profile/history declaration differs")
    if row["cameraProfile"] is not None:
        _text(row["cameraProfile"], 200, False)
    history = row["transformHistory"]
    if type(history) is not list or len(history) > 20:
        raise ValueError("source color declared history is unbounded")
    for item in history:
        _text(item, 500, False)
    groups = row["lightingGroups"]
    if type(groups) is not list or not 1 <= len(groups) <= 12 or type(groups[-1]) is not dict:
        raise ValueError("source color declared groups are malformed")
    if any(type(group) is not dict or type(group.get("intent")) is not str for group in groups):
        raise ValueError("source color declared group intent is not a literal string")
    # This endpoint validates contiguous DECLARED ranges only, not actual source count.
    endpoint = integer(groups[-1].get("endFrame"), 1, profile.max_frames)
    _groups(groups, endpoint)


def _source_color(value: object) -> dict:
    """Require explicit complete declarations; map order is not source occurrence order."""
    row = closed(value, {"schemaVersion", "declarations"}, "source color request")
    _literal(row, {"schemaVersion": 1})
    declarations = row["declarations"]
    if type(declarations) is not dict or not 1 <= len(declarations) <= 128:
        raise ValueError("source color declarations must cover 1..128 sources")
    for source_id, selected in declarations.items():
        _selection(selected, identifier(source_id))
    if len(canonical_compact_json(row).encode("utf-8")) > 4 * 1024 ** 2:
        raise ValueError("source color declaration transport exceeds its bound")
    return declarations


def _job(value: object, producer: PurePosixPath, staged: bool) -> dict:
    """Exact prospective path/name projection; neither files nor a process are observed."""
    row = closed(value, _PLAN | set(_REFERENCES) if staged else _PLAN, "source color staged job")
    identifier(row["sourceId"])
    job_id = _uuid(row["jobId"], True)
    directory = producer / ".sniper-grade-observations" / job_id
    expected = {"directory": directory, "inputPath": directory / "input.json", "implementationPath": directory / "implementation.json",
                "launchClaimPath": directory / "launch-claim.json", "executionDir": directory / "execution"}
    if any(_path(row[key]) != file for key, file in expected.items()) or type(row["containerName"]) is not str \
            or row["containerName"] != f"sniper-grade-observation-{job_id.replace('-', '')}":
        raise ValueError("source color job path/container name differs")
    if staged:
        for key, field in _REFERENCES.items():
            _reference(row[key], expected[field])
    return {key: row[key] for key in _PLAN}


def _jobs(sidecar: dict, reservation: dict, declarations: dict) -> None:
    """Join ordered plans and raw refs; repeated source IDs or UUIDs are never aliases."""
    jobs, planned = sidecar["jobs"], reservation["jobs"]
    if type(jobs) is not list or type(planned) is not list or not 1 <= len(jobs) <= 128 or len(jobs) != len(planned):
        raise ValueError("source color staged/planned job lists differ or exceed bounds")
    producer = _path(sidecar["producerDir"])
    projections = [_job(row, producer, True) for row in jobs]
    plans = [_job(row, producer, False) for row in planned]
    ids, uuids = [row["sourceId"] for row in projections], [row["jobId"] for row in projections]
    if len(set(ids)) != len(ids) or len(set(uuids)) != len(uuids) or set(ids) != set(declarations) or projections != plans:
        raise ValueError("source color exact source coverage/job order differs")


def validate_source_color_reservation(value: object) -> dict:
    """Return detached planned names only, even before any sidecar/job publication.

    Original PID and runtime are metadata, never process settlement or cleanup
    authority. The caller authenticates raw bytes and the original claim/hash.
    """
    row = closed(value, _RESERVATION, "source color reservation")
    _literal(row, {"schemaVersion": 2, "kind": "guided-source-color-reservation",
                   "scope": "reserved-grade-container-names-not-process-settlement-or-cleanup"})
    producer = _path(row["producerDir"])
    if _path(row["sidecarPath"]) != _opening(row["opening"], producer):
        raise ValueError("source color reservation belongs to another producer/sidecar")
    _hash(row["sourceColorHash"])
    integer(row["ownerPid"], 1, 2 ** 31 - 1)
    _runtime(row["runtime"])
    jobs = row["jobs"]
    if type(jobs) is not list or not 1 <= len(jobs) <= 128:
        raise ValueError("source color planned job lists differ or exceed bounds")
    plans = [_job(job, producer, False) for job in jobs]
    ids, uuids = [job["sourceId"] for job in plans], [job["jobId"] for job in plans]
    if len(set(ids)) != len(ids) or len(set(uuids)) != len(uuids):
        raise ValueError("source color exact source coverage/job order differs")
    return deepcopy(row)


def validate_source_color_staging(sidecar: object, reservation: object) -> dict:
    """Return detached checked metadata only; callers still authenticate every raw ref and owner."""
    row = closed(sidecar, _SIDECAR, "source color sidecar")
    reserved = validate_source_color_reservation(reservation)
    _literal(row, {"schemaVersion": 1, "kind": "guided-source-color-input", "scope": "private-source-observation-not-transform-or-approval",
                   "executable": False, "gradeApplicable": False, "deliveryApproved": False})
    producer = _path(row["producerDir"])
    sidecar_path = _opening(row["opening"], producer)
    if _path(reserved["producerDir"]) != producer or _path(reserved["sidecarPath"]) != sidecar_path:
        raise ValueError("source color reservation belongs to another producer/sidecar")
    _opening(reserved["opening"], producer)
    if reserved["opening"] != row["opening"]:
        raise ValueError("source color original opening references differ")
    reference = _reference(row["reservation"])
    if _path(reference["path"]).parts[-2:] != (".sniper-color-resource", "active.json"):
        raise ValueError("source color reservation reference is not the exact resource marker")
    expected = closed(row["expected"], {"planSha256", "manifestSha256", "projectSha256"}, "source color original parents")
    for value in expected.values():
        _hash(value)
    declarations = _source_color(row["sourceColor"])
    if _hash(reserved["sourceColorHash"]) != digest(row["sourceColor"]):
        raise ValueError("source color reservation lost its exact semantic request hash")
    _jobs(row, reserved, declarations)
    return deepcopy(row)
