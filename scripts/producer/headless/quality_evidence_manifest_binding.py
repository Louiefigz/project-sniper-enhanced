"""Exact generation-manifest and byte-role binding for quality evidence."""

from __future__ import annotations

import hashlib

from . import approved_parent_schema_values as descriptor_values
from .approved_parent_quality_receipts import QcReceiptWireV1
from .approved_parent_schema import ApprovedParentDescriptorV1
from .artifact_contract import ArtifactRefV1
from .generation_profile import verify_r0_generation_profile
from .generation_schema import GenerationCommitV1
from .quality_evidence_types import ApprovedParentQualityEvidenceV1


class QualityEvidenceManifestBindingError(RuntimeError):
    """Evidence paths, bytes, or manifest classes are inconsistent."""


def artifact_for_bytes(path: str, raw: bytes) -> ArtifactRefV1:
    """Build an exact ref for immutable already-read bytes."""
    return ArtifactRefV1(path, hashlib.sha256(raw).hexdigest(), len(raw))


def same_artifact(first: ArtifactRefV1, second: ArtifactRefV1) -> bool:
    """Compare parser-created refs through exact primitive fields."""
    return (
        first.relative_path,
        first.sha256,
        first.size_bytes,
    ) == (
        second.relative_path,
        second.sha256,
        second.size_bytes,
    )


def _require_ref(ref: ArtifactRefV1, artifact_class: str, groups: dict) -> None:
    matches = tuple(
        row
        for row in groups.get(artifact_class, ())
        if (row.path, row.sha256, row.size_bytes)
        == (ref.relative_path, ref.sha256, ref.size_bytes)
    )
    if len(matches) != 1:
        raise QualityEvidenceManifestBindingError(
            f"artifact role {artifact_class} is stale"
        )


def _receipt_refs(
    descriptor: ApprovedParentDescriptorV1,
    qc: QcReceiptWireV1,
    evidence: ApprovedParentQualityEvidenceV1,
) -> tuple[tuple[ArtifactRefV1, bytes, str], ...]:
    return (
        (
            descriptor.quality.full_decode,
            evidence.full_decode.document_json,
            "full-decode-proof-v1",
        ),
        (
            descriptor.quality.effect_proof,
            evidence.effect_proof.document_json,
            "effect-proof-v1",
        ),
        (
            descriptor.quality.audit,
            evidence.audit.document_json,
            "audit-b-receipt-v1",
        ),
        (
            descriptor.quality.qc_receipt,
            qc.document_json,
            "qc-receipt-v1",
        ),
    )


def _authority_refs(
    descriptor: ApprovedParentDescriptorV1,
    commit: GenerationCommitV1,
    groups: dict,
) -> None:
    descriptor_ref = artifact_for_bytes(
        commit.approved_parent_path, descriptor.document_json
    )
    fixed = (
        (descriptor_ref, "approved-parent-v1"),
        (descriptor.plan.artifact, "plan-v1"),
        (descriptor.output.final.artifact, "final-media-v1"),
        (descriptor.output.assembly_receipt, "assembly-receipt-v1"),
        (
            descriptor.provenance.runtime_capability_manifest,
            "runtime-capability-manifest-v1",
        ),
    )
    for ref, artifact_class in fixed:
        _require_ref(ref, artifact_class, groups)
    for asset in descriptor.graphics.assets:
        _require_ref(asset.media.artifact, "graphic-media-v1", groups)


def _raw_receipts(
    descriptor: ApprovedParentDescriptorV1,
    qc: QcReceiptWireV1,
    evidence: ApprovedParentQualityEvidenceV1,
    groups: dict,
) -> None:
    for expected, raw, artifact_class in _receipt_refs(descriptor, qc, evidence):
        actual = artifact_for_bytes(expected.relative_path, raw)
        if not same_artifact(actual, expected):
            raise QualityEvidenceManifestBindingError("receipt bytes are stale")
        _require_ref(actual, artifact_class, groups)


def _role_aliases(
    descriptor: ApprovedParentDescriptorV1,
    commit: GenerationCommitV1,
    qc: QcReceiptWireV1,
    evidence: ApprovedParentQualityEvidenceV1,
) -> None:
    role_refs = tuple(row[0] for row in _receipt_refs(descriptor, qc, evidence))
    role_digests = tuple(ref.sha256 for ref in role_refs)
    if len(set(role_digests)) != len(role_digests):
        raise QualityEvidenceManifestBindingError("quality receipt bytes alias")
    manifest_digests = tuple(row.sha256 for row in commit.files)
    if any(manifest_digests.count(digest) != 1 for digest in role_digests):
        raise QualityEvidenceManifestBindingError("receipt role bytes alias")
    descriptor_digest = hashlib.sha256(descriptor.document_json).hexdigest()
    if descriptor_digest in role_digests:
        raise QualityEvidenceManifestBindingError("receipt aliases authority card")
    refs = descriptor_values.artifact_refs(descriptor)
    if any(sum(ref.sha256 == digest for ref in refs) != 1 for digest in role_digests):
        raise QualityEvidenceManifestBindingError("receipt aliases another role")


def validate_quality_evidence_manifest_binding(
    descriptor: ApprovedParentDescriptorV1,
    commit: GenerationCommitV1,
    qc: QcReceiptWireV1,
    evidence: ApprovedParentQualityEvidenceV1,
) -> None:
    """Bind authority, evidence bytes, and every consumed role to R0 classes."""
    try:
        groups = verify_r0_generation_profile(commit)
    except RuntimeError as exc:
        raise QualityEvidenceManifestBindingError("commit profile is invalid") from exc
    _authority_refs(descriptor, commit, groups)
    _raw_receipts(descriptor, qc, evidence, groups)
    _role_aliases(descriptor, commit, qc, evidence)
