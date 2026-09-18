"""Byte-role and semantic binding for approved-parent quality evidence."""

from __future__ import annotations

from dataclasses import dataclass

from fingerprints import plan_content_hash

from . import quality_receipt_json as wire
from .approved_parent_quality_evidence import (
    ApprovedParentQualityEvidenceV1,
    parse_approved_parent_quality_evidence_v1,
)
from .approved_parent_quality_receipts import (
    QcReceiptWireV1,
    parse_qc_receipt_v1,
)
from .approved_parent_schema import (
    ApprovedParentDescriptorV1,
    parse_approved_parent_descriptor,
)
from .generation_schema import GenerationCommitV1, parse_generation_commit
from .quality_evidence_manifest_binding import (
    QualityEvidenceManifestBindingError,
    artifact_for_bytes,
    same_artifact,
    validate_quality_evidence_manifest_binding,
)
from .quality_evidence_semantics import (
    QualityEvidenceSemanticError,
    validate_quality_evidence_semantics,
)
from .quality_policy import current_deterministic_quality_policy
from .repair_intent import approved_plan_digest


class ApprovedParentQualityEvidenceBindingError(RuntimeError):
    """Quality evidence bytes or roles contradict generation authority."""


@dataclass(frozen=True)
class ApprovedParentQualityEvidenceBindingV1:
    """Loader-ready immutable inputs for evidence cross-binding."""

    descriptor: ApprovedParentDescriptorV1
    commit: GenerationCommitV1
    qc_receipt: QcReceiptWireV1
    plan_json: bytes
    evidence: ApprovedParentQualityEvidenceV1


@dataclass(frozen=True)
class _ValidatedBindingV1:
    descriptor: ApprovedParentDescriptorV1
    commit: GenerationCommitV1
    qc_receipt: QcReceiptWireV1
    plan: dict
    plan_json: bytes
    evidence: ApprovedParentQualityEvidenceV1


def _parsed_descriptor(value: object) -> ApprovedParentDescriptorV1:
    if type(value) is not ApprovedParentDescriptorV1:
        raise ApprovedParentQualityEvidenceBindingError("descriptor is invalid")
    try:
        parsed = parse_approved_parent_descriptor(value.document_json)
    except RuntimeError as exc:
        raise ApprovedParentQualityEvidenceBindingError("descriptor bytes are invalid") from exc
    if not wire.same_typed_value(value, parsed):
        raise ApprovedParentQualityEvidenceBindingError("descriptor is forged")
    return parsed


def _parsed_commit(value: object) -> GenerationCommitV1:
    if type(value) is not GenerationCommitV1:
        raise ApprovedParentQualityEvidenceBindingError("commit is invalid")
    try:
        parsed = parse_generation_commit(value.document_json)
    except RuntimeError as exc:
        raise ApprovedParentQualityEvidenceBindingError("commit bytes are invalid") from exc
    if not wire.same_typed_value(value, parsed):
        raise ApprovedParentQualityEvidenceBindingError("commit is forged")
    return parsed


def _parsed_qc(value: object) -> QcReceiptWireV1:
    if type(value) is not QcReceiptWireV1:
        raise ApprovedParentQualityEvidenceBindingError("QC receipt is invalid")
    try:
        parsed = parse_qc_receipt_v1(value.document_json)
    except RuntimeError as exc:
        raise ApprovedParentQualityEvidenceBindingError("QC receipt bytes are invalid") from exc
    if not wire.same_typed_value(value, parsed):
        raise ApprovedParentQualityEvidenceBindingError("QC receipt is forged")
    return parsed


def _parsed_evidence(value: object) -> ApprovedParentQualityEvidenceV1:
    if type(value) is not ApprovedParentQualityEvidenceV1:
        raise ApprovedParentQualityEvidenceBindingError("quality evidence is invalid")
    try:
        parsed = parse_approved_parent_quality_evidence_v1(
            value.full_decode.document_json,
            value.effect_proof.document_json,
            value.audit.document_json,
        )
    except (AttributeError, RuntimeError) as exc:
        raise ApprovedParentQualityEvidenceBindingError("evidence bytes are invalid") from exc
    if not wire.same_typed_value(value, parsed):
        raise ApprovedParentQualityEvidenceBindingError("quality evidence is forged")
    return parsed


def _validated(value: object) -> _ValidatedBindingV1:
    if type(value) is not ApprovedParentQualityEvidenceBindingV1:
        raise ApprovedParentQualityEvidenceBindingError("binding input is invalid")
    descriptor = _parsed_descriptor(value.descriptor)
    commit = _parsed_commit(value.commit)
    qc = _parsed_qc(value.qc_receipt)
    evidence = _parsed_evidence(value.evidence)
    try:
        plan = wire.canonical_document(value.plan_json, "approved plan")
    except RuntimeError as exc:
        raise ApprovedParentQualityEvidenceBindingError("plan bytes are invalid") from exc
    return _ValidatedBindingV1(
        descriptor, commit, qc, plan, value.plan_json, evidence
    )


def _identity(value: _ValidatedBindingV1) -> None:
    descriptor = value.descriptor
    commit = value.commit
    described = (
        descriptor.identity.authority_id,
        descriptor.identity.generation_id,
        descriptor.identity.attempt_id,
        descriptor.identity.unit_id,
        descriptor.identity.request_digest,
        descriptor.policies.execution_policy_id,
        descriptor.policies.repair_policy_id,
        descriptor.policies.quality_policy_id,
        descriptor.policies.fallback_policy_id,
    )
    committed = (
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
    if described != committed:
        raise ApprovedParentQualityEvidenceBindingError("identity is inconsistent")


def _plan(value: _ValidatedBindingV1) -> None:
    descriptor = value.descriptor
    plan_ref = artifact_for_bytes(
        descriptor.plan.artifact.relative_path, value.plan_json
    )
    expected = (
        descriptor.plan.artifact,
        descriptor.plan.approved_plan_digest,
        descriptor.plan.content_hash,
    )
    actual = (
        plan_ref,
        approved_plan_digest(value.plan),
        plan_content_hash(value.plan),
    )
    if not same_artifact(actual[0], expected[0]):
        raise ApprovedParentQualityEvidenceBindingError("plan artifact is stale")
    if actual[1:] != expected[1:]:
        raise ApprovedParentQualityEvidenceBindingError("plan digests are stale")


def _qc(value: _ValidatedBindingV1) -> None:
    descriptor = value.descriptor
    qc = value.qc_receipt
    expected = (
        descriptor.plan.approved_plan_digest,
        descriptor.output.final.artifact.sha256,
        descriptor.output.assembly_receipt.sha256,
        descriptor.policies.quality_policy_id,
        descriptor.quality.audit,
        descriptor.quality.full_decode,
        descriptor.quality.effect_proof,
    )
    actual = (
        qc.plan_digest,
        qc.final_sha256,
        qc.assembly_receipt_sha256,
        qc.quality_policy_id,
        qc.audit,
        qc.full_decode,
        qc.effect_proof,
    )
    current = current_deterministic_quality_policy().policy_id
    if actual != expected or descriptor.policies.quality_policy_id != current:
        raise ApprovedParentQualityEvidenceBindingError("QC or policy binding is stale")


def validate_approved_parent_quality_evidence_binding(value: object) -> None:
    """Cross-bind canonical evidence to plan, manifest roles, policy, and QC."""
    checked = _validated(value)
    _identity(checked)
    _plan(checked)
    try:
        validate_quality_evidence_manifest_binding(
            checked.descriptor,
            checked.commit,
            checked.qc_receipt,
            checked.evidence,
        )
    except QualityEvidenceManifestBindingError as exc:
        raise ApprovedParentQualityEvidenceBindingError(str(exc)) from exc
    _qc(checked)
    try:
        validate_quality_evidence_semantics(
            checked.descriptor, checked.qc_receipt, checked.plan, checked.evidence
        )
    except QualityEvidenceSemanticError as exc:
        raise ApprovedParentQualityEvidenceBindingError(str(exc)) from exc
