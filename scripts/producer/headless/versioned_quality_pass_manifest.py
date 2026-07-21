"""Manifest-role binding for quality-pass approved card and assembly V2."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from .artifact_contract import ArtifactRefV1
from .generation_schema import GenerationManifestRowV1
from .quality_receipt_json import same_typed_value
from .versioned_quality_pass_current_validation import (
    QualityPassCurrentBindingV2Error,
)
from .versioned_quality_pass_types import QualityPassAuthorityInputsV2


def _artifact(row: GenerationManifestRowV1) -> ArtifactRefV1:
    return ArtifactRefV1(row.path, row.sha256, row.size_bytes)


def _raw_ref(path: str, raw: bytes) -> ArtifactRefV1:
    return ArtifactRefV1(path, hashlib.sha256(raw).hexdigest(), len(raw))


def _require(ref: ArtifactRefV1, artifact_class: str, groups: Mapping) -> None:
    matches = tuple(
        row
        for row in groups.get(artifact_class, ())
        if same_typed_value(_artifact(row), ref)
    )
    if len(matches) != 1:
        raise QualityPassCurrentBindingV2Error(
            f"quality-pass artifact does not match class {artifact_class}"
        )


def _provenance(inputs: QualityPassAuthorityInputsV2) -> tuple:
    value = inputs.approved_card.provenance
    classes = (
        "request-identity-v1",
        "execution-policy-v1",
        "admission-inputs-v1",
        "realization-inputs-v1",
        "generation-inputs-v1",
        "source-snapshot-manifest-v1",
        "base-fingerprint-v1",
        "operator-intent-v1",
        "cut-approval-v1",
        "asset-closure-v1",
        "runtime-capability-manifest-v1",
        "repair-state-v1",
        "realization-v1",
        "template-usage-approval-v1",
        "refit-disposition-v1",
        "proxy-disposition-v1",
    )
    refs = (
        value.request_identity,
        value.execution_policy,
        value.admission_inputs,
        value.realization_inputs,
        value.generation_inputs,
        value.source_snapshot_manifest,
        value.base_fingerprint,
        value.operator_intent,
        value.cut_approval,
        value.asset_closure,
        value.runtime_capability_manifest,
        value.repair_state,
        value.realization,
        value.template_usage_approval,
        value.refit_disposition,
        value.proxy_disposition,
    )
    return tuple(zip(refs, classes))


def _products(inputs: QualityPassAuthorityInputsV2) -> tuple:
    card = inputs.approved_card
    return (
        (card.plan.artifact, "plan-v1"),
        (card.base.media.artifact, "base-media-v1"),
        (card.base.plan_artifact, "base-plan-v1"),
        (card.base.receipt, "base-receipt-v1"),
        (card.base.timeline_map, "timeline-map-v1"),
        (card.graphics.prebound_clips, "prebound-clips-v1"),
        (card.output.final.artifact, "final-media-v1"),
        (card.output.assembly_receipt, "assembly-receipt-v2"),
        (card.output.cover, "cover-image-v1"),
        (card.output.cover_proof, "cover-proof-v1"),
        (card.quality.audit, "audit-b-receipt-v1"),
        (card.quality.full_decode, "full-decode-proof-v1"),
        (card.quality.effect_proof, "effect-proof-v1"),
        (card.quality.qc_receipt, "qc-receipt-v1"),
        (card.quality.final_approval, "final-approval-v3"),
    )


def _variable(inputs: QualityPassAuthorityInputsV2) -> tuple:
    card = inputs.approved_card
    graphics = tuple(
        role
        for asset in card.graphics.assets
        for role in (
            (asset.media.artifact, "graphic-media-v1"),
            (asset.receipt, "graphic-render-receipt-v1"),
        )
    )
    critics = tuple(
        (critic.artifact, "critic-receipt-v1") for critic in card.quality.critics
    )
    return graphics + critics


def _exact_documents(
    inputs: QualityPassAuthorityInputsV2, groups: Mapping
) -> ArtifactRefV1:
    card_row = groups["quality-pass-approved-card-v2"][0]
    assembly_row = groups["assembly-receipt-v2"][0]
    verify_row = groups["quality-pass-generation-verification-v2"][0]
    card_ref = _raw_ref(card_row.path, inputs.approved_card.document_json)
    assembly_ref = _raw_ref(assembly_row.path, inputs.assembly_receipt.document_json)
    verify_ref = _raw_ref(verify_row.path, inputs.verification.document_json)
    expected = (_artifact(card_row), _artifact(assembly_row), _artifact(verify_row))
    if not same_typed_value((card_ref, assembly_ref, verify_ref), expected):
        raise QualityPassCurrentBindingV2Error(
            "quality-pass authority document bytes are stale"
        )
    cross = (
        inputs.approved_card.output.assembly_receipt,
        inputs.verification.approved_card,
        inputs.verification.assembly_receipt,
    )
    if not same_typed_value(cross, (assembly_ref, card_ref, assembly_ref)):
        raise QualityPassCurrentBindingV2Error(
            "quality-pass authority document references are stale"
        )
    return assembly_ref


def bind_quality_pass_manifest(
    inputs: QualityPassAuthorityInputsV2, groups: Mapping
) -> ArtifactRefV1:
    """Bind all current card roles and exact authority document bytes."""
    assembly_ref = _exact_documents(inputs, groups)
    roles = _provenance(inputs) + _products(inputs) + _variable(inputs)
    for ref, artifact_class in roles:
        _require(ref, artifact_class, groups)
    described = {ref for ref, _artifact_class in roles}
    excluded = {
        "quality-pass-approved-card-v2",
        "quality-pass-generation-verification-v2",
        "repair-policy-v1",
        "quality-policy-v1",
        "fallback-policy-v1",
        "render-build-receipt-v1",
        "compositor-build-receipt-v1",
    }
    expected = {
        _artifact(row)
        for name, rows in groups.items()
        if name not in excluded
        for row in rows
    }
    if described != expected:
        raise QualityPassCurrentBindingV2Error(
            "quality-pass approved-card coverage is incomplete"
        )
    return assembly_ref
