"""P4 v2 real grade proof and explicit retired transition/SFX refusal."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from current_render_graph_contract import file_hash
from current_render_oracle import prove as prove_current_render
from edit.exact_timing import PositiveRational
from motion.baseline_look import BaselineSpec, apply_baseline_look
from motion import transitions, transition_sfx_repair
from planner.treatment_models import TreatmentState
from planner.treatment_operations import apply_treatment_operation
from tests.p4_exit_media import ProgramSpec, changed_picture_frames, make_program, prove_decode


def _state(plan: dict) -> TreatmentState:
    return TreatmentState(plan, (), PositiveRational(30, 1), 120)


def _initial_plan() -> dict:
    """Current grade-only fixture; no retired transition is admitted."""
    return {"cutTrack": [{"sourceId": "source-main", "srcStart": 0.0, "srcEnd": 4.0}],
            "transitions": [], "baselineLook": {
                "zoom": 1.0, "centerX": 0.5, "centerY": 0.5, "grade": "none"},
            "music": {"enabled": False}}


def _oracle_summary(receipt: dict) -> dict:
    return {key: receipt[key] for key in (
        "passed", "pictureComparison", "decodedAudioMatch", "streamFactsMatch")}


def _retired_attempt(root: Path, identity: tuple[str, str, object]) -> dict:
    """Instrument only forbidden work; the real policy/parser must reject first."""
    api, kind, sound = identity
    source, output = root / "absent-source.mp4", root / "absent-output.mp4"
    event = {"outTime": 2.0, "kind": kind, "sfx": sound}
    inventory = tuple(sorted(path.name for path in root.iterdir()))
    targets = ("subprocess.Popen", "tempfile.mkdtemp",
               "motion.transitions.probe_video", "motion.transition_sfx_repair.probe_duration")
    with ExitStack() as stack:
        guards = [stack.enter_context(patch(name, side_effect=AssertionError(
            "retired route attempted dependent work: " + name))) for name in targets]
        try:
            if api == "apply_transitions":
                transitions.apply_transitions(str(source), [event], str(output))
            else:
                request = transition_sfx_repair.TransitionSfxRepairRequest(
                    str(source), str(root / "absent-visual.mp4"),
                    [{**event, "sfx": False}], [{**event, "sfx": True}], str(output))
                transition_sfx_repair.repair_transition_sfx(request)
        except ValueError as error:
            if "retired" not in str(error):
                raise
        else:
            raise RuntimeError("retired route unexpectedly admitted execution")
    calls = sum(guard.call_count for guard in guards)
    unchanged = inventory == tuple(sorted(path.name for path in root.iterdir()))
    return {"api": api, "kind": kind, "sfx": sound, "rejected": True,
            "dependentWorkCalls": calls, "outputAbsent": not output.exists(),
            "directoryUnchanged": unchanged,
            "passed": calls == 0 and unchanged and not output.exists()}


def _retired_cases(root: Path) -> dict:
    """No visual/SFX rendering or picture-reuse success is claimed here."""
    rows = [_retired_attempt(root, ("apply_transitions", kind, sound))
            for kind in ("white-flash", "light-leak", "zoom-pull")
            for sound in (False, True, "click")]
    rows += [_retired_attempt(root, ("repair_transition_sfx", kind, True))
             for kind in ("white-flash", "light-leak", "zoom-pull")]
    return {"scope": "real-policy-refusal-with-forbidden-work-instrumentation",
            "cases": rows, "passed": all(row["passed"] for row in rows)}


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
    decoded = [prove_decode(path) for path in (before, incremental, forced)]
    oracle = prove_current_render(
        incremental, forced, root / "grade-oracle.json")
    changed = changed_picture_frames(before, incremental)
    return {
        "passed": (
            source_before == source_after and len(changed) == 120
            and all(row["decodedFrames"] == 120 for row in decoded)
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
        "fullDecode": decoded,
        "forcedFullOracle": _oracle_summary(oracle),
    }


def run_treatment_cases(root: Path) -> dict:
    """Qualify current grade media and fail-closed retired execution separately."""
    retired = _retired_cases(root)
    source = root / "treatment-source.mp4"
    make_program(source, ProgramSpec((320, 180), 30, 4.0, pattern="flat"))
    grade = _grade_case(root, source, _initial_plan())
    return {"passed": retired["passed"] and grade["passed"],
            "source": prove_decode(source), "retiredExecutionRejection": retired, "grade": grade}
