"""Canonical non-authorizing report for build closure reobservation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from . import quality_receipt_json as wire

BuildClosureReobservationSchemaError = wire.QualityReceiptSchemaError
BUILD_CLOSURE_REOBSERVATION_STATUS = (
    "SOURCE_AND_TOOL_ENDPOINTS_REOBSERVED_NOT_EXECUTION_ATTESTED"
)

_TOP_KEYS = frozenset(
    "builds claims qualityPolicyId requestDigest "
    "runtimeCapabilityManifestSha256 schemaVersion scope sources "
    "status tools".split()
)
_BUILD_KEYS = frozenset("compositor render".split())
_SET_KEYS = frozenset("count setDigest".split())
_CLAIM_KEYS = frozenset(
    "callbackCompleted dynamicLibraryClosureVerified endpointMetadataStable "
    "exactSourceBytesReobserved exactToolBytesReobserved executionAuthorized "
    "executionReobserved processExecutionAttested publicationAuthorized "
    "runtimeVerified sourceRootDescriptorHeld toolInodeDescriptorsHeld".split()
)


@dataclass(frozen=True)
class BuildClosureSetV1:
    """Count and digest for one closed ordered observation set."""

    count: int
    set_digest: str


@dataclass(frozen=True)
class BuildClosureClaimsV1:
    """Narrow observation truths and authorities the report cannot grant."""

    callback_completed: bool
    exact_source_bytes_reobserved: bool
    exact_tool_bytes_reobserved: bool
    source_root_descriptor_held: bool
    tool_inode_descriptors_held: bool
    endpoint_metadata_stable: bool
    runtime_verified: bool
    dynamic_library_closure_verified: bool
    execution_reobserved: bool
    process_execution_attested: bool
    execution_authorized: bool
    publication_authorized: bool


@dataclass(frozen=True)
class BuildClosureReobservationReportV1:
    """Path-free proof of source/tool endpoint checks around a callback."""

    status: str
    scope: str
    request_digest: str
    quality_policy_id: str
    runtime_manifest_sha256: str
    compositor_build_digest: str
    render_build_digest: str
    sources: BuildClosureSetV1
    tools: BuildClosureSetV1
    claims: BuildClosureClaimsV1
    document_json: bytes


def encode_build_closure_document(value: object) -> bytes:
    """Encode one report or set value using its exact canonical JSON form."""
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")


def build_closure_set_digest(domain: bytes, rows: tuple[dict, ...]) -> str:
    """Hash an ordered closed row set without exposing its paths in reports."""
    raw = encode_build_closure_document(list(rows))
    return hashlib.sha256(domain + raw).hexdigest()


def _closed_set(value: object, label: str) -> BuildClosureSetV1:
    row = wire.exact(value, _SET_KEYS, label)
    count = row["count"]
    if type(count) is not int or count <= 0:
        raise BuildClosureReobservationSchemaError(f"{label} count is invalid")
    return BuildClosureSetV1(
        count, wire.digest(row["setDigest"], f"{label} digest")
    )


def _claims(value: object) -> BuildClosureClaimsV1:
    row = wire.exact(value, _CLAIM_KEYS, "build closure claims")
    expected = {
        "callbackCompleted": True,
        "dynamicLibraryClosureVerified": False,
        "endpointMetadataStable": True,
        "exactSourceBytesReobserved": True,
        "exactToolBytesReobserved": True,
        "executionAuthorized": False,
        "executionReobserved": False,
        "processExecutionAttested": False,
        "publicationAuthorized": False,
        "runtimeVerified": False,
        "sourceRootDescriptorHeld": True,
        "toolInodeDescriptorsHeld": True,
    }
    if row != expected or any(type(item) is not bool for item in row.values()):
        raise BuildClosureReobservationSchemaError(
            "build closure report overclaims authority"
        )
    return BuildClosureClaimsV1(
        row["callbackCompleted"],
        row["exactSourceBytesReobserved"],
        row["exactToolBytesReobserved"],
        row["sourceRootDescriptorHeld"],
        row["toolInodeDescriptorsHeld"],
        row["endpointMetadataStable"],
        row["runtimeVerified"],
        row["dynamicLibraryClosureVerified"],
        row["executionReobserved"],
        row["processExecutionAttested"],
        row["executionAuthorized"],
        row["publicationAuthorized"],
    )


def parse_build_closure_reobservation_report_v1(
    raw: object,
) -> BuildClosureReobservationReportV1:
    """Parse the exact path-free, non-authorizing observation report."""
    document = wire.canonical_document(raw, "build closure reobservation")
    wire.exact(document, _TOP_KEYS, "build closure reobservation")
    envelope = (
        type(document["schemaVersion"]),
        document["schemaVersion"],
        document["status"],
        document["scope"],
    )
    expected = (
        int,
        1,
        BUILD_CLOSURE_REOBSERVATION_STATUS,
        "synchronous-callback-endpoints",
    )
    if envelope != expected:
        raise BuildClosureReobservationSchemaError(
            "build closure reobservation envelope is invalid"
        )
    builds = wire.exact(document["builds"], _BUILD_KEYS, "build identities")
    return BuildClosureReobservationReportV1(
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
        wire.digest(builds["compositor"], "reobserved compositor build"),
        wire.digest(builds["render"], "reobserved render build"),
        _closed_set(document["sources"], "reobserved source set"),
        _closed_set(document["tools"], "reobserved tool set"),
        _claims(document["claims"]),
        raw,
    )


def validate_build_closure_reobservation_report_v1(value: object) -> None:
    """Reject mutated reports and hostile dataclass equality values."""
    valid = type(value) is BuildClosureReobservationReportV1
    valid = valid and type(getattr(value, "document_json", None)) is bytes
    if not valid:
        raise BuildClosureReobservationSchemaError(
            "build closure reobservation instance is invalid"
        )
    parsed = parse_build_closure_reobservation_report_v1(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise BuildClosureReobservationSchemaError(
            "build closure reobservation construction is invalid"
        )
