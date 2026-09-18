"""Cross-bind an approved-parent card to the exact R0 generation manifest."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from .approved_parent_schema import ApprovedParentDescriptorV1
from .artifact_contract import ArtifactRefV1
from .generation_artifact_store import GenerationArtifactStoreV1
from .generation_schema import GenerationCommitV1, GenerationManifestRowV1


class ApprovedParentBindingError(RuntimeError):
    """The authority card names the wrong commit identity or artifact class."""


def _artifact(row: GenerationManifestRowV1) -> ArtifactRefV1:
    return ArtifactRefV1(row.path, row.sha256, row.size_bytes)


def class_artifacts(
    groups: Mapping[str, tuple[GenerationManifestRowV1, ...]],
) -> Mapping[str, tuple[ArtifactRefV1, ...]]:
    """Project exact manifest rows into immutable typed references."""
    return MappingProxyType(
        {name: tuple(_artifact(row) for row in rows) for name, rows in groups.items()}
    )


def validate_descriptor_identity(
    descriptor: ApprovedParentDescriptorV1, commit: GenerationCommitV1
) -> None:
    """Require the card to repeat every immutable commit identity and policy."""
    identity = descriptor.identity
    policies = descriptor.policies
    actual = (
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
    expected = (
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
    if actual != expected:
        raise ApprovedParentBindingError("approved-parent identity differs from commit")


def _provenance_roles(descriptor: ApprovedParentDescriptorV1) -> tuple:
    value = descriptor.provenance
    return (
        (value.request_identity, "request-identity-v1"),
        (value.execution_policy, "execution-policy-v1"),
        (value.admission_inputs, "admission-inputs-v1"),
        (value.realization_inputs, "realization-inputs-v1"),
        (value.generation_inputs, "generation-inputs-v1"),
        (value.source_snapshot_manifest, "source-snapshot-manifest-v1"),
        (value.base_fingerprint, "base-fingerprint-v1"),
        (value.operator_intent, "operator-intent-v1"),
        (value.cut_approval, "cut-approval-v1"),
        (value.asset_closure, "asset-closure-v1"),
        (value.runtime_capability_manifest, "runtime-capability-manifest-v1"),
        (value.repair_state, "repair-state-v1"),
        (value.realization, "realization-v1"),
        (value.template_usage_approval, "template-usage-approval-v1"),
        (value.refit_disposition, "refit-disposition-v1"),
        (value.proxy_disposition, "proxy-disposition-v1"),
    )


def _product_roles(descriptor: ApprovedParentDescriptorV1) -> tuple:
    return (
        (descriptor.plan.artifact, "plan-v1"),
        (descriptor.base.media.artifact, "base-media-v1"),
        (descriptor.base.plan_artifact, "base-plan-v1"),
        (descriptor.base.receipt, "base-receipt-v1"),
        (descriptor.base.timeline_map, "timeline-map-v1"),
        (descriptor.graphics.prebound_clips, "prebound-clips-v1"),
        (descriptor.output.final.artifact, "final-media-v1"),
        (descriptor.output.assembly_receipt, "assembly-receipt-v1"),
        (descriptor.output.cover, "cover-image-v1"),
        (descriptor.output.cover_proof, "cover-proof-v1"),
        (descriptor.quality.audit, "audit-b-receipt-v1"),
        (descriptor.quality.full_decode, "full-decode-proof-v1"),
        (descriptor.quality.effect_proof, "effect-proof-v1"),
        (descriptor.quality.qc_receipt, "qc-receipt-v1"),
        (descriptor.quality.final_approval, "final-approval-v3"),
    )


def _variable_roles(descriptor: ApprovedParentDescriptorV1) -> tuple:
    graphics = tuple(
        (asset.media.artifact, "graphic-media-v1")
        for asset in descriptor.graphics.assets
    )
    receipts = tuple(
        (asset.receipt, "graphic-render-receipt-v1")
        for asset in descriptor.graphics.assets
    )
    critics = tuple(
        (critic.artifact, "critic-receipt-v1") for critic in descriptor.quality.critics
    )
    return graphics + receipts + critics


def _require_class(
    ref: ArtifactRefV1,
    artifact_class: str,
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]],
) -> None:
    if ref not in artifacts.get(artifact_class, ()):
        raise ApprovedParentBindingError(
            f"approved-parent artifact does not match class {artifact_class}"
        )


def validate_descriptor_artifacts(
    descriptor: ApprovedParentDescriptorV1,
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]],
    store: GenerationArtifactStoreV1,
) -> None:
    """Bind every card ref to its sole allowed class and verified snapshot."""
    roles = (
        _provenance_roles(descriptor)
        + _product_roles(descriptor)
        + _variable_roles(descriptor)
    )
    for ref, artifact_class in roles:
        _require_class(ref, artifact_class, artifacts)
        store.resolve(ref)
    described = {ref for ref, _artifact_class in roles}
    expected = {
        ref
        for name, refs in artifacts.items()
        if name
        not in {
            "approved-parent-v1",
            "generation-verification-v1",
            "repair-policy-v1",
            "quality-policy-v1",
            "fallback-policy-v1",
            "render-build-receipt-v1",
            "compositor-build-receipt-v1",
        }
        for ref in refs
    }
    if described != expected:
        raise ApprovedParentBindingError("approved-parent card coverage is incomplete")


def validate_remaining_artifacts(
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]],
    store: GenerationArtifactStoreV1,
) -> None:
    """Revalidate the unembedded policy, build, card, and verification refs."""
    for refs in artifacts.values():
        for ref in refs:
            store.resolve(ref)
