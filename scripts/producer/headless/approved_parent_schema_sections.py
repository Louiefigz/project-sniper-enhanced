"""Typed nested sections for the approved-parent authority card."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from . import approved_parent_schema_values as values

ApprovedParentSchemaError = values.ApprovedParentSchemaError
ArtifactRefV1 = values.ArtifactRefV1
MediaRefV1 = values.MediaRefV1
GraphicAssetRefV1 = values.GraphicAssetRefV1
CriticArtifactRefV1 = values.CriticArtifactRefV1

_DIGEST = re.compile(r"[0-9a-f]{64}")
_AUTHORITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_IDENTITY_KEYS = frozenset(
    "attemptId authorityId generationId requestDigest unitId".split()
)
_POLICY_KEYS = frozenset(
    "executionPolicyId fallbackPolicyId qualityPolicyId repairPolicyId".split()
)
_PROVENANCE_ORDER = (
    "requestIdentity executionPolicy admissionInputs realizationInputs "
    "generationInputs sourceSnapshotManifest baseFingerprint operatorIntent "
    "cutApproval assetClosure runtimeCapabilityManifest repairState realization "
    "templateUsageApproval refitDisposition proxyDisposition"
)
_PLAN_KEYS = frozenset(
    "approvedPlanDigest artifact baseProjectionDigest contentHash".split()
)
_BASE_KEYS = frozenset("media planArtifact receipt timelineMap".split())
_GRAPHICS_KEYS = frozenset("assets preboundClips".split())
_OUTPUT_KEYS = frozenset(
    "assemblyReceipt cover coverProof final proxyDisposition".split()
)
_QUALITY_KEYS = frozenset(
    "audit critics effectProof finalApproval fullDecode qcReceipt".split()
)


@dataclass(frozen=True)
class ApprovedParentIdentityV1:
    authority_id: str
    generation_id: str
    attempt_id: str
    unit_id: str
    request_digest: str


@dataclass(frozen=True)
class ApprovedParentPoliciesV1:
    execution_policy_id: str
    repair_policy_id: str
    quality_policy_id: str
    fallback_policy_id: str


@dataclass(frozen=True)
class ApprovedParentProvenanceV1:
    request_identity: ArtifactRefV1
    execution_policy: ArtifactRefV1
    admission_inputs: ArtifactRefV1
    realization_inputs: ArtifactRefV1
    generation_inputs: ArtifactRefV1
    source_snapshot_manifest: ArtifactRefV1
    base_fingerprint: ArtifactRefV1
    operator_intent: ArtifactRefV1
    cut_approval: ArtifactRefV1
    asset_closure: ArtifactRefV1
    runtime_capability_manifest: ArtifactRefV1
    repair_state: ArtifactRefV1
    realization: ArtifactRefV1
    template_usage_approval: ArtifactRefV1
    refit_disposition: ArtifactRefV1
    proxy_disposition: ArtifactRefV1


@dataclass(frozen=True)
class ApprovedParentPlanV1:
    artifact: ArtifactRefV1
    approved_plan_digest: str
    content_hash: str
    base_projection_digest: str


@dataclass(frozen=True)
class ApprovedParentBaseV1:
    media: MediaRefV1
    plan_artifact: ArtifactRefV1
    receipt: ArtifactRefV1
    timeline_map: ArtifactRefV1


@dataclass(frozen=True)
class ApprovedParentGraphicsV1:
    prebound_clips: ArtifactRefV1
    assets: tuple[GraphicAssetRefV1, ...]


@dataclass(frozen=True)
class ApprovedParentOutputV1:
    final: MediaRefV1
    assembly_receipt: ArtifactRefV1
    cover: ArtifactRefV1
    cover_proof: ArtifactRefV1
    proxy_disposition: str


@dataclass(frozen=True)
class ApprovedParentQualityV1:
    audit: ArtifactRefV1
    full_decode: ArtifactRefV1
    effect_proof: ArtifactRefV1
    qc_receipt: ArtifactRefV1
    critics: tuple[CriticArtifactRefV1, ...]
    final_approval: ArtifactRefV1


def _exact(value: object, keys: frozenset[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise ApprovedParentSchemaError(f"{label} keys are invalid")
    return value


def _digest(label: str, value: object) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise ApprovedParentSchemaError(f"{label} must be lowercase SHA-256")
    return value


def _uuid(label: str, value: object) -> str:
    if type(value) is not str:
        raise ApprovedParentSchemaError(f"{label} must be a canonical UUID")
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise ApprovedParentSchemaError(f"{label} must be a canonical UUID") from exc
    if parsed != value:
        raise ApprovedParentSchemaError(f"{label} must use canonical UUID form")
    return value


def parse_identity(value: object) -> ApprovedParentIdentityV1:
    row = _exact(value, _IDENTITY_KEYS, "identity")
    authority = row["authorityId"]
    if type(authority) is not str or not _AUTHORITY.fullmatch(authority):
        raise ApprovedParentSchemaError("authority ID is invalid")
    return ApprovedParentIdentityV1(
        authority,
        _uuid("generation ID", row["generationId"]),
        _uuid("attempt ID", row["attemptId"]),
        _uuid("unit ID", row["unitId"]),
        _digest("request digest", row["requestDigest"]),
    )


def parse_policies(value: object) -> ApprovedParentPoliciesV1:
    row = _exact(value, _POLICY_KEYS, "policies")
    return ApprovedParentPoliciesV1(
        _digest("execution policy ID", row["executionPolicyId"]),
        _digest("repair policy ID", row["repairPolicyId"]),
        _digest("quality policy ID", row["qualityPolicyId"]),
        _digest("fallback policy ID", row["fallbackPolicyId"]),
    )


def parse_provenance(value: object) -> ApprovedParentProvenanceV1:
    names = _PROVENANCE_ORDER.split()
    row = _exact(value, frozenset(names), "provenance")
    return ApprovedParentProvenanceV1(
        *(values.parse_artifact(row[name]) for name in names)
    )


def parse_plan(value: object) -> ApprovedParentPlanV1:
    row = _exact(value, _PLAN_KEYS, "plan")
    return ApprovedParentPlanV1(
        values.parse_artifact(row["artifact"]),
        _digest("approved plan digest", row["approvedPlanDigest"]),
        _digest("plan content hash", row["contentHash"]),
        _digest("base projection digest", row["baseProjectionDigest"]),
    )


def parse_base(value: object) -> ApprovedParentBaseV1:
    row = _exact(value, _BASE_KEYS, "base")
    return ApprovedParentBaseV1(
        values.parse_media(row["media"]),
        values.parse_artifact(row["planArtifact"]),
        values.parse_artifact(row["receipt"]),
        values.parse_artifact(row["timelineMap"]),
    )


def parse_graphics(value: object) -> ApprovedParentGraphicsV1:
    row = _exact(value, _GRAPHICS_KEYS, "graphics")
    return ApprovedParentGraphicsV1(
        values.parse_artifact(row["preboundClips"]),
        values.parse_graphics(row["assets"]),
    )


def parse_output(value: object) -> ApprovedParentOutputV1:
    row = _exact(value, _OUTPUT_KEYS, "output")
    if row["proxyDisposition"] != "omitted-by-policy":
        raise ApprovedParentSchemaError("output proxy disposition is invalid")
    return ApprovedParentOutputV1(
        values.parse_media(row["final"]),
        values.parse_artifact(row["assemblyReceipt"]),
        values.parse_artifact(row["cover"]),
        values.parse_artifact(row["coverProof"]),
        row["proxyDisposition"],
    )


def parse_quality(value: object) -> ApprovedParentQualityV1:
    row = _exact(value, _QUALITY_KEYS, "quality")
    return ApprovedParentQualityV1(
        values.parse_artifact(row["audit"]),
        values.parse_artifact(row["fullDecode"]),
        values.parse_artifact(row["effectProof"]),
        values.parse_artifact(row["qcReceipt"]),
        values.parse_critics(row["critics"]),
        values.parse_artifact(row["finalApproval"]),
    )
