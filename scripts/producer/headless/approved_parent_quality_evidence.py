"""Public exact parsers for approved-parent deterministic MP4 evidence."""

from __future__ import annotations

from collections.abc import Callable

from . import quality_receipt_json as wire
from .quality_effect_evidence_wire import parse_effect_proof_v1
from .quality_audit_evidence_wire import (
    parse_audit_b_receipt_v1,
    quality_evidence_set_digest,
)
from .quality_evidence_types import (
    ApprovedParentQualityEvidenceV1,
    AuditBReceiptV1,
    EffectProofV1,
    FullDecodeProofV1,
)
from .quality_evidence_wire import (
    QualityEvidenceSchemaError,
    parse_full_decode_proof_v1,
)


def _validate_instance(
    value: object,
    expected: type,
    parser: Callable[[object], object],
    label: str,
) -> None:
    document_json = getattr(value, "document_json", None)
    if type(value) is not expected or type(document_json) is not bytes:
        raise QualityEvidenceSchemaError(f"{label} instance is invalid")
    parsed = parser(document_json)
    if not wire.same_typed_value(value, parsed):
        raise QualityEvidenceSchemaError(f"{label} direct construction is invalid")


def validate_full_decode_proof_v1(value: object) -> None:
    """Reject direct construction or mutation outside exact decode bytes."""
    _validate_instance(
        value, FullDecodeProofV1, parse_full_decode_proof_v1, "full-decode proof"
    )


def validate_effect_proof_v1(value: object) -> None:
    """Reject direct construction or mutation outside exact effect bytes."""
    _validate_instance(value, EffectProofV1, parse_effect_proof_v1, "effect proof")


def validate_audit_b_receipt_v1(value: object) -> None:
    """Reject direct construction or mutation outside exact terminal-audit bytes."""
    _validate_instance(
        value, AuditBReceiptV1, parse_audit_b_receipt_v1, "Audit-B receipt"
    )


def parse_approved_parent_quality_evidence_v1(
    full_decode_json: object, effect_proof_json: object, audit_json: object
) -> ApprovedParentQualityEvidenceV1:
    """Parse the acyclic independent-evidence then terminal-audit set."""
    return ApprovedParentQualityEvidenceV1(
        parse_full_decode_proof_v1(full_decode_json),
        parse_effect_proof_v1(effect_proof_json),
        parse_audit_b_receipt_v1(audit_json),
    )


def validate_approved_parent_quality_evidence_v1(value: object) -> None:
    """Revalidate the complete evidence set and its terminal causal edges."""
    if type(value) is not ApprovedParentQualityEvidenceV1:
        raise QualityEvidenceSchemaError("quality evidence set is invalid")
    validate_full_decode_proof_v1(value.full_decode)
    validate_effect_proof_v1(value.effect_proof)
    validate_audit_b_receipt_v1(value.audit)
    expected = quality_evidence_set_digest(
        value.audit.full_decode, value.audit.effect_proof
    )
    if value.audit.evidence_set_digest != expected:
        raise QualityEvidenceSchemaError("quality evidence set is inconsistent")


__all__ = [
    "ApprovedParentQualityEvidenceV1",
    "AuditBReceiptV1",
    "EffectProofV1",
    "FullDecodeProofV1",
    "QualityEvidenceSchemaError",
    "parse_approved_parent_quality_evidence_v1",
    "parse_audit_b_receipt_v1",
    "parse_effect_proof_v1",
    "parse_full_decode_proof_v1",
    "quality_evidence_set_digest",
    "validate_approved_parent_quality_evidence_v1",
    "validate_audit_b_receipt_v1",
    "validate_effect_proof_v1",
    "validate_full_decode_proof_v1",
]
