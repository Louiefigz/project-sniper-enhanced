"""Cross-record semantics for exact approved-parent quality evidence."""

from __future__ import annotations

import math
from fractions import Fraction

from .approved_parent_quality_receipts import QcReceiptWireV1
from .approved_parent_schema import ApprovedParentDescriptorV1
from .quality_audit_evidence_wire import quality_evidence_set_digest
from .quality_evidence_types import ApprovedParentQualityEvidenceV1
from .quality_pass_contract import graphic_render_intent_digest
from .repair_intent import current_accent_policy


class QualityEvidenceSemanticError(RuntimeError):
    """Canonical evidence contradicts plan, media, policy, or receipt roles."""


def _core(descriptor: ApprovedParentDescriptorV1) -> tuple:
    return (
        descriptor.plan.artifact,
        descriptor.plan.approved_plan_digest,
        descriptor.output.final.artifact,
        descriptor.output.assembly_receipt,
        descriptor.policies.quality_policy_id,
        descriptor.provenance.runtime_capability_manifest,
    )


def _full_decode(
    descriptor: ApprovedParentDescriptorV1,
    evidence: ApprovedParentQualityEvidenceV1,
) -> None:
    proof = evidence.full_decode
    actual = (
        proof.plan,
        proof.approved_plan_digest,
        proof.final,
        proof.assembly_receipt,
        proof.quality_policy_id,
        proof.runtime_capability_manifest,
    )
    if actual != _core(descriptor):
        raise QualityEvidenceSemanticError("full-decode authority binding is invalid")
    facts = descriptor.output.final.facts
    if facts.audio_codec != "aac" or proof.video.expected_frames != facts.frame_count:
        raise QualityEvidenceSemanticError("full-decode media coverage is invalid")
    decoded_duration = (
        proof.audio.expected_samples_per_channel / proof.audio.sample_rate_hz
    )
    tolerance = max(0.1, 2_048 / proof.audio.sample_rate_hz)
    if abs(decoded_duration - facts.duration_seconds) > tolerance:
        raise QualityEvidenceSemanticError("full-decode audio duration is invalid")
    packet_error = abs(
        proof.audio.expected_packets * 1_024
        - proof.audio.expected_samples_per_channel
    )
    if packet_error > 2_048:
        raise QualityEvidenceSemanticError("full-decode AAC packet coverage is invalid")
    if proof.tools.ffmpeg_sha256 == proof.tools.ffprobe_sha256:
        raise QualityEvidenceSemanticError("decode tool roles alias")


def _effect_row(plan: dict) -> dict:
    track = plan.get("graphicsTrack")
    if type(track) is not list or len(track) != 1 or type(track[0]) is not dict:
        raise QualityEvidenceSemanticError("R0 effect plan is not single-target")
    row = track[0]
    placement = row.get("placement")
    start, end = row.get("outStart"), row.get("outEnd")
    numeric = (start, end)
    positioned = (
        type(placement) is dict
        and set(placement) == {"x", "y"}
        and all(
            type(placement[key]) in {int, float} and math.isfinite(placement[key])
            for key in ("x", "y")
        )
    )
    valid = (
        row.get("kind") == "section-marker"
        and row.get("anchor") == "free-band"
        and type(row.get("spec")) is dict
        and positioned
        and all(type(item) in {int, float} and math.isfinite(item) for item in numeric)
        and end > start >= 0
    )
    if not valid:
        raise QualityEvidenceSemanticError("R0 effect target is invalid")
    return row


def _requested_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def _ceiling(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _expected_frames(
    start: int | float, end: int | float, descriptor: ApprovedParentDescriptorV1
) -> tuple[int, int]:
    facts = descriptor.output.final.facts
    fps = Fraction(facts.fps_numerator, facts.fps_denominator)
    first = _ceiling(Fraction(str(start)) * fps)
    last = _ceiling(Fraction(str(end)) * fps) - 1
    if first < 0 or last < first or last >= facts.frame_count:
        raise QualityEvidenceSemanticError("effect window exceeds final media")
    return first, last


def _effect_identity(
    descriptor: ApprovedParentDescriptorV1,
    plan: dict,
    evidence: ApprovedParentQualityEvidenceV1,
) -> dict:
    proof = evidence.effect_proof
    actual = (
        proof.plan,
        proof.approved_plan_digest,
        proof.final,
        proof.assembly_receipt,
        proof.quality_policy_id,
        proof.runtime_capability_manifest,
    )
    if actual != _core(descriptor):
        raise QualityEvidenceSemanticError("effect authority binding is invalid")
    row = _effect_row(plan)
    target = proof.target
    policy = current_accent_policy()
    requested = row["spec"].get("accent")
    valid = (
        proof.request_digest == descriptor.identity.request_digest
        and target.graphic_id == row.get("id")
        and target.requested_value == requested
        and target.brand_policy_id == descriptor.policies.repair_policy_id
        and target.brand_policy_id == policy.policy_id
        and requested in policy.allowed_values
    )
    if not valid:
        raise QualityEvidenceSemanticError("requested effect or brand binding is invalid")
    return row


def _effect_raster(
    descriptor: ApprovedParentDescriptorV1,
    row: dict,
    evidence: ApprovedParentQualityEvidenceV1,
) -> None:
    proof = evidence.effect_proof
    if len(descriptor.graphics.assets) != 1:
        raise QualityEvidenceSemanticError("R0 effect asset set is invalid")
    asset = descriptor.graphics.assets[0]
    render_intent = graphic_render_intent_digest(row)
    expected = (asset.graphic_id, asset.media.artifact, render_intent)
    actual = (
        proof.target.graphic_id,
        proof.preencode.graphic_media,
        proof.preencode.render_intent_digest,
    )
    requested_rgb = _requested_rgb(proof.target.requested_value)
    valid = actual == expected and asset.render_intent_digest == render_intent
    valid = valid and proof.preencode.raster_rgb == requested_rgb
    if not valid:
        raise QualityEvidenceSemanticError("pre-encode effect landing is invalid")
    decoded = proof.decoded_color
    if decoded.requested_rgb != requested_rgb:
        raise QualityEvidenceSemanticError("decoded requested color is invalid")
    if row.get("id") != asset.graphic_id:
        raise QualityEvidenceSemanticError("effect asset order is invalid")


def _effect_window(
    descriptor: ApprovedParentDescriptorV1,
    row: dict,
    evidence: ApprovedParentQualityEvidenceV1,
) -> None:
    proof = evidence.effect_proof
    timing = proof.timing
    start, end = row.get("outStart"), row.get("outEnd")
    expected_frames = _expected_frames(start, end, descriptor)
    expected_timing = (start, end, *expected_frames)
    actual_timing = (
        timing.out_start,
        timing.out_end,
        timing.expected_first_frame,
        timing.expected_last_frame,
    )
    if actual_timing != expected_timing:
        raise QualityEvidenceSemanticError("effect timing differs from plan")
    samples = timing.sampled_frames
    related = (
        proof.decoded_color.sampled_frames,
        proof.contrast.sampled_frames,
        proof.protected_regions.sampled_frames,
    )
    if related != (samples, samples, samples):
        raise QualityEvidenceSemanticError("effect full-window evidence is incomplete")


def _effect_placement(
    descriptor: ApprovedParentDescriptorV1,
    row: dict,
    evidence: ApprovedParentQualityEvidenceV1,
) -> None:
    placement = evidence.effect_proof.placement
    asset_facts = descriptor.graphics.assets[0].media.facts
    final_facts = descriptor.output.final.facts
    expected = (
        row["anchor"],
        row["placement"]["x"],
        row["placement"]["y"],
        final_facts.width,
        final_facts.height,
        asset_facts.width,
        asset_facts.height,
    )
    actual = (
        placement.anchor,
        placement.expected_x,
        placement.expected_y,
        placement.delivery_width,
        placement.delivery_height,
        placement.graphic_width,
        placement.graphic_height,
    )
    if actual != expected:
        raise QualityEvidenceSemanticError("effect placement differs from plan")
    visible = (
        placement.expected_x < placement.delivery_width
        and placement.expected_x + placement.graphic_width > 0
        and placement.expected_y < placement.delivery_height
        and placement.expected_y + placement.graphic_height > 0
    )
    if not visible:
        raise QualityEvidenceSemanticError("effect placement is outside delivery")


def _effect(
    descriptor: ApprovedParentDescriptorV1,
    plan: dict,
    evidence: ApprovedParentQualityEvidenceV1,
) -> None:
    row = _effect_identity(descriptor, plan, evidence)
    _effect_raster(descriptor, row, evidence)
    _effect_window(descriptor, row, evidence)
    _effect_placement(descriptor, row, evidence)


def _audit(
    descriptor: ApprovedParentDescriptorV1,
    qc: QcReceiptWireV1,
    evidence: ApprovedParentQualityEvidenceV1,
) -> None:
    audit = evidence.audit
    actual = (
        audit.plan,
        audit.approved_plan_digest,
        audit.final,
        audit.assembly_receipt,
        audit.quality_policy_id,
        audit.runtime_capability_manifest,
    )
    if actual != _core(descriptor):
        raise QualityEvidenceSemanticError("terminal Audit-B authority is invalid")
    refs = (qc.full_decode, qc.effect_proof)
    if (audit.full_decode, audit.effect_proof) != refs:
        raise QualityEvidenceSemanticError("terminal Audit-B evidence refs are stale")
    if audit.evidence_set_digest != quality_evidence_set_digest(*refs):
        raise QualityEvidenceSemanticError("terminal Audit-B evidence digest is stale")


def validate_quality_evidence_semantics(
    descriptor: ApprovedParentDescriptorV1,
    qc: QcReceiptWireV1,
    plan: dict,
    evidence: ApprovedParentQualityEvidenceV1,
) -> None:
    """Bind evidence semantics to exact plan, products, policy, and QC roles."""
    _full_decode(descriptor, evidence)
    _effect(descriptor, plan, evidence)
    _audit(descriptor, qc, evidence)
