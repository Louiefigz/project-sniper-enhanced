"""Structural/current-card binding for one immutable assembly receipt."""

from __future__ import annotations

import hashlib

from graphics.composite_smoothness import YDIF_DUP_FAIL

from .approved_parent_assembly_receipt import (
    AssemblyReceiptV1,
    validate_assembly_receipt_v1,
)
from .approved_parent_assembly_types import (
    STRUCTURAL_STATUS,
    AssemblyAuthorityRequirementV1,
    AssemblyBindingReportV1,
    UNRESOLVED_ASSEMBLY_AUTHORITY,
)
from .approved_parent_binding import validate_descriptor_identity
from .approved_parent_schema import (
    ApprovedParentDescriptorV1,
    parse_approved_parent_descriptor,
)
from .artifact_contract import ArtifactRefV1
from .generation_profile import verify_r0_generation_profile
from .generation_schema import GenerationCommitV1, parse_generation_commit
from .quality_pass_outputs import graphic_asset_set_digest
from .quality_receipt_json import same_typed_value

__all__ = (
    "STRUCTURAL_STATUS",
    "ApprovedParentAssemblyBindingError",
    "AssemblyAuthorityRequirementV1",
    "AssemblyBindingReportV1",
    "UNRESOLVED_ASSEMBLY_AUTHORITY",
    "bind_approved_parent_assembly_receipt",
)


class ApprovedParentAssemblyBindingError(RuntimeError):
    """Assembly bytes contradict their current descriptor or commit."""


def _artifact(path: str, raw: bytes) -> ArtifactRefV1:
    return ArtifactRefV1(path, hashlib.sha256(raw).hexdigest(), len(raw))


def _parsed_inputs(
    descriptor: object, commit: object, receipt: object
) -> tuple[ApprovedParentDescriptorV1, GenerationCommitV1, AssemblyReceiptV1]:
    expected = (ApprovedParentDescriptorV1, GenerationCommitV1, AssemblyReceiptV1)
    if tuple(type(value) for value in (descriptor, commit, receipt)) != expected:
        raise ApprovedParentAssemblyBindingError("assembly binding inputs are invalid")
    try:
        parsed_descriptor = parse_approved_parent_descriptor(descriptor.document_json)
        parsed_commit = parse_generation_commit(commit.document_json)
        validate_assembly_receipt_v1(receipt)
    except RuntimeError as exc:
        raise ApprovedParentAssemblyBindingError(
            "assembly authority is invalid"
        ) from exc
    if not same_typed_value(descriptor, parsed_descriptor):
        raise ApprovedParentAssemblyBindingError("descriptor construction is invalid")
    if not same_typed_value(commit, parsed_commit):
        raise ApprovedParentAssemblyBindingError("commit construction is invalid")
    try:
        validate_descriptor_identity(descriptor, commit)
    except RuntimeError as exc:
        raise ApprovedParentAssemblyBindingError(
            "assembly authority is invalid"
        ) from exc
    return descriptor, commit, receipt


def _identity(
    descriptor: ApprovedParentDescriptorV1,
    commit: GenerationCommitV1,
    receipt: AssemblyReceiptV1,
) -> None:
    if commit.expected_parent is None:
        raise ApprovedParentAssemblyBindingError(
            "assembly receipt cannot represent a genesis generation"
        )
    expected = (
        descriptor.identity.request_digest,
        descriptor.policies.quality_policy_id,
        commit.expected_parent,
    )
    actual = (receipt.request_digest, receipt.quality_policy_id, receipt.parent)
    if actual != expected:
        raise ApprovedParentAssemblyBindingError("assembly identity is stale")
    if (
        receipt.parent_assembly_receipt_sha256
        == descriptor.output.assembly_receipt.sha256
    ):
        raise ApprovedParentAssemblyBindingError("assembly receipt is self-parented")


def _current_card(
    descriptor: ApprovedParentDescriptorV1, receipt: AssemblyReceiptV1
) -> None:
    plan = (receipt.plan, receipt.plan_digest, receipt.base_projection_digest)
    expected_plan = (
        descriptor.plan.artifact,
        descriptor.plan.approved_plan_digest,
        descriptor.plan.base_projection_digest,
    )
    base = (receipt.base, receipt.base_receipt_sha256, receipt.timeline_map_sha256)
    expected_base = (
        descriptor.base.media,
        descriptor.base.receipt.sha256,
        descriptor.base.timeline_map.sha256,
    )
    if not same_typed_value(plan, expected_plan):
        raise ApprovedParentAssemblyBindingError("assembly plan card is stale")
    if not same_typed_value(base, expected_base):
        raise ApprovedParentAssemblyBindingError("assembly base card is stale")


def _graphics(
    descriptor: ApprovedParentDescriptorV1, receipt: AssemblyReceiptV1
) -> None:
    assets = descriptor.graphics.assets
    expected = (
        assets,
        graphic_asset_set_digest(assets),
        descriptor.graphics.prebound_clips,
    )
    actual = (receipt.assets, receipt.asset_set_digest, receipt.clips_artifact)
    if not same_typed_value(actual, expected):
        raise ApprovedParentAssemblyBindingError("assembly graphic card is stale")
    if len(assets) != 1 or len(receipt.compositor.alpha_occupancy) != 1:
        raise ApprovedParentAssemblyBindingError("R0 assembly graphic count is invalid")


def _observed_shape(
    descriptor: ApprovedParentDescriptorV1, receipt: AssemblyReceiptV1
) -> None:
    proof = receipt.compositor
    expected = (
        1,
        descriptor.base.media.facts.frame_count,
        descriptor.output.final.facts.frame_count,
        YDIF_DUP_FAIL,
    )
    actual = (proof.passes, proof.frames_in, proof.frames_out, proof.fail_threshold)
    if not same_typed_value(actual, expected):
        raise ApprovedParentAssemblyBindingError("assembly observations are stale")
    base, final = receipt.base.facts, receipt.final.facts
    base_timing = (
        base.width,
        base.height,
        base.fps_numerator,
        base.fps_denominator,
        base.frame_count,
        base.audio_codec,
    )
    final_timing = (
        final.width,
        final.height,
        final.fps_numerator,
        final.fps_denominator,
        final.frame_count,
        final.audio_codec,
    )
    valid = (
        base_timing == final_timing
        and base.alpha_mode == final.alpha_mode == "none"
        and base.audio_codec is not None
        and receipt.base.artifact.sha256 != receipt.final.artifact.sha256
    )
    if not valid:
        raise ApprovedParentAssemblyBindingError("assembly timing shape is invalid")


def _output(descriptor: ApprovedParentDescriptorV1, receipt: AssemblyReceiptV1) -> None:
    expected = (
        descriptor.output.final,
        descriptor.output.cover,
        descriptor.output.cover_proof,
    )
    actual = (receipt.final, receipt.cover, receipt.cover_proof)
    if not same_typed_value(actual, expected):
        raise ApprovedParentAssemblyBindingError("assembly output card is stale")


def _require_ref(ref: ArtifactRefV1, artifact_class: str, groups: dict) -> None:
    matches = tuple(
        row
        for row in groups.get(artifact_class, ())
        if ArtifactRefV1(row.path, row.sha256, row.size_bytes) == ref
    )
    if len(matches) != 1:
        raise ApprovedParentAssemblyBindingError(
            f"assembly artifact does not match class {artifact_class}"
        )


def _manifest_roles(
    descriptor: ApprovedParentDescriptorV1, receipt: AssemblyReceiptV1
) -> tuple[tuple[ArtifactRefV1, str], ...]:
    fixed = (
        (receipt.plan, "plan-v1"),
        (receipt.base.artifact, "base-media-v1"),
        (descriptor.base.receipt, "base-receipt-v1"),
        (descriptor.base.timeline_map, "timeline-map-v1"),
        (receipt.clips_artifact, "prebound-clips-v1"),
        (receipt.final.artifact, "final-media-v1"),
        (receipt.cover, "cover-image-v1"),
        (receipt.cover_proof, "cover-proof-v1"),
    )
    graphics = tuple(
        role
        for asset in receipt.assets
        for role in (
            (asset.media.artifact, "graphic-media-v1"),
            (asset.receipt, "graphic-render-receipt-v1"),
        )
    )
    return fixed + graphics


def _manifest(
    descriptor: ApprovedParentDescriptorV1,
    receipt: AssemblyReceiptV1,
    groups: dict,
) -> ArtifactRefV1:
    approved = _artifact(groups["approved-parent-v1"][0].path, descriptor.document_json)
    assembly = _artifact(
        descriptor.output.assembly_receipt.relative_path, receipt.document_json
    )
    roles = (
        (approved, "approved-parent-v1"),
        (assembly, "assembly-receipt-v1"),
        *_manifest_roles(descriptor, receipt),
    )
    if assembly != descriptor.output.assembly_receipt:
        raise ApprovedParentAssemblyBindingError("assembly receipt bytes are stale")
    for ref, artifact_class in roles:
        _require_ref(ref, artifact_class, groups)
    digests = tuple(ref.sha256 for ref, _artifact_class in roles[1:])
    if len(digests) != len(set(digests)):
        raise ApprovedParentAssemblyBindingError("assembly artifact bytes alias")
    return assembly


def bind_approved_parent_assembly_receipt(
    descriptor: object, commit: object, receipt: object
) -> AssemblyBindingReportV1:
    """Bind current-card structure; never claim runtime or publication approval."""
    descriptor, commit, receipt = _parsed_inputs(descriptor, commit, receipt)
    _identity(descriptor, commit, receipt)
    try:
        groups = dict(verify_r0_generation_profile(commit))
    except RuntimeError as exc:
        raise ApprovedParentAssemblyBindingError("commit profile is invalid") from exc
    _current_card(descriptor, receipt)
    _graphics(descriptor, receipt)
    _observed_shape(descriptor, receipt)
    _output(descriptor, receipt)
    assembly = _manifest(descriptor, receipt, groups)
    return AssemblyBindingReportV1(
        STRUCTURAL_STATUS, assembly, UNRESOLVED_ASSEMBLY_AUTHORITY, False, False
    )
