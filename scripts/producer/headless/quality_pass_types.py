"""Immutable requests, ports, and results for the quality-pass controller."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .quality_pass_contract import (
    ApprovedParentV1,
    ArtifactRefV1,
    GraphicAssetRefV1,
    ParentRefV1,
    QualityPassInputV1,
)
from .quality_pass_outputs import (
    CandidateMediaV1,
    CriticReceiptV1,
    GateReceiptV1,
    QcReceiptV1,
)
from .quality_timing import TimingReceiptV1, TimingRecorder
from .repair_intent import RepairApplication


@dataclass(frozen=True)
class CandidatePlanV1:
    """Exact parent plus immutable one-pointer repair application."""

    parent: ApprovedParentV1
    application: RepairApplication


@dataclass(frozen=True)
class RenderChangedRequestV1:
    """Sole changed graphic render request."""

    candidate: CandidatePlanV1
    target_json: bytes
    target_digest: str

    def decoded_target(self) -> dict:
        """Return a disposable target copy for the renderer adapter."""
        return json.loads(self.target_json)


@dataclass(frozen=True)
class CompositeRequestV1:
    """Exact base, plan, timeline, and complete graphic asset set."""

    request_digest: str
    candidate: CandidatePlanV1
    graphic_assets: tuple[GraphicAssetRefV1, ...]


@dataclass(frozen=True)
class QcRequestV1:
    """Complete deterministic-QC input for the recomposited candidate."""

    candidate: CandidatePlanV1
    media: CandidateMediaV1
    graphic_assets: tuple[GraphicAssetRefV1, ...]


@dataclass(frozen=True)
class CriticRequestV1:
    """Immutable rendered-evidence request shared by both critic lenses."""

    candidate: CandidatePlanV1
    media: CandidateMediaV1
    qc: QcReceiptV1


@dataclass(frozen=True)
class SealRequestV1:
    """Verified child claims submitted to the byte-level evidence sealer."""

    request: QualityPassInputV1
    candidate: CandidatePlanV1
    gate: GateReceiptV1
    rendered: GraphicAssetRefV1
    graphic_assets: tuple[GraphicAssetRefV1, ...]
    media: CandidateMediaV1
    qc: QcReceiptV1
    critics: tuple[CriticReceiptV1, ...]


@dataclass(frozen=True)
class QualityPassPorts:
    """Concrete non-GUI adapters owned by the composition root."""

    resolve_parent: Callable[[ParentRefV1], ApprovedParentV1]
    run_gates: Callable[[CandidatePlanV1], GateReceiptV1]
    wait_resources: Callable[[RenderChangedRequestV1], None]
    render_changed: Callable[[RenderChangedRequestV1], GraphicAssetRefV1]
    composite: Callable[[CompositeRequestV1], CandidateMediaV1]
    run_qc: Callable[[QcRequestV1], QcReceiptV1]
    queue_critics: Callable[[CriticRequestV1], Any]
    run_critics: Callable[[Any], tuple[CriticReceiptV1, ...]]
    seal_evidence: Callable[[SealRequestV1], ArtifactRefV1]
    timing_factory: Callable[[], TimingRecorder]


@dataclass(frozen=True)
class QualityPassResultV1:
    """Private candidate contract result; not publication or verification."""

    status: str
    request_digest: str
    parent: ParentRefV1
    candidate_plan_digest: str
    final: object
    qc_receipt: ArtifactRefV1
    critic_receipts: tuple[ArtifactRefV1, ...]
    evidence_receipt: ArtifactRefV1
    timing: TimingReceiptV1
    controller_writer_port_exposed: bool
    controller_base_render_port_exposed: bool
    controller_overlay_dispatches: int
    controller_composite_dispatches: int
