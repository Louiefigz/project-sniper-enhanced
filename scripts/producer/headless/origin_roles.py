"""Current-card artifact roles named by initialization-origin binding."""

from __future__ import annotations

from .approved_parent_schema import ApprovedParentDescriptorV1
from .origin_receipt import InitializationOriginReceiptV1


def _variable_roles(receipt: InitializationOriginReceiptV1) -> tuple:
    graphics = tuple(
        role
        for index, asset in enumerate(receipt.graphics.assets)
        for role in (
            (f"graphics.media[{index}]", asset.media.artifact, "graphic-media-v1"),
            (
                f"graphics.receipt[{index}]",
                asset.receipt,
                "graphic-render-receipt-v1",
            ),
        )
    )
    critics = tuple(
        (f"quality.critic[{index}]", item.artifact, "critic-receipt-v1")
        for index, item in enumerate(receipt.quality.critics)
    )
    return graphics + critics


def origin_manifest_roles(
    descriptor: ApprovedParentDescriptorV1,
    receipt: InitializationOriginReceiptV1,
) -> tuple:
    """Return every origin role that can bind to a current R0 manifest row."""
    fixed = (
        ("plan", receipt.plan.artifact, "plan-v1"),
        ("base.media", receipt.base.media.artifact, "base-media-v1"),
        ("base.plan", receipt.base.plan_artifact, "base-plan-v1"),
        ("base.receipt", receipt.base.receipt, "base-receipt-v1"),
        ("base.timeline", receipt.base.timeline_map, "timeline-map-v1"),
        ("graphics.clips", receipt.graphics.prebound_clips, "prebound-clips-v1"),
        ("output.final", receipt.output.final.artifact, "final-media-v1"),
        ("output.cover", receipt.output.cover, "cover-image-v1"),
        ("output.coverProof", receipt.output.cover_proof, "cover-proof-v1"),
        ("quality.audit", receipt.quality.audit, "audit-b-receipt-v1"),
        ("quality.decode", receipt.quality.full_decode, "full-decode-proof-v1"),
        ("quality.effect", receipt.quality.effect_proof, "effect-proof-v1"),
        ("quality.qc", receipt.quality.qc_receipt, "qc-receipt-v1"),
        ("quality.approval", receipt.quality.final_approval, "final-approval-v3"),
        (
            "build.render",
            receipt.build_runtime.render_build_receipt,
            "render-build-receipt-v1",
        ),
        (
            "build.compositor",
            receipt.build_runtime.compositor_build_receipt,
            "compositor-build-receipt-v1",
        ),
        (
            "runtime.capabilities",
            receipt.build_runtime.runtime_capability_manifest,
            "runtime-capability-manifest-v1",
        ),
        (
            "policy.execution",
            descriptor.provenance.execution_policy,
            "execution-policy-v1",
        ),
    )
    return fixed + _variable_roles(receipt)
