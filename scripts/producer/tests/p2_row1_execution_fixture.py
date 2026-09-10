"""One executable real-media case for the retained P2 row-one cohort."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from edit.cut_repair_execution import (
    CutRepairExecutionInput,
    execute_cut_repair_candidate,
)
from edit.exact_timing import (
    FrameRange,
    PositiveRational,
    ProjectClock,
    SampleRange,
)
from edit.picture_lock import PictureLockInput, SelectedApproval
from edit.picture_lock_common import content_hash
from edit.picture_lock_mapping import MappingProofInput, MappingSpan
from edit.repair_fragment_contracts import RepairFragmentRequest
from tests._p2_repair_media_fixture import (
    media as make_media,
    operation as base_operation,
    tools,
)
from tests.p2_row1_caption_fixture import (
    CaptionFixtureInput,
    TOTAL_FRAMES,
    caption_contexts,
    dialogue_evidence,
)
from tests.p2_row1_receipt import (
    assertions,
    caption_evidence,
    invariants,
    media_evidence,
    palmier_evidence,
)

POSITIONS = ("early", "middle", "late")
SPLIT_FRAME = 75


@dataclass(frozen=True)
class CaseSpec:
    """One exact rate/position cell in the claim-sized cross-product."""

    rate: PositiveRational
    position: str

    @property
    def rate_token(self) -> str:
        """Return a stable human/machine-readable rational-rate token."""
        return f"{self.rate.numerator}/{self.rate.denominator}"

    @property
    def case_id(self) -> str:
        """Return the stable case identity."""
        token = self.rate_token.replace("/", "-")
        return f"p2-row1-{token}-{self.position}"


@dataclass(frozen=True)
class CohortMedia:
    """Immutable parent and normalized-VFR source reused by one rate row."""

    parent: Path
    source: Path


def prepare_rate_media(root: Path, rate: PositiveRational) -> CohortMedia:
    """Generate one real parent/source pair for all positions at one rate."""
    root.mkdir(parents=True)
    fps = f"{rate.numerator}/{rate.denominator}"
    parent, source = root / "parent.mov", root / "source-vfr.mov"
    make_media(str(parent), fps, False)
    make_media(str(source), fps, True)
    return CohortMedia(parent.resolve(), source.resolve())


def _dirty_start(position: str, extension_frames: int) -> int:
    if position == "early":
        return 0
    if position == "middle":
        return 60
    if position == "late":
        return TOTAL_FRAMES - extension_frames
    raise ValueError(f"unsupported cohort position: {position}")


def _operation(clock: ProjectClock, position: str) -> dict:
    value = base_operation(clock)
    start = _dirty_start(position, value["extensionFrames"])
    end = start + value["extensionFrames"]
    sample_start = clock.sample_at_frame(start)
    samples = {
        "startSample": sample_start,
        "endSampleExclusive":
            sample_start + value["extensionOutputSamples"],
    }
    source_id = "source-a" if start < SPLIT_FRAME else "source-b"
    value["target"]["sourceId"] = source_id
    value["segment"]["segmentId"] = f"segment-{source_id[-1]}"
    value["audioDirtyWindows"] = [{
        "startFrame": start, "endFrameExclusive": end,
    }]
    value["audioDirtySampleRanges"] = [samples]
    value["replacedAudioSampleRanges"] = [samples]
    return value


def _mapping_spans(clock: ProjectClock) -> tuple[MappingSpan, ...]:
    first = clock.sample_at_frame(SPLIT_FRAME)
    total = clock.sample_at_frame(TOTAL_FRAMES)
    return (
        MappingSpan(
            FrameRange(0, SPLIT_FRAME), "source-a",
            SampleRange(0, first)),
        MappingSpan(
            FrameRange(SPLIT_FRAME, TOTAL_FRAMES), "source-b",
            SampleRange(0, total - first)),
    )


def _mapping_proof(
    clock: ProjectClock,
    operation: dict,
    child_hash: str,
) -> MappingProofInput:
    dirty = operation["audioDirtyWindows"][0]
    window = FrameRange(
        dirty["startFrame"], dirty["endFrameExclusive"])
    spans = _mapping_spans(clock)
    return MappingProofInput(
        "c" * 64, child_hash, spans, spans, (window,), TOTAL_FRAMES)


def _child_lock(child_hash: str) -> PictureLockInput:
    return PictureLockInput(
        approved_cut_revision_hash="1" * 64,
        plan_content_hash="2" * 64,
        timeline_map_hash=child_hash,
        source_snapshot_set_hash="3" * 64,
        transcript_timing_hash="a" * 64,
        cut_approval_receipt_hash="4" * 64,
        cut_review_approval_receipt_hash="5" * 64,
        workflow_policy="cut-first",
        selected_approval=SelectedApproval(
            "operator", "6" * 64, "7" * 64),
        parent_picture_lock_hash="b" * 64,
    )


def _cut_track(spec: CaseSpec) -> list[dict[str, object]]:
    half = SPLIT_FRAME * spec.rate.denominator / spec.rate.numerator
    return [
        {"sourceId": "source-a", "start": 0.0,
         "end": half, "speed": 1.0},
        {"sourceId": "source-b", "start": 0.0,
         "end": half, "speed": 1.0},
    ]


def _request(
    root: Path,
    media: CohortMedia,
    operation: dict,
    clock: ProjectClock,
) -> RepairFragmentRequest:
    return RepairFragmentRequest(
        operation, content_hash(operation),
        str(media.parent), str(media.source),
        str((root / "repair.mov").resolve()), clock, tools())


def _execute(
    root: Path,
    spec: CaseSpec,
    media: CohortMedia,
) -> tuple[dict, dict, ProjectClock, dict]:
    clock = ProjectClock(spec.rate, 48_000)
    operation = _operation(clock, spec.position)
    child_hash = content_hash({
        "caseId": spec.case_id, "mapping": [
            span.source_id for span in _mapping_spans(clock)],
    })
    captions, caption_meta = caption_contexts(CaptionFixtureInput(
        root, spec.rate, clock,
        operation["audioDirtyWindows"][0]["startFrame"]))
    item = CutRepairExecutionInput(
        _request(root, media, operation, clock),
        _child_lock(child_hash), child_hash,
        _mapping_proof(clock, operation, child_hash),
        ("clause-old",), ("clause-new",), ("operation-old",),
        _cut_track(spec), spec.rate, True,
        str((root / "candidate.mov").resolve()), captions)
    return execute_cut_repair_candidate(item), operation, clock, caption_meta


def run_case(root: Path, spec: CaseSpec, media: CohortMedia) -> dict:
    """Execute and distill one complete real-media claim cell."""
    root.mkdir(parents=True)
    result, operation, clock, caption_meta = _execute(root, spec, media)
    dirty = operation["audioDirtyWindows"][0]
    value = {
        "schemaVersion": 1,
        "fixtureId": "p2-row1-real-vfr-multisource-caption-jl-v1",
        "caseId": spec.case_id, "rateToken": spec.rate_token,
        "fps": spec.rate.to_dict(), "candidateStatus": result["status"],
        "repair": {
            "position": spec.position, "method": operation["method"],
            "operationHash": content_hash(operation),
            "dirtyFrameWindow": dirty,
            "extensionFrames": operation["extensionFrames"],
            "targetSourceId": operation["target"]["sourceId"],
        },
        "authority": {
            "sourceIds": sorted({
                row["sourceId"] for row in _cut_track(spec)}),
            "childCutTrackHash": content_hash(_cut_track(spec)),
            "childPictureLockHash": result["childPictureLockHash"],
            "supersessionHash": result["supersessionHash"],
        },
        "media": media_evidence(result),
        "captions": caption_evidence(result, caption_meta),
        "dialogue": dialogue_evidence(
            CaptionFixtureInput(
                root, spec.rate, clock, dirty["startFrame"]),
            result["childPictureLock"]["timelineMapHash"]),
        "palmier": palmier_evidence(result),
        "invariants": invariants(result),
    }
    value["assertions"] = assertions(value)
    value["passed"] = all(value["assertions"].values())
    value["receiptHash"] = content_hash(value)
    return value
