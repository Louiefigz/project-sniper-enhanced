"""Real transition, SFX, and grade closures for the retained P4 cohort."""
from __future__ import annotations

from pathlib import Path

from current_render_graph_contract import file_hash
from current_render_oracle import observe, prove as prove_current_render
from edit.exact_timing import PositiveRational
from motion.baseline_look import BaselineSpec, apply_baseline_look
from motion.transition_sfx_repair import (
    TransitionSfxRepairRequest,
    repair_transition_sfx,
)
from motion.transitions import apply_transitions
from planner.treatment_models import TreatmentResult, TreatmentState
from planner.treatment_operations import apply_treatment_operation
from tests.p4_exit_media import (
    ProgramSpec,
    changed_picture_frames,
    make_program,
    packet_hash,
    prove_decode,
)


def _state(plan: dict) -> TreatmentState:
    return TreatmentState(
        plan, (), PositiveRational(30, 1), 120)


def _initial_plan() -> dict:
    return {
        "cutTrack": [{
            "sourceId": "source-main", "srcStart": 0.0, "srcEnd": 4.0,
        }],
        "transitions": [{
            "id": "seam-hook", "outFrame": 60, "outTime": 2.0,
            "kind": "white-flash", "sfx": False,
        }],
        "baselineLook": {
            "zoom": 1.0, "centerX": 0.5, "centerY": 0.5, "grade": "none",
        },
        "music": {"enabled": False},
    }


def _raw_event(row: dict) -> list[dict]:
    return [{
        "outTime": row["outTime"], "kind": row["kind"], "sfx": row["sfx"],
    }]


def _oracle_summary(receipt: dict) -> dict:
    return {
        "passed": receipt["passed"],
        "pictureComparison": receipt["pictureComparison"],
        "decodedAudioMatch": receipt["decodedAudioMatch"],
        "streamFactsMatch": receipt["streamFactsMatch"],
    }


def _inside_windows(frames: list[int], windows: list[dict]) -> int:
    return sum(any(
        row["startFrame"] <= frame < row["endFrameExclusive"]
        for row in windows)
        for frame in frames)


def _transition_operation(plan: dict) -> TreatmentResult:
    expected = {
        "id": "seam-hook", "outFrame": 60,
        "kind": "white-flash", "sfx": False,
    }
    value = {
        "id": "seam-hook", "outFrame": 90,
        "kind": "light-leak", "sfx": False,
    }
    return apply_treatment_operation(_state(plan), {
        "schemaVersion": 1, "operation": "transition.set",
        "transitionId": "seam-hook",
        "expectedValue": expected, "value": value,
    })


def _transition_case(root: Path, source: Path) -> tuple[dict, dict, Path]:
    plan = _initial_plan()
    before = root / "transition-before.mp4"
    incremental = root / "transition-incremental.mp4"
    forced = root / "transition-forced.mp4"
    apply_transitions(
        str(source), _raw_event(plan["transitions"][0]), str(before))
    treatment = _transition_operation(plan)
    after = treatment.state.plan["transitions"][0]
    source_before = file_hash(source)
    incremental_result = apply_transitions(
        str(source), _raw_event(after), str(incremental))
    forced_result = apply_transitions(
        str(source), _raw_event(after), str(forced))
    source_after = file_hash(source)
    oracle = prove_current_render(
        incremental, forced, root / "transition-oracle.json")
    changed = changed_picture_frames(before, incremental)
    windows = treatment.receipt["dirtyWindows"]
    inside = _inside_windows(changed, windows)
    result = {
        "passed": (
            source_before == source_after and bool(changed)
            and inside > 0 and len(changed) - inside == 0
            and oracle["passed"]
            and incremental_result["outFrames"] == 120
            and forced_result["outFrames"] == 120
            and treatment.receipt["invalidatedNodes"]
            == ["base-video", "transition-video"]
        ),
        "operationReceipt": treatment.receipt,
        "reusedUpstreamSha256": source_after,
        "decodedChangedFrames": len(changed),
        "decodedChangedInsideDirtyWindows": inside,
        "decodedChangedOutsideDirtyWindows": len(changed) - inside,
        "closureSemantics": (
            "the upstream program artifact is byte-reused; transition-video "
            "and base-video are the declared rerendered nodes"),
        "forcedFullOracle": _oracle_summary(oracle),
    }
    return result, treatment.state.plan, incremental


def _repair_summary(repair: dict) -> dict:
    channel = repair["channelNormalization"]
    result = {
        key: repair[key] for key in (
            "inFrames", "outFrames", "audioInS", "audioOutS",
            "programSourceSha256", "picturePacketSha256", "pictureReused",
            "changedSfxSlots", "sfx", "whooshPeakDbfs",
        )
    }
    result["channelNormalization"] = {
        "status": channel["decision"]["status"],
        "receiptHash": channel["receiptHash"],
    }
    return result


def _sfx_case(
    root: Path,
    source: Path,
    transition_plan: dict,
    visual_before: Path,
) -> dict:
    treatment = apply_treatment_operation(_state(transition_plan), {
        "schemaVersion": 1, "operation": "sfx.set",
        "transitionId": "seam-hook", "expectedSfx": False, "sfx": True,
    })
    before_event = _raw_event(transition_plan["transitions"][0])
    after_event = _raw_event(treatment.state.plan["transitions"][0])
    incremental = root / "sfx-incremental.mp4"
    forced = root / "sfx-forced.mp4"
    repair = repair_transition_sfx(TransitionSfxRepairRequest(
        str(source), str(visual_before), before_event, after_event,
        str(incremental)))
    apply_transitions(str(source), after_event, str(forced))
    oracle = prove_current_render(
        incremental, forced, root / "sfx-oracle.json")
    before_observation = observe(visual_before)
    after_observation = observe(incremental)
    picture_reused = packet_hash(visual_before) == packet_hash(incremental)
    return {
        "passed": (
            treatment.receipt["mediaReused"] is True
            and treatment.receipt["invalidatedNodes"]
            == ["final-mux", "master-audio", "transition-audio"]
            and repair["pictureReused"] is True and picture_reused
            and before_observation.pictureFrameMd5Sha256
            == after_observation.pictureFrameMd5Sha256
            and before_observation.pcmSha256 != after_observation.pcmSha256
            and oracle["passed"]
        ),
        "operationReceipt": treatment.receipt,
        "picturePacketReused": picture_reused,
        "pictureFrameMd5Reused": (
            before_observation.pictureFrameMd5Sha256
            == after_observation.pictureFrameMd5Sha256),
        "audioChanged": (
            before_observation.pcmSha256 != after_observation.pcmSha256),
        "repair": _repair_summary(repair),
        "forcedFullOracle": _oracle_summary(oracle),
    }


def _grade_case(root: Path, source: Path, plan: dict) -> dict:
    treatment = apply_treatment_operation(_state(plan), {
        "schemaVersion": 1, "operation": "grade.set",
        "expectedGrade": "none", "grade": "warm",
    })
    before = root / "grade-before.mp4"
    incremental = root / "grade-incremental.mp4"
    forced = root / "grade-forced.mp4"
    plain = BaselineSpec(
        zoom=1.0, center_x=0.5, center_y=0.5,
        grade="none", out_w=320, out_h=180)
    warm = BaselineSpec(
        zoom=1.0, center_x=0.5, center_y=0.5,
        grade="warm", out_w=320, out_h=180)
    apply_baseline_look(str(source), plain, str(before))
    source_before = file_hash(source)
    incremental_result = apply_baseline_look(
        str(source), warm, str(incremental))
    forced_result = apply_baseline_look(str(source), warm, str(forced))
    source_after = file_hash(source)
    oracle = prove_current_render(
        incremental, forced, root / "grade-oracle.json")
    changed = changed_picture_frames(before, incremental)
    return {
        "passed": (
            source_before == source_after and bool(changed)
            and treatment.receipt["dirtyWindows"]
            == [{"startFrame": 0, "endFrameExclusive": 120}]
            and treatment.receipt["invalidatedNodes"]
            == ["base-video-full", "final-video", "graphics-composite-full"]
            and incremental_result["outFrames"] == 120
            and forced_result["outFrames"] == 120
            and oracle["passed"]
        ),
        "operationReceipt": treatment.receipt,
        "reusedUpstreamSha256": source_after,
        "decodedChangedFrames": len(changed),
        "forcedFullOracle": _oracle_summary(oracle),
    }


def run_treatment_cases(root: Path) -> dict:
    """Execute all three typed operations against populated real media."""
    source = root / "treatment-source.mp4"
    make_program(source, ProgramSpec((320, 180), 30, 4.0, pattern="flat"))
    transition, changed_plan, visual = _transition_case(root, source)
    sfx = _sfx_case(root, source, changed_plan, visual)
    grade = _grade_case(root, source, changed_plan)
    decoded = prove_decode(source)
    passed = all(row["passed"] for row in (transition, sfx, grade))
    return {
        "passed": passed, "source": decoded,
        "transition": transition, "sfx": sfx, "grade": grade,
    }
