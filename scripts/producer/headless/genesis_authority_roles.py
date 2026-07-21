"""Exact artifact-class roles for a genesis approved card and origin receipt."""

from __future__ import annotations

from .genesis_approved_card import GenesisApprovedCardV2
from .origin_receipt import InitializationOriginReceiptV1


def _provenance(card: GenesisApprovedCardV2) -> tuple:
    value = card.provenance
    return (
        ("provenance.request", value.request_identity, "request-identity-v1"),
        (
            "provenance.execution",
            value.execution_policy,
            "initialization-execution-policy-v2",
        ),
        ("provenance.admission", value.admission_inputs, "admission-inputs-v1"),
        (
            "provenance.realizationInputs",
            value.realization_inputs,
            "realization-inputs-v1",
        ),
        (
            "provenance.generationInputs",
            value.generation_inputs,
            "generation-inputs-v1",
        ),
        (
            "provenance.snapshotManifest",
            value.source_snapshot_manifest,
            "source-snapshot-manifest-v1",
        ),
        ("provenance.baseFingerprint", value.base_fingerprint, "base-fingerprint-v1"),
        ("provenance.operator", value.operator_intent, "operator-intent-v1"),
        ("provenance.cut", value.cut_approval, "cut-approval-v1"),
        ("provenance.assetClosure", value.asset_closure, "asset-closure-v1"),
        (
            "provenance.runtime",
            value.runtime_capability_manifest,
            "runtime-capability-manifest-v1",
        ),
        ("provenance.repairState", value.repair_state, "repair-state-v1"),
        ("provenance.realization", value.realization, "realization-v1"),
        (
            "provenance.templateApproval",
            value.template_usage_approval,
            "template-usage-approval-v1",
        ),
        ("provenance.refit", value.refit_disposition, "refit-disposition-v1"),
        ("provenance.proxy", value.proxy_disposition, "proxy-disposition-v1"),
    )


def _products(card: GenesisApprovedCardV2) -> tuple:
    return (
        ("plan", card.plan.artifact, "plan-v1"),
        ("base.media", card.base.media.artifact, "base-media-v1"),
        ("base.plan", card.base.plan_artifact, "base-plan-v1"),
        ("base.receipt", card.base.receipt, "base-receipt-v1"),
        ("base.timeline", card.base.timeline_map, "timeline-map-v1"),
        ("graphics.clips", card.graphics.prebound_clips, "prebound-clips-v1"),
        ("output.final", card.output.final.artifact, "final-media-v1"),
        ("output.cover", card.output.cover, "cover-image-v1"),
        ("output.coverProof", card.output.cover_proof, "cover-proof-v1"),
        ("quality.audit", card.quality.audit, "audit-b-receipt-v1"),
        ("quality.decode", card.quality.full_decode, "full-decode-proof-v1"),
        ("quality.effect", card.quality.effect_proof, "effect-proof-v1"),
        ("quality.qc", card.quality.qc_receipt, "qc-receipt-v1"),
        ("quality.approval", card.quality.final_approval, "final-approval-v3"),
    )


def _variable(card: GenesisApprovedCardV2) -> tuple:
    graphics = tuple(
        role
        for index, asset in enumerate(card.graphics.assets)
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
        for index, item in enumerate(card.quality.critics)
    )
    return graphics + critics


def genesis_authority_roles(
    card: GenesisApprovedCardV2, receipt: InitializationOriginReceiptV1
) -> tuple:
    """Return every manifest-backed authority named by the genesis structure."""
    authority = (
        ("origin.receipt", card.origin.receipt, "initialization-origin-receipt-v1"),
        ("origin.operation", card.origin.operation, "headless-operation-v1"),
        (
            "origin.snapshot",
            card.origin.snapshot_authority,
            "initialization-snapshot-authority-v1",
        ),
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
    )
    return _provenance(card) + _products(card) + _variable(card) + authority
