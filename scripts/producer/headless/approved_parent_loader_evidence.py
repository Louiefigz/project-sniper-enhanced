"""Load and cross-bind exact decode, effect, and Audit-B evidence bytes."""

from __future__ import annotations

from dataclasses import dataclass

from .approved_parent_quality_evidence import (
    ApprovedParentQualityEvidenceV1,
    parse_approved_parent_quality_evidence_v1,
)
from .approved_parent_quality_evidence_binding import (
    ApprovedParentQualityEvidenceBindingV1,
    validate_approved_parent_quality_evidence_binding,
)
from .approved_parent_quality_receipts import ApprovedParentQualityRecordsV1
from .approved_parent_schema import ApprovedParentDescriptorV1
from .generation_artifact_store import GenerationArtifactStoreV1

_JSON_LIMIT = 16 * 1024 * 1024
SEALED_QUALITY_STATUS = "SEALED_CLAIMS_BOUND_NOT_RUNTIME_REOBSERVED"


@dataclass(frozen=True)
class ApprovedParentQualityEvidenceAuthorityV1:
    """Bound receipt claims that cannot alone authorize execution."""

    evidence: ApprovedParentQualityEvidenceV1
    status: str
    runtime_reobserved: bool
    execution_authorized: bool


def load_approved_parent_quality_evidence(
    store: GenerationArtifactStoreV1,
    descriptor: ApprovedParentDescriptorV1,
    records: ApprovedParentQualityRecordsV1,
    plan_json: bytes,
) -> ApprovedParentQualityEvidenceAuthorityV1:
    """Parse exact manifested evidence and bind every retained authority edge."""
    evidence = parse_approved_parent_quality_evidence_v1(
        store.read(descriptor.quality.full_decode, _JSON_LIMIT),
        store.read(descriptor.quality.effect_proof, _JSON_LIMIT),
        store.read(descriptor.quality.audit, _JSON_LIMIT),
    )
    binding = ApprovedParentQualityEvidenceBindingV1(
        descriptor,
        store.generation.commit,
        records.qc_receipt,
        plan_json,
        evidence,
    )
    validate_approved_parent_quality_evidence_binding(binding)
    return ApprovedParentQualityEvidenceAuthorityV1(
        evidence, SEALED_QUALITY_STATUS, False, False
    )
