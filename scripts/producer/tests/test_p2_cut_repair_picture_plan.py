"""Exact plan-authoring tests for the bounded picture-repair subset."""
from __future__ import annotations

import copy
import unittest

from edit.compatibility_projection import build_projection, stable_digest
from edit.cut_repair_picture_plan import (
    PictureReviewPlanInput,
    build_picture_review_plan,
)
from edit.cut_repair_picture_plan_admission import PicturePlanError
from edit.cut_repair_picture_plan_authority import (
    PicturePlanAuthorityError,
    parse_picture_plan_authority,
)
from edit.exact_timing import PositiveRational, ProjectClock
from edit.picture_lock_common import content_hash

_CLOCK = ProjectClock(PositiveRational(30, 1), 48_000)


def _plan() -> dict:
    return {
        "planVersion": 1,
        "target": {"mode": "longform", "fps": 30},
        "cutTrack": [
            {"id": "seg-a", "sourceId": "raw",
             "start": 4, "end": 5, "speed": 1},
            {"id": "seg-b", "sourceId": "raw",
             "start": 2, "end": 4, "speed": 1},
        ],
        "cutDecisions": {"schemaVersion": 1, "removals": []},
    }


def _context(plan: dict, plan_hash: str) -> dict:
    timeline_hash = build_projection(plan, plan_hash)["timelineMapHash"]
    return {
        "clock": {
            "fps": {"numerator": "30", "denominator": "1"},
            "sampleRate": 48_000,
        },
        "totalFrames": 90,
        "parentTimelineMapHash": timeline_hash,
        "segments": [
            {
                "segmentId": "seg-a", "elementVersion": 1,
                "sourceId": "raw", "sourceRate": 48_000,
                "sourceSamples": {
                    "startSample": 192_000,
                    "endSampleExclusive": 240_000,
                },
                "outputFrames": {
                    "startFrame": 0, "endFrameExclusive": 30,
                },
                "speed": {"numerator": "1", "denominator": "1"},
                "sourceFps": {"numerator": "30", "denominator": "1"},
            },
            {
                "segmentId": "seg-b", "elementVersion": 1,
                "sourceId": "raw", "sourceRate": 48_000,
                "sourceSamples": {
                    "startSample": 96_000,
                    "endSampleExclusive": 192_000,
                },
                "outputFrames": {
                    "startFrame": 30, "endFrameExclusive": 90,
                },
                "speed": {"numerator": "1", "denominator": "1"},
                "sourceFps": {"numerator": "30", "denominator": "1"},
            },
        ],
    }


def _operation(context: dict) -> dict:
    return {
        "schemaVersion": 1,
        "operation": "cut.restoreSpeech",
        "target": {
            "kind": "word-range", "sourceId": "raw",
            "wordIds": ["w-" + "1" * 16], "occurrence": 1,
            "sourceSampleRange": {
                "startSample": 91_200, "endSampleExclusive": 100_800,
            },
            "transcriptTimingHash": "a" * 64,
        },
        "parentPictureLockHash": "b" * 64,
        "parentTimelineMapHash": context["parentTimelineMapHash"],
        "segment": {"segmentId": "seg-b", "elementVersion": 1,
                    "edge": "start"},
        "sourceExtension": {"startSample": 91_200,
                            "endSampleExclusive": 96_000},
        "sourceSampleRate": 48_000,
        "sourceVideoFrameRange": {
            "startFrame": 57, "endFrameExclusive": 60,
        },
        "sourceFrameRate": {"numerator": "30", "denominator": "1"},
        "speed": {"numerator": "1", "denominator": "1"},
        "extensionFrames": 3,
        "preserveUnrelated": True,
        "totalOutputFramesBefore": 90,
        "totalOutputFramesAfter": 90,
        "method": "extend-and-reclaim-silence",
        "reclaimedSilence": {
            "silenceId": "silence-terminal",
            "sourceSampleRange": {"startSample": 187_200,
                                  "endSampleExclusive": 192_000},
            "outputFrameRange": {"startFrame": 87,
                                 "endFrameExclusive": 90},
        },
        "pictureDirtyWindows": [
            {"startFrame": 30, "endFrameExclusive": 90}],
        "audioDirtyWindows": [
            {"startFrame": 30, "endFrameExclusive": 90}],
        "audioDirtySampleRanges": [
            {"startSample": 48_000, "endSampleExclusive": 144_000}],
        "extensionOutputSamples": 4_800,
        "quantizationResidualSamples": 0,
        "residualPolicy": "reclaimed-proved-silence",
        "unchangedPictureMappingRanges": [
            {"startFrame": 0, "endFrameExclusive": 30}],
        "revalidatedDependentIds": [],
        "unchangedDependentIds": [],
    }


def _build(plan: dict, context: dict, operation: dict):
    operation_hash = content_hash(operation)
    return build_picture_review_plan(PictureReviewPlanInput(
        plan, stable_digest(plan), context, operation,
        operation_hash, _CLOCK, 1))


class CutRepairPicturePlanTests(unittest.TestCase):
    def test_terminal_reclaim_shifts_one_row_without_new_seams(self) -> None:
        plan = _plan()
        plan_hash = stable_digest(plan)
        context = _context(plan, plan_hash)
        result = _build(plan, context, _operation(context))
        child = result.plan["cutTrack"][1]
        self.assertEqual(child, {
            "id": "seg-b", "sourceId": "raw",
            "start": 1.9, "end": 3.9, "speed": 1, "generation": 2,
        })
        self.assertEqual(len(result.plan["cutTrack"]), len(plan["cutTrack"]))
        self.assertEqual(
            result.projection["timelineMap"]["outputDuration"], 3)
        authority = parse_picture_plan_authority(result.authority)
        self.assertEqual(authority["target"], {
            "index": 1, "segmentId": "seg-b",
            "parentElementVersion": 1, "childElementVersion": 2,
        })
        self.assertEqual(
            authority["mappingProof"]["authorizedDirtyWindows"],
            [{"startFrame": 30, "endFrameExclusive": 90}])
        self.assertEqual(
            authority["reversion"]["restoreParentCutRowHash"],
            authority["parentCutRowHash"])

    def test_interior_reclaim_remains_an_explicit_blocker(self) -> None:
        plan = _plan()
        context = _context(plan, stable_digest(plan))
        operation = _operation(context)
        operation["reclaimedSilence"] = {
            "silenceId": "silence-interior",
            "sourceSampleRange": {
                "startSample": 139_200,
                "endSampleExclusive": 144_000,
            },
            "outputFrameRange": {
                "startFrame": 57, "endFrameExclusive": 60,
            },
        }
        operation["pictureDirtyWindows"] = [{
            "startFrame": 30, "endFrameExclusive": 60,
        }]
        operation["audioDirtyWindows"] = copy.deepcopy(
            operation["pictureDirtyWindows"])
        operation["audioDirtySampleRanges"] = [{
            "startSample": 48_000, "endSampleExclusive": 96_000,
        }]
        operation["unchangedPictureMappingRanges"] = [
            {"startFrame": 0, "endFrameExclusive": 30},
            {"startFrame": 60, "endFrameExclusive": 90},
        ]
        with self.assertRaisesRegex(
                PicturePlanError,
                "PICTURE_PLAN_INTERIOR_RECLAIM_CREATES_UNPROVED_SEAMS"):
            _build(plan, context, operation)

    def test_mutation_receipt_rejects_reversion_tamper(self) -> None:
        plan = _plan()
        context = _context(plan, stable_digest(plan))
        result = _build(plan, context, _operation(context))
        authority = copy.deepcopy(result.authority)
        authority["reversion"]["segmentId"] = "seg-a"
        with self.assertRaisesRegex(
                PicturePlanAuthorityError, "stale"):
            parse_picture_plan_authority(authority)


if __name__ == "__main__":
    unittest.main(verbosity=2)
