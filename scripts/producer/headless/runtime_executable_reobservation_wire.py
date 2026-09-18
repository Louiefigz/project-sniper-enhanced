"""Canonical, explicitly non-authorizing executable reobservation report."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass

from . import quality_receipt_json as wire

RuntimeExecutableReobservationSchemaError = wire.QualityReceiptSchemaError

EXECUTABLE_REOBSERVATION_STATUS = (
    "EXECUTABLE_BYTES_AND_INODES_REOBSERVED_NOT_EXECUTION_ATTESTED"
)

_TOP_KEYS = frozenset(
    "claims qualityPolicyId requestDigest runtimeCapabilityManifestSha256 "
    "schemaVersion scope status tools".split()
)
_TOOL_SET_KEYS = frozenset("ffmpeg ffprobe".split())
_TOOL_KEYS = frozenset(
    "ctimeNs device gid inode linkCount mode mtimeNs path sha256 sizeBytes uid".split()
)
_CLAIM_KEYS = frozenset(
    "callbackCompleted dynamicLibraryClosureVerified exactExecutableBytesReobserved "
    "executionAuthorized executionReobserved inodeSnapshotsStable "
    "processExecutionAttested publicationAuthorized qualityMeasurementsReobserved "
    "runtimeVerified".split()
)


@dataclass(frozen=True)
class RuntimeExecutableSnapshotV1:
    """Exact bytes and inode metadata for one held executable descriptor."""

    path: str
    sha256: str
    size_bytes: int
    device: int
    inode: int
    mode: int
    link_count: int
    uid: int
    gid: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class RuntimeExecutableClaimsV1:
    """Narrow true claims and explicit authorities this report cannot supply."""

    callback_completed: bool
    exact_executable_bytes_reobserved: bool
    inode_snapshots_stable: bool
    runtime_verified: bool
    dynamic_library_closure_verified: bool
    execution_reobserved: bool
    process_execution_attested: bool
    quality_measurements_reobserved: bool
    execution_authorized: bool
    publication_authorized: bool


@dataclass(frozen=True)
class RuntimeExecutableReobservationReportV1:
    """Canonical proof of endpoint checks across one synchronous callback."""

    status: str
    scope: str
    request_digest: str
    quality_policy_id: str
    runtime_capability_manifest_sha256: str
    ffmpeg: RuntimeExecutableSnapshotV1
    ffprobe: RuntimeExecutableSnapshotV1
    claims: RuntimeExecutableClaimsV1
    document_json: bytes


def _path(value: object) -> str:
    valid = (
        type(value) is str
        and value
        and "\0" not in value
        and "\\" not in value
        and not any(
            ord(character) < 32 or ord(character) == 127 for character in value
        )
        and os.path.isabs(value)
        and os.path.normpath(value) == value
        and unicodedata.normalize("NFC", value) == value
    )
    if not valid:
        raise RuntimeExecutableReobservationSchemaError(
            "reobserved executable path is invalid"
        )
    return value


def _integer(value: object, label: str, positive: bool = False) -> int:
    valid = type(value) is int and value >= int(positive)
    if not valid or (positive and value == 0):
        raise RuntimeExecutableReobservationSchemaError(f"{label} is invalid")
    return value


def _tool(value: object) -> RuntimeExecutableSnapshotV1:
    row = wire.exact(value, _TOOL_KEYS, "reobserved executable")
    return RuntimeExecutableSnapshotV1(
        _path(row["path"]),
        wire.digest(row["sha256"], "reobserved executable digest"),
        _integer(row["sizeBytes"], "reobserved executable size", True),
        _integer(row["device"], "reobserved executable device"),
        _integer(row["inode"], "reobserved executable inode", True),
        _integer(row["mode"], "reobserved executable mode", True),
        _integer(row["linkCount"], "reobserved executable link count", True),
        _integer(row["uid"], "reobserved executable owner"),
        _integer(row["gid"], "reobserved executable group"),
        _integer(row["mtimeNs"], "reobserved executable mtime"),
        _integer(row["ctimeNs"], "reobserved executable ctime"),
    )


def _claims(value: object) -> RuntimeExecutableClaimsV1:
    row = wire.exact(value, _CLAIM_KEYS, "executable reobservation claims")
    actual = tuple(row[key] for key in sorted(_CLAIM_KEYS))
    if any(type(item) is not bool for item in actual):
        raise RuntimeExecutableReobservationSchemaError(
            "executable reobservation claims are not booleans"
        )
    expected = {
        "callbackCompleted": True,
        "dynamicLibraryClosureVerified": False,
        "exactExecutableBytesReobserved": True,
        "executionAuthorized": False,
        "executionReobserved": False,
        "inodeSnapshotsStable": True,
        "processExecutionAttested": False,
        "publicationAuthorized": False,
        "qualityMeasurementsReobserved": False,
        "runtimeVerified": False,
    }
    if row != expected:
        raise RuntimeExecutableReobservationSchemaError(
            "executable reobservation overclaims authority"
        )
    return RuntimeExecutableClaimsV1(
        row["callbackCompleted"],
        row["exactExecutableBytesReobserved"],
        row["inodeSnapshotsStable"],
        row["runtimeVerified"],
        row["dynamicLibraryClosureVerified"],
        row["executionReobserved"],
        row["processExecutionAttested"],
        row["qualityMeasurementsReobserved"],
        row["executionAuthorized"],
        row["publicationAuthorized"],
    )


def parse_runtime_executable_reobservation_report_v1(
    raw: object,
) -> RuntimeExecutableReobservationReportV1:
    """Parse only the exact callback-lifetime, non-authorizing report."""
    document = wire.canonical_document(raw, "runtime executable reobservation")
    wire.exact(document, _TOP_KEYS, "runtime executable reobservation")
    envelope = (
        type(document["schemaVersion"]),
        document["schemaVersion"],
        document["status"],
        document["scope"],
    )
    expected = (
        int,
        1,
        EXECUTABLE_REOBSERVATION_STATUS,
        "synchronous-callback-endpoints",
    )
    if envelope != expected:
        raise RuntimeExecutableReobservationSchemaError(
            "runtime executable reobservation envelope is invalid"
        )
    tools = wire.exact(
        document["tools"], _TOOL_SET_KEYS, "reobserved tool set"
    )
    ffmpeg, ffprobe = _tool(tools["ffmpeg"]), _tool(tools["ffprobe"])
    if ffmpeg.path == ffprobe.path or ffmpeg.sha256 == ffprobe.sha256:
        raise RuntimeExecutableReobservationSchemaError(
            "reobserved executable roles alias"
        )
    if (ffmpeg.device, ffmpeg.inode) == (ffprobe.device, ffprobe.inode):
        raise RuntimeExecutableReobservationSchemaError(
            "reobserved executable inodes alias"
        )
    return RuntimeExecutableReobservationReportV1(
        document["status"],
        document["scope"],
        wire.digest(document["requestDigest"], "reobserved request digest"),
        wire.digest(
            document["qualityPolicyId"], "reobserved quality policy ID"
        ),
        wire.digest(
            document["runtimeCapabilityManifestSha256"],
            "reobserved runtime manifest digest",
        ),
        ffmpeg,
        ffprobe,
        _claims(document["claims"]),
        raw,
    )


def validate_runtime_executable_reobservation_report_v1(value: object) -> None:
    """Reject mutated fields, hostile equality, and non-canonical report bytes."""
    valid = type(value) is RuntimeExecutableReobservationReportV1
    valid = valid and type(getattr(value, "document_json", None)) is bytes
    if not valid:
        raise RuntimeExecutableReobservationSchemaError(
            "runtime executable reobservation instance is invalid"
        )
    parsed = parse_runtime_executable_reobservation_report_v1(
        value.document_json
    )
    if not wire.same_typed_value(value, parsed):
        raise RuntimeExecutableReobservationSchemaError(
            "runtime executable reobservation construction is invalid"
        )
