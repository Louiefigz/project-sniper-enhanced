"""Exact structural verification V2 for a versioned quality-pass generation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import approved_parent_schema_sections as sections
from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1
from .generation_schema import GenerationCommitV1, GenerationManifestRowV1
from .operation_wire import canonical, parse_parent
from .repair_intent import ParentRefV1
from .versioned_parent_authority import ParentAuthorityV2, parse_parent_authority_v2
from .versioned_quality_pass_profile import (
    QUALITY_PASS_R1_PROFILE,
    verify_quality_pass_r1_profile,
)

QualityPassGenerationVerificationV2Error = wire.QualityReceiptSchemaError
_DOMAIN = b"sniper-quality-pass-payload-manifest-v2\0"
_TOP_KEYS = frozenset(
    "approvedCard assemblyReceipt expectedParent identity parentAuthority "
    "payloadManifestDigest policies profile schemaVersion status".split()
)


@dataclass(frozen=True)
class QualityPassGenerationVerificationV2:
    """Non-authorizing payload binding for one quality-pass V2 commit."""

    status: str
    profile: str
    expected_parent: ParentRefV1
    identity: sections.ApprovedParentIdentityV1
    policies: sections.ApprovedParentPoliciesV1
    approved_card: ArtifactRefV1
    assembly_receipt: ArtifactRefV1
    parent_authority: ParentAuthorityV2
    payload_manifest_digest: str
    document_json: bytes


def _row_document(row: GenerationManifestRowV1) -> dict:
    return {
        "artifactClass": row.artifact_class,
        "path": row.path,
        "sha256": row.sha256,
        "sizeBytes": row.size_bytes,
    }


def quality_pass_payload_manifest_digest(rows: object) -> str:
    """Bind every ordered payload row except verification V2 itself."""
    valid = (
        type(rows) is tuple
        and bool(rows)
        and all(type(row) is GenerationManifestRowV1 for row in rows)
        and not any(
            row.artifact_class == "quality-pass-generation-verification-v2"
            for row in rows
        )
    )
    if not valid:
        raise QualityPassGenerationVerificationV2Error(
            "quality-pass verification rows are invalid or recursive"
        )
    ordered = sorted(rows, key=lambda row: row.path)
    raw = canonical([_row_document(row) for row in ordered])
    return hashlib.sha256(_DOMAIN + raw).hexdigest()


def _identity(document: dict) -> tuple:
    try:
        return (
            sections.parse_identity(document["identity"]),
            sections.parse_policies(document["policies"]),
        )
    except RuntimeError as exc:
        raise QualityPassGenerationVerificationV2Error(
            "quality-pass verification identity is invalid"
        ) from exc


def parse_quality_pass_generation_verification_v2(
    raw: object,
) -> QualityPassGenerationVerificationV2:
    """Parse exact canonical structural verification V2 bytes."""
    document = wire.canonical_document(raw, "quality-pass verification V2")
    wire.exact(document, _TOP_KEYS, "quality-pass verification V2")
    valid = (
        type(document["schemaVersion"]) is int
        and document["schemaVersion"] == 2
        and document["status"] == "structural-pass-runtime-unverified"
        and document["profile"] == QUALITY_PASS_R1_PROFILE
    )
    if not valid:
        raise QualityPassGenerationVerificationV2Error(
            "quality-pass verification envelope is invalid"
        )
    identity, policies = _identity(document)
    return QualityPassGenerationVerificationV2(
        document["status"],
        document["profile"],
        parse_parent(document["expectedParent"]),
        identity,
        policies,
        wire.artifact(document["approvedCard"]),
        wire.artifact(document["assemblyReceipt"]),
        parse_parent_authority_v2(document["parentAuthority"]),
        wire.digest(document["payloadManifestDigest"], "quality-pass payload digest"),
        raw,
    )


def _sole_ref(commit: GenerationCommitV1, artifact_class: str) -> ArtifactRefV1:
    rows = tuple(row for row in commit.files if row.artifact_class == artifact_class)
    if len(rows) != 1:
        raise QualityPassGenerationVerificationV2Error(
            f"quality-pass verification class is not singular: {artifact_class}"
        )
    row = rows[0]
    return ArtifactRefV1(row.path, row.sha256, row.size_bytes)


def _identity_tuple(value: QualityPassGenerationVerificationV2) -> tuple:
    identity, policies = value.identity, value.policies
    return (
        identity.authority_id,
        identity.generation_id,
        identity.attempt_id,
        identity.unit_id,
        identity.request_digest,
        policies.execution_policy_id,
        policies.repair_policy_id,
        policies.quality_policy_id,
        policies.fallback_policy_id,
    )


def _commit_tuple(commit: GenerationCommitV1) -> tuple:
    return (
        commit.authority_id,
        commit.generation_id,
        commit.attempt_id,
        commit.unit_id,
        commit.request_digest,
        commit.execution_policy_id,
        commit.repair_policy_id,
        commit.quality_policy_id,
        commit.fallback_policy_id,
    )


def validate_quality_pass_generation_verification_v2(
    value: object, commit: object
) -> None:
    """Bind structural verification V2 to one exact quality-pass commit."""
    valid = (
        type(value) is QualityPassGenerationVerificationV2
        and type(commit) is GenerationCommitV1
    )
    if not valid:
        raise QualityPassGenerationVerificationV2Error(
            "quality-pass verification inputs are invalid"
        )
    parsed = parse_quality_pass_generation_verification_v2(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise QualityPassGenerationVerificationV2Error(
            "quality-pass verification construction is invalid"
        )
    verify_quality_pass_r1_profile(commit)
    payload = tuple(
        row
        for row in commit.files
        if row.artifact_class != "quality-pass-generation-verification-v2"
    )
    actual_refs = (value.approved_card, value.assembly_receipt)
    expected_refs = (
        _sole_ref(commit, "quality-pass-approved-card-v2"),
        _sole_ref(commit, "assembly-receipt-v2"),
    )
    matches = (
        wire.same_typed_value(value.expected_parent, commit.expected_parent)
        and _identity_tuple(value) == _commit_tuple(commit)
        and wire.same_typed_value(actual_refs, expected_refs)
        and value.payload_manifest_digest
        == quality_pass_payload_manifest_digest(payload)
    )
    if not matches:
        raise QualityPassGenerationVerificationV2Error(
            "quality-pass verification does not bind the commit"
        )
