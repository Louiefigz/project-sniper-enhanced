"""In-memory semantic binding for the approved-parent quality receipt chain."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping

from .approved_parent_quality_receipts import (
    ApprovedParentQualityRecordsV1,
    validate_cover_proof_v1,
    validate_critic_receipt_v1,
    validate_final_approval_v3,
    validate_qc_receipt_v1,
)
from .approved_parent_schema import (
    ApprovedParentDescriptorV1,
    parse_approved_parent_descriptor,
    validate_approved_parent_descriptor,
)
from .artifact_contract import ArtifactRefV1
from .generation_profile import verify_r0_generation_profile
from .generation_schema import GenerationCommitV1, parse_generation_commit
from .quality_receipt_json import same_typed_value

_Descriptor = ApprovedParentDescriptorV1
_Records = ApprovedParentQualityRecordsV1
_Groups = Mapping[str, tuple]


class ApprovedParentQualityBindingError(RuntimeError):
    """Canonical quality records contradict their descriptor or commit."""


def _artifact(path: str, raw: bytes) -> ArtifactRefV1:
    return ArtifactRefV1(path, hashlib.sha256(raw).hexdigest(), len(raw))


def _raise_wrapped(callback: Callable[[], None], label: str) -> None:
    try:
        callback()
    except RuntimeError as exc:
        raise ApprovedParentQualityBindingError(f"invalid {label}") from exc


def _validate_inputs(
    descriptor: object, commit: object, records: object
) -> tuple[
    ApprovedParentDescriptorV1, GenerationCommitV1, ApprovedParentQualityRecordsV1
]:
    if type(descriptor) is not ApprovedParentDescriptorV1:
        raise ApprovedParentQualityBindingError("descriptor instance is invalid")
    if type(commit) is not GenerationCommitV1:
        raise ApprovedParentQualityBindingError("commit instance is invalid")
    if type(records) is not ApprovedParentQualityRecordsV1:
        raise ApprovedParentQualityBindingError("quality record set is invalid")
    _raise_wrapped(
        lambda: validate_approved_parent_descriptor(descriptor), "descriptor"
    )
    try:
        parsed_descriptor = parse_approved_parent_descriptor(descriptor.document_json)
    except RuntimeError as exc:
        raise ApprovedParentQualityBindingError("descriptor bytes are invalid") from exc
    if not same_typed_value(descriptor, parsed_descriptor):
        raise ApprovedParentQualityBindingError("descriptor construction is invalid")
    try:
        parsed_commit = parse_generation_commit(commit.document_json)
    except RuntimeError as exc:
        raise ApprovedParentQualityBindingError("commit bytes are invalid") from exc
    if not same_typed_value(commit, parsed_commit):
        raise ApprovedParentQualityBindingError("commit construction is invalid")
    return descriptor, commit, records


def _validate_records(records: ApprovedParentQualityRecordsV1) -> None:
    if type(records.critics) is not tuple or len(records.critics) != 2:
        raise ApprovedParentQualityBindingError("critic record set is invalid")
    checks = (
        (records.cover_proof, validate_cover_proof_v1, "cover proof"),
        (records.qc_receipt, validate_qc_receipt_v1, "QC receipt"),
        (records.final_approval, validate_final_approval_v3, "final approval"),
    )
    for value, validator, label in checks:
        _raise_wrapped(lambda value=value, validator=validator: validator(value), label)
    for critic in records.critics:
        _raise_wrapped(
            lambda critic=critic: validate_critic_receipt_v1(critic), "critic"
        )
    if tuple(critic.lens for critic in records.critics) != (
        "composition",
        "editorial",
    ):
        raise ApprovedParentQualityBindingError("critic record order is invalid")


def _identity(
    descriptor: ApprovedParentDescriptorV1, commit: GenerationCommitV1
) -> None:
    identity = descriptor.identity
    policies = descriptor.policies
    described = (
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
        raise ApprovedParentQualityBindingError("descriptor/commit identity mismatch")


def _require_ref(ref: ArtifactRefV1, artifact_class: str, groups: _Groups) -> None:
    rows = groups.get(artifact_class, ())
    matches = tuple(
        row
        for row in rows
        if ArtifactRefV1(row.path, row.sha256, row.size_bytes) == ref
    )
    if len(matches) != 1:
        raise ApprovedParentQualityBindingError(
            f"artifact does not match commit class {artifact_class}"
        )


def _manifest_refs(descriptor: _Descriptor, groups: _Groups) -> None:
    refs = (
        (descriptor.plan.artifact, "plan-v1"),
        (descriptor.output.final.artifact, "final-media-v1"),
        (descriptor.output.assembly_receipt, "assembly-receipt-v1"),
        (descriptor.output.cover, "cover-image-v1"),
        (descriptor.quality.audit, "audit-b-receipt-v1"),
        (descriptor.quality.full_decode, "full-decode-proof-v1"),
        (descriptor.quality.effect_proof, "effect-proof-v1"),
    )
    for ref, artifact_class in refs:
        _require_ref(ref, artifact_class, groups)


def _raw_receipt_refs(
    descriptor: ApprovedParentDescriptorV1,
    records: ApprovedParentQualityRecordsV1,
    groups: _Groups,
) -> None:
    fixed = (
        (
            descriptor.output.cover_proof,
            records.cover_proof.document_json,
            "cover-proof-v1",
        ),
        (
            descriptor.quality.qc_receipt,
            records.qc_receipt.document_json,
            "qc-receipt-v1",
        ),
        (
            descriptor.quality.final_approval,
            records.final_approval.document_json,
            "final-approval-v3",
        ),
    )
    for expected, raw, artifact_class in fixed:
        actual = _artifact(expected.relative_path, raw)
        if actual != expected:
            raise ApprovedParentQualityBindingError("receipt/descriptor mismatch")
        _require_ref(actual, artifact_class, groups)
    for described, record in zip(descriptor.quality.critics, records.critics):
        actual = _artifact(described.artifact.relative_path, record.document_json)
        if actual != described.artifact:
            raise ApprovedParentQualityBindingError("critic/descriptor mismatch")
        _require_ref(actual, "critic-receipt-v1", groups)


def _bind_cover(descriptor: _Descriptor, records: _Records) -> None:
    cover = records.cover_proof
    expected = (descriptor.output.final.artifact.sha256, descriptor.output.cover)
    if (cover.source_final_sha256, cover.cover) != expected:
        raise ApprovedParentQualityBindingError("cover proof binding is invalid")


def _bind_qc(descriptor: _Descriptor, records: _Records) -> None:
    qc = records.qc_receipt
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
    if actual != expected:
        raise ApprovedParentQualityBindingError("QC semantic binding is invalid")
    protected = {
        descriptor.plan.artifact.sha256,
        descriptor.output.final.artifact.sha256,
        descriptor.output.assembly_receipt.sha256,
        descriptor.output.cover.sha256,
        descriptor.output.cover_proof.sha256,
        descriptor.quality.qc_receipt.sha256,
        descriptor.quality.final_approval.sha256,
    }
    protected.update(item.artifact.sha256 for item in descriptor.quality.critics)
    evidence = {qc.audit.sha256, qc.full_decode.sha256, qc.effect_proof.sha256}
    if protected & evidence:
        raise ApprovedParentQualityBindingError("QC evidence aliases product bytes")


def _bind_critics(descriptor: _Descriptor, records: _Records) -> None:
    final_sha = descriptor.output.final.artifact.sha256
    evidence = descriptor.quality.qc_receipt.sha256
    expected = tuple(
        (item.lens, final_sha, evidence) for item in descriptor.quality.critics
    )
    actual = tuple(
        (item.lens, item.candidate_sha256, item.evidence_digest)
        for item in records.critics
    )
    if actual != expected:
        raise ApprovedParentQualityBindingError("critic semantic binding is invalid")


def _bind_approval(descriptor: _Descriptor, records: _Records) -> None:
    approval = records.final_approval
    identity = descriptor.identity
    critic_refs = tuple(
        (item.lens, item.artifact) for item in descriptor.quality.critics
    )
    expected = (
        identity.authority_id,
        identity.generation_id,
        identity.attempt_id,
        identity.unit_id,
        identity.request_digest,
        descriptor.plan.approved_plan_digest,
        descriptor.output.final.artifact.sha256,
        descriptor.output.assembly_receipt.sha256,
        descriptor.quality.qc_receipt,
        critic_refs,
        descriptor.policies.quality_policy_id,
    )
    actual = (
        approval.authority_id,
        approval.generation_id,
        approval.attempt_id,
        approval.unit_id,
        approval.request_digest,
        approval.plan_digest,
        approval.final_sha256,
        approval.assembly_receipt_sha256,
        approval.qc_receipt,
        tuple((item.lens, item.artifact) for item in approval.critics),
        approval.quality_policy_id,
    )
    if actual != expected:
        raise ApprovedParentQualityBindingError("final approval binding is invalid")


def validate_approved_parent_quality_chain(
    descriptor: object, commit: object, records: object
) -> None:
    """Cross-bind canonical quality records without opening any artifact path."""
    descriptor, commit, records = _validate_inputs(descriptor, commit, records)
    _validate_records(records)
    _identity(descriptor, commit)
    try:
        groups = verify_r0_generation_profile(commit)
    except RuntimeError as exc:
        raise ApprovedParentQualityBindingError("commit profile is invalid") from exc
    descriptor_ref = _artifact(commit.approved_parent_path, descriptor.document_json)
    _require_ref(descriptor_ref, "approved-parent-v1", groups)
    _manifest_refs(descriptor, groups)
    _raw_receipt_refs(descriptor, records, groups)
    _bind_cover(descriptor, records)
    _bind_qc(descriptor, records)
    _bind_critics(descriptor, records)
    _bind_approval(descriptor, records)
