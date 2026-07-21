"""Current-card semantic validation for quality-pass authority V2."""

from __future__ import annotations

from graphics.composite_smoothness import YDIF_DUP_FAIL

from .generation_schema import GenerationCommitV1, parse_generation_commit
from .quality_pass_outputs import graphic_asset_set_digest
from .quality_receipt_json import same_typed_value
from .versioned_assembly_receipt import (
    AssemblyReceiptV2,
    validate_assembly_receipt_v2,
)
from .versioned_quality_pass_card import (
    QualityPassApprovedCardV2,
    validate_quality_pass_approved_card_v2,
)
from .versioned_quality_pass_types import QualityPassAuthorityInputsV2
from .versioned_quality_pass_verification import (
    QualityPassGenerationVerificationV2,
    validate_quality_pass_generation_verification_v2,
)


class QualityPassCurrentBindingV2Error(RuntimeError):
    """Quality-pass V2 current card or receipt is inconsistent."""


def _reparsed_commit(value: GenerationCommitV1) -> None:
    try:
        parsed = parse_generation_commit(value.document_json)
    except RuntimeError as exc:
        raise QualityPassCurrentBindingV2Error(
            "quality-pass commit is invalid"
        ) from exc
    if not same_typed_value(value, parsed):
        raise QualityPassCurrentBindingV2Error("quality-pass commit is forged")


def revalidate_quality_pass_inputs(value: object) -> QualityPassAuthorityInputsV2:
    """Reparse every exact current authority before cross-comparison."""
    if type(value) is not QualityPassAuthorityInputsV2:
        raise QualityPassCurrentBindingV2Error("quality-pass inputs are invalid")
    expected = (
        GenerationCommitV1,
        QualityPassApprovedCardV2,
        AssemblyReceiptV2,
        QualityPassGenerationVerificationV2,
    )
    actual = (
        type(value.commit),
        type(value.approved_card),
        type(value.assembly_receipt),
        type(value.verification),
    )
    if actual != expected:
        raise QualityPassCurrentBindingV2Error("quality-pass input types are invalid")
    try:
        _reparsed_commit(value.commit)
        validate_quality_pass_approved_card_v2(value.approved_card)
        validate_assembly_receipt_v2(value.assembly_receipt)
        validate_quality_pass_generation_verification_v2(
            value.verification, value.commit
        )
    except RuntimeError as exc:
        raise QualityPassCurrentBindingV2Error(
            "quality-pass authority bytes are invalid"
        ) from exc
    return value


def _card_identity(inputs: QualityPassAuthorityInputsV2) -> tuple:
    card, commit = inputs.approved_card, inputs.commit
    identity, policies = card.identity, card.policies
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
        card.expected_parent,
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
        commit.expected_parent,
    )
    return actual, expected


def validate_quality_pass_identity(inputs: QualityPassAuthorityInputsV2) -> None:
    """Bind commit, card, receipt, and verification parent/current identities."""
    receipt, verification = inputs.assembly_receipt, inputs.verification
    actual, expected = _card_identity(inputs)
    receipt_values = (
        receipt.request_digest,
        receipt.quality_policy_id,
        receipt.parent,
    )
    expected_receipt = (
        inputs.commit.request_digest,
        inputs.commit.quality_policy_id,
        inputs.commit.expected_parent,
    )
    valid = (
        same_typed_value(actual, expected)
        and same_typed_value(receipt_values, expected_receipt)
        and same_typed_value(verification.parent_authority, receipt.parent_authority)
    )
    if not valid:
        raise QualityPassCurrentBindingV2Error("quality-pass identity is stale")
    if same_typed_value(
        receipt.parent_authority.receipt,
        inputs.approved_card.output.assembly_receipt,
    ):
        raise QualityPassCurrentBindingV2Error("quality-pass assembly is self-parented")


def validate_quality_pass_card_values(inputs: QualityPassAuthorityInputsV2) -> None:
    """Bind plan, base, graphics, and output receipt values to the current card."""
    card, receipt = inputs.approved_card, inputs.assembly_receipt
    plan = (receipt.plan, receipt.plan_digest, receipt.base_projection_digest)
    expected_plan = (
        card.plan.artifact,
        card.plan.approved_plan_digest,
        card.plan.base_projection_digest,
    )
    base = (receipt.base, receipt.base_receipt_sha256, receipt.timeline_map_sha256)
    expected_base = (
        card.base.media,
        card.base.receipt.sha256,
        card.base.timeline_map.sha256,
    )
    graphics = (
        receipt.assets,
        receipt.asset_set_digest,
        receipt.clips_artifact,
    )
    expected_graphics = (
        card.graphics.assets,
        graphic_asset_set_digest(card.graphics.assets),
        card.graphics.prebound_clips,
    )
    output = (receipt.final, receipt.cover, receipt.cover_proof)
    expected_output = (card.output.final, card.output.cover, card.output.cover_proof)
    if not all(
        same_typed_value(actual, expected)
        for actual, expected in (
            (plan, expected_plan),
            (base, expected_base),
            (graphics, expected_graphics),
            (output, expected_output),
        )
    ):
        raise QualityPassCurrentBindingV2Error(
            "quality-pass current card values are stale"
        )


def validate_quality_pass_observed_shape(inputs: QualityPassAuthorityInputsV2) -> None:
    """Retain frozen R0 compositor-shape checks without claiming reobservation."""
    card, receipt = inputs.approved_card, inputs.assembly_receipt
    proof = receipt.compositor
    actual = (proof.passes, proof.frames_in, proof.frames_out, proof.fail_threshold)
    expected = (
        1,
        card.base.media.facts.frame_count,
        card.output.final.facts.frame_count,
        YDIF_DUP_FAIL,
    )
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
        same_typed_value(actual, expected)
        and base_timing == final_timing
        and base.alpha_mode == final.alpha_mode == "none"
        and base.audio_codec is not None
        and receipt.base.artifact.sha256 != receipt.final.artifact.sha256
    )
    if not valid:
        raise QualityPassCurrentBindingV2Error("quality-pass compositor shape is stale")
