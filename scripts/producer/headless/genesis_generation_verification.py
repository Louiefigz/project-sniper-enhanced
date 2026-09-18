"""Exact acyclic structural verification for the genesis R1 payload."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import approved_parent_schema_sections as sections
from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1
from .generation_schema import (
    GenerationCommitV1,
    GenerationManifestRowV1,
    parse_generation_commit,
)
from .genesis_approved_card import (
    GenesisOriginAuthorityV2,
    parse_genesis_origin_authority_v2,
)
from .genesis_generation_profile import (
    GENESIS_R1_PROFILE,
    verify_genesis_r1_generation_profile,
)

GenesisGenerationVerificationError = wire.QualityReceiptSchemaError
_DOMAIN = b"sniper-genesis-payload-manifest-v2\0"
_TOP_KEYS = frozenset(
    "approvedCard expectedParent identity origin payloadManifestDigest policies "
    "profile schemaVersion status".split()
)


@dataclass(frozen=True)
class GenesisGenerationVerificationV2:
    """Structural pass record that contains no runtime or publication claim."""

    status: str
    profile: str
    expected_parent: None
    identity: sections.ApprovedParentIdentityV1
    policies: sections.ApprovedParentPoliciesV1
    approved_card: ArtifactRefV1
    origin: GenesisOriginAuthorityV2
    payload_manifest_digest: str
    document_json: bytes


def _row_value(row: GenerationManifestRowV1) -> dict:
    return {
        "artifactClass": row.artifact_class,
        "path": row.path,
        "sha256": row.sha256,
        "sizeBytes": row.size_bytes,
    }


def genesis_payload_manifest_digest(rows: object) -> str:
    """Bind ordered genesis payload rows while excluding verification V2 itself."""
    valid = (
        type(rows) is tuple
        and bool(rows)
        and all(type(row) is GenerationManifestRowV1 for row in rows)
        and not any(row.artifact_class == "generation-verification-v2" for row in rows)
    )
    if not valid:
        raise GenesisGenerationVerificationError(
            "genesis verification payload rows are invalid or recursive"
        )
    ordered = sorted(rows, key=lambda row: row.path)
    from .operation_wire import canonical

    return hashlib.sha256(
        _DOMAIN + canonical([_row_value(row) for row in ordered])
    ).hexdigest()


def _identity_and_policies(document: dict) -> tuple:
    try:
        return (
            sections.parse_identity(document["identity"]),
            sections.parse_policies(document["policies"]),
        )
    except RuntimeError as exc:
        raise GenesisGenerationVerificationError(
            "genesis verification identity is invalid"
        ) from exc


def parse_genesis_generation_verification_v2(
    raw: object,
) -> GenesisGenerationVerificationV2:
    """Parse only exact canonical non-authorizing genesis verification bytes."""
    document = wire.canonical_document(raw, "genesis generation verification")
    wire.exact(document, _TOP_KEYS, "genesis generation verification")
    valid = (
        type(document["schemaVersion"]) is int
        and document["schemaVersion"] == 2
        and document["status"] == "structural-pass-runtime-unverified"
        and document["profile"] == GENESIS_R1_PROFILE
        and document["expectedParent"] is None
    )
    if not valid:
        raise GenesisGenerationVerificationError(
            "genesis verification envelope is invalid"
        )
    identity, policies = _identity_and_policies(document)
    return GenesisGenerationVerificationV2(
        document["status"],
        document["profile"],
        None,
        identity,
        policies,
        wire.artifact(document["approvedCard"]),
        parse_genesis_origin_authority_v2(document["origin"]),
        wire.digest(document["payloadManifestDigest"], "genesis payload digest"),
        raw,
    )


def _ref(row: GenerationManifestRowV1) -> ArtifactRefV1:
    return ArtifactRefV1(row.path, row.sha256, row.size_bytes)


def _sole_ref(commit: GenerationCommitV1, artifact_class: str) -> ArtifactRefV1:
    rows = tuple(row for row in commit.files if row.artifact_class == artifact_class)
    if len(rows) != 1:
        raise GenesisGenerationVerificationError(
            f"genesis verification class is not singular: {artifact_class}"
        )
    return _ref(rows[0])


def _expected_identity(commit: GenerationCommitV1) -> tuple:
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


def _actual_identity(value: GenesisGenerationVerificationV2) -> tuple:
    identity = value.identity
    policies = value.policies
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


def validate_genesis_generation_verification_v2(value: object, commit: object) -> None:
    """Bind verification V2 to the exact genesis commit class multiset."""
    valid = (
        type(value) is GenesisGenerationVerificationV2
        and type(commit) is GenerationCommitV1
    )
    if not valid:
        raise GenesisGenerationVerificationError(
            "genesis verification binding inputs are invalid"
        )
    parsed = parse_genesis_generation_verification_v2(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise GenesisGenerationVerificationError(
            "genesis verification construction is invalid"
        )
    reparsed_commit = parse_generation_commit(commit.document_json)
    if not wire.same_typed_value(commit, reparsed_commit):
        raise GenesisGenerationVerificationError(
            "genesis verification commit construction is invalid"
        )
    verify_genesis_r1_generation_profile(commit)
    payload = tuple(
        row
        for row in commit.files
        if row.artifact_class != "generation-verification-v2"
    )
    expected_refs = (
        _sole_ref(commit, "genesis-approved-card-v2"),
        _sole_ref(commit, "initialization-origin-receipt-v1"),
        _sole_ref(commit, "headless-operation-v1"),
        _sole_ref(commit, "initialization-snapshot-authority-v1"),
    )
    actual_refs = (
        value.approved_card,
        value.origin.receipt,
        value.origin.operation,
        value.origin.snapshot_authority,
    )
    matches = (
        _actual_identity(value) == _expected_identity(commit)
        and wire.same_typed_value(actual_refs, expected_refs)
        and value.payload_manifest_digest == genesis_payload_manifest_digest(payload)
    )
    if not matches:
        raise GenesisGenerationVerificationError(
            "genesis verification does not bind the commit"
        )
