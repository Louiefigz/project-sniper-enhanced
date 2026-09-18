"""Non-GUI controller for one private mechanical MP4 candidate."""

from __future__ import annotations

import json

from fingerprints import base_plan_digest

from .quality_pass_contract import (
    ApprovedParentV1,
    GraphicAssetRefV1,
    QualityPassContractError,
    QualityPassInputV1,
    graphic_render_intent_digest,
    validate_approved_parent,
    validate_artifact_ref,
    validate_graphic_asset,
    validate_quality_pass_input,
)
from .quality_pass_outputs import (
    CandidateMediaV1,
    GateReceiptV1,
    QcReceiptV1,
    QualityPassOutputError,
    graphic_asset_set_digest,
    validate_candidate,
    validate_critic_receipts,
    validate_gate_receipt,
    validate_qc_receipt,
)
from .quality_policy import current_deterministic_quality_policy
from .quality_pass_types import (
    CandidatePlanV1,
    CompositeRequestV1,
    CriticRequestV1,
    QcRequestV1,
    QualityPassPorts,
    QualityPassResultV1,
    RenderChangedRequestV1,
    SealRequestV1,
)
from .quality_timing import TimingRecorder
from .repair_intent import (
    AccentRepairPolicy,
    apply_repair,
    current_accent_policy,
)


class QualityPassError(RuntimeError):
    """The mechanical quality pass is stale, unsupported, or unverified."""


def _resolve_parent(
    request: QualityPassInputV1, ports: QualityPassPorts
) -> tuple[ApprovedParentV1, AccentRepairPolicy]:
    parent = ports.resolve_parent(request.repair.expected_parent)
    validate_approved_parent(parent)
    if parent.ref != request.repair.expected_parent:
        raise QualityPassError("resolved approved parent is stale")
    policy = current_accent_policy()
    quality_policy = current_deterministic_quality_policy()
    if request.repair_policy_id != policy.policy_id:
        raise QualityPassError("quality pass repair policy is stale")
    if request.quality_policy_id != quality_policy.policy_id:
        raise QualityPassError("quality pass verification policy is stale")
    if parent.repair_policy_id != request.repair_policy_id:
        raise QualityPassError("approved parent repair policy differs")
    if parent.quality_policy_id != request.quality_policy_id:
        raise QualityPassError("approved parent quality policy differs")
    return parent, policy


def _apply(
    request: QualityPassInputV1, resolved: tuple[ApprovedParentV1, AccentRepairPolicy]
) -> CandidatePlanV1:
    parent, policy = resolved
    application = apply_repair(
        request.repair, parent.ref, parent.decoded_plan(), policy
    )
    candidate = application.decoded_plan()
    if base_plan_digest(candidate) != parent.base_projection_digest:
        raise QualityPassError("repair invalidated the approved base projection")
    return CandidatePlanV1(parent, application)


def _check_gate(candidate: CandidatePlanV1, receipt: GateReceiptV1) -> None:
    validate_gate_receipt(receipt)
    expected = candidate.application.after_digest
    if (
        receipt.plan_digest != expected
        or receipt.base_projection_digest != candidate.parent.base_projection_digest
    ):
        raise QualityPassError("deterministic gate receipt is for other inputs")


def _target_entry(candidate: CandidatePlanV1) -> dict:
    plan = candidate.application.decoded_plan()
    matches = [
        row
        for row in plan["graphicsTrack"]
        if row.get("id") == candidate.application.graphic_id
    ]
    if len(matches) != 1:
        raise QualityPassError("candidate target is absent or ambiguous")
    return matches[0]


def _render_request(candidate: CandidatePlanV1) -> RenderChangedRequestV1:
    target = _target_entry(candidate)
    raw = json.dumps(
        target,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")
    return RenderChangedRequestV1(candidate, raw, graphic_render_intent_digest(target))


def _validate_render_request(request: RenderChangedRequestV1) -> None:
    expected = _target_entry(request.candidate)
    raw = json.dumps(
        expected,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")
    if (
        request.target_json != raw
        or request.target_digest != graphic_render_intent_digest(expected)
    ):
        raise QualityPassError("changed render request mutated after admission")


def _replace_target(
    request: RenderChangedRequestV1, rendered: GraphicAssetRefV1
) -> tuple[GraphicAssetRefV1, ...]:
    try:
        validate_graphic_asset(rendered)
    except QualityPassContractError as exc:
        raise QualityPassError(str(exc)) from exc
    _validate_render_request(request)
    candidate = request.candidate
    expected = graphic_render_intent_digest(_target_entry(candidate))
    if (
        rendered.graphic_id != candidate.application.graphic_id
        or rendered.render_intent_digest != expected
    ):
        raise QualityPassError("changed render is not bound to repair target")
    matches = [
        asset
        for asset in candidate.parent.graphics_assets
        if asset.graphic_id == rendered.graphic_id
    ]
    if len(matches) != 1:
        raise QualityPassError("approved graphic asset target is ambiguous")
    if matches[0].media.artifact.sha256 == rendered.media.artifact.sha256:
        raise QualityPassError("changed render reused parent media bytes")
    return tuple(
        rendered if asset.graphic_id == rendered.graphic_id else asset
        for asset in candidate.parent.graphics_assets
    )


def _check_candidate(request: CompositeRequestV1, media: CandidateMediaV1) -> None:
    validate_candidate(media)
    parent, application = request.candidate.parent, request.candidate.application
    expected_assets = graphic_asset_set_digest(request.graphic_assets)
    valid = (
        media.plan_digest == application.after_digest
        and media.base_sha256 == parent.base.artifact.sha256
        and media.graphic_asset_set_digest == expected_assets
        and media.final.artifact.sha256 != parent.base.artifact.sha256
        and media.final.artifact.sha256 != parent.final.artifact.sha256
    )
    if not valid:
        raise QualityPassError("composite result is not bound to candidate inputs")


def _check_qc(request: QcRequestV1, qc: QcReceiptV1) -> None:
    validate_qc_receipt(qc)
    expected = request.candidate.application.after_digest
    valid = (
        qc.plan_digest == expected
        and qc.final_sha256 == request.media.final.artifact.sha256
        and qc.assembly_receipt_sha256 == request.media.assembly_receipt.sha256
        and qc.quality_policy_id == request.candidate.parent.quality_policy_id
    )
    if not valid:
        raise QualityPassError("quality receipt is not bound to candidate")


def _run_pipeline(
    request: QualityPassInputV1, ports: QualityPassPorts, timer: TimingRecorder
) -> tuple:
    resolved = timer.measure(
        "admission_import", lambda: _resolve_parent(request, ports)
    )
    parent = resolved[0]
    candidate = timer.measure("repair", lambda: _apply(request, resolved))
    gate = timer.measure("deterministic_gates", lambda: ports.run_gates(candidate))
    _check_gate(candidate, gate)
    render_request = _render_request(candidate)
    timer.measure("resource_wait", lambda: ports.wait_resources(render_request))
    rendered = timer.measure(
        "overlay_render", lambda: ports.render_changed(render_request)
    )
    assets = _replace_target(render_request, rendered)
    composite_request = CompositeRequestV1(request.request_digest, candidate, assets)
    media = timer.measure(
        "composite_audio_proxy", lambda: ports.composite(composite_request)
    )
    _check_candidate(composite_request, media)
    qc_request = QcRequestV1(candidate, media, assets)
    qc = timer.measure("deterministic_qc", lambda: ports.run_qc(qc_request))
    _check_qc(qc_request, qc)
    critic_request = CriticRequestV1(candidate, media, qc)
    queued = timer.measure("model_queue", lambda: ports.queue_critics(critic_request))
    critics = timer.measure("model_run", lambda: ports.run_critics(queued))
    timer.measure(
        "rendered_critics",
        lambda: validate_critic_receipts(
            critics, media.final.artifact.sha256, qc.receipt.sha256
        ),
    )
    seal = SealRequestV1(request, candidate, gate, rendered, assets, media, qc, critics)
    evidence = timer.measure("proof_sealing", lambda: ports.seal_evidence(seal))
    validate_artifact_ref(evidence)
    return parent, candidate, media, qc, critics, evidence


def run_quality_pass(
    request: QualityPassInputV1, ports: QualityPassPorts
) -> QualityPassResultV1:
    """Run one no-writer/no-base-rebuild pass to a verified private MP4."""
    validate_quality_pass_input(request)
    timer = ports.timing_factory()
    if type(timer) is not TimingRecorder:
        raise QualityPassError("quality timing factory returned an invalid recorder")
    try:
        parent, candidate, media, qc, critics, evidence = _run_pipeline(
            request, ports, timer
        )
    except (QualityPassContractError, QualityPassOutputError) as exc:
        raise QualityPassError(str(exc)) from exc
    timing = timer.receipt()
    return QualityPassResultV1(
        "CANDIDATE_CONTRACT_VALIDATED",
        request.request_digest,
        parent.ref,
        candidate.application.after_digest,
        media.final,
        qc.receipt,
        tuple(item.artifact for item in critics),
        evidence,
        timing,
        controller_writer_port_exposed=False,
        controller_base_render_port_exposed=False,
        controller_overlay_dispatches=1,
        controller_composite_dispatches=1,
    )
