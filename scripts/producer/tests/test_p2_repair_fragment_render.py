"""Real multi-source/VFR P2 dirty-fragment render and receipt tests."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from edit.exact_timing import PositiveRational, ProjectClock
from captions.caption_plan_pipeline import PlanCaptionContext
from captions.caption_repair_revalidation import CaptionRepairContexts
from captions.caption_words import CaptionFrameRate
from edit.cut_repair_execution import (
    CutRepairExecutionInput,
    execute_cut_repair_candidate,
)
from edit.exact_timing import FrameRange, SampleRange
from edit.picture_lock import PictureLockInput, SelectedApproval
from edit.picture_lock_common import content_hash
from edit.picture_lock_mapping import MappingProofInput, MappingSpan
from edit.repair_fragment import render_repair_fragment
from edit.repair_fragment_contracts import (
    RepairFragmentRequest,
)
from compile_timeline import compile_plan
from tests._p2_repair_media_fixture import (
    FFMPEG,
    FFPROBE,
    media as _media,
    operation as _operation,
    picture_operation as _picture_operation,
    tools as _tools,
)

def _receipt_schema() -> dict[str, object]:
    path = (Path(__file__).resolve().parents[3] / "schemas" / "producer"
            / "cut-repair-fragment-receipt-v1.schema.json")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _assert_closed_shape(
    case: unittest.TestCase,
    value: dict[str, object],
    schema: dict[str, object],
) -> None:
    required = set(schema["required"])
    properties = set(schema["properties"])
    case.assertEqual(set(value), required)
    case.assertEqual(required, properties)


def _controller_fragment(
    root: str,
    clock: ProjectClock,
    operation: dict,
) -> tuple[RepairFragmentRequest, str]:
    parent = os.path.join(root, "parent.mov")
    source = os.path.join(root, "source-vfr.mov")
    _media(parent, "30/1", False)
    _media(source, "30/1", True)
    return (
        RepairFragmentRequest(
            operation, content_hash(operation), parent, source,
            os.path.join(root, "repair.mov"), clock, _tools()),
        os.path.join(root, "candidate.mov"),
    )


def _controller_proof(child_hash: str) -> MappingProofInput:
    span = MappingSpan(
        FrameRange(0, 150), "source-a", SampleRange(0, 240_000))
    return MappingProofInput(
        "c" * 64, child_hash, (span,), (span,),
        (FrameRange(60, 62),), 150)


def _controller_lock(child_hash: str) -> PictureLockInput:
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


def _controller_captions(root: str) -> CaptionRepairContexts:
    plan = {"cutTrack": [{
        "sourceId": "source-a", "start": 0.0, "end": 5.0, "speed": 1.0,
    }]}
    context = PlanCaptionContext(
        plan, {"sources": []},
        compile_plan(plan), CaptionFrameRate(30, 1), root)
    return CaptionRepairContexts(context, context)


def _controller_candidate(root: str) -> tuple[dict, dict, ProjectClock]:
    rate = PositiveRational(30, 1)
    clock = ProjectClock(rate, 48_000)
    operation = _operation(clock)
    fragment, candidate = _controller_fragment(root, clock, operation)
    child_hash = "e" * 64
    result = execute_cut_repair_candidate(CutRepairExecutionInput(
        fragment, _controller_lock(child_hash), child_hash,
        _controller_proof(child_hash),
        ("clause-old",), ("clause-new",), ("operation-old",),
        ({"sourceId": "source-a", "start": 0.0,
          "end": 5.0, "speed": 1.0},),
        rate, False, candidate, _controller_captions(root)))
    return result, operation, clock


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg and ffprobe required")
class RepairFragmentRenderTests(unittest.TestCase):
    def test_fractional_and_integer_fps_normalize_vfr_multi_source(self) -> None:
        rates = tuple(PositiveRational(*terms) for terms in (
            (24000, 1001), (24, 1), (25, 1), (30000, 1001),
            (30, 1), (50, 1), (60000, 1001), (60, 1)))
        for rate in rates:
            with self.subTest(rate=rate):
                self._run_rate(rate)

    def _run_rate(self, rate: PositiveRational) -> None:
        with tempfile.TemporaryDirectory(prefix="p2-fragment-") as directory:
            root = os.path.realpath(directory)
            fps = f"{rate.numerator}/{rate.denominator}"
            parent = os.path.join(root, "parent.mov")
            source = os.path.join(root, "source-vfr.mov")
            output = os.path.join(root, "repair.mov")
            _media(parent, fps, False)
            _media(source, fps, True)
            clock = ProjectClock(rate, 48_000)
            operation = _operation(clock)
            receipt = render_repair_fragment(RepairFragmentRequest(
                operation, content_hash(operation), parent, source,
                output, clock, _tools()))
            self.assertTrue(os.path.isfile(output))
            self.assertEqual(receipt["operationHash"], content_hash(operation))
            self.assertEqual(
                receipt["retime"]["requestedSpeed"],
                {"numerator": "1", "denominator": "1"})
            end_frame = 60 + operation["extensionFrames"]
            expected = clock.sample_at_frame(end_frame) \
                - clock.sample_at_frame(60)
            self.assertEqual(
                receipt["output"]["audioSamplesPerChannel"], expected)
            self.assertEqual(
                receipt["output"]["videoFrames"],
                operation["extensionFrames"])
            self.assertEqual(
                receipt["inputs"]["source"]["timingClass"],
                "normalized-from-vfr-source")
            self.assertNotEqual(
                receipt["inputs"]["source"]["sha256"],
                receipt["inputs"]["parent"]["sha256"])
            schema = _receipt_schema()
            _assert_closed_shape(self, receipt, schema)
            properties = schema["properties"]
            _assert_closed_shape(
                self, receipt["retime"], properties["retime"])
            _assert_closed_shape(
                self, receipt["output"], properties["output"])

    def test_picture_extension_reclaims_exact_silence_samples(self) -> None:
        rate = PositiveRational(30000, 1001)
        with tempfile.TemporaryDirectory(prefix="p2-picture-") as directory:
            root = os.path.realpath(directory)
            parent = os.path.join(root, "parent.mov")
            source = os.path.join(root, "source-vfr.mov")
            output = os.path.join(root, "repair.mov")
            fps = f"{rate.numerator}/{rate.denominator}"
            _media(parent, fps, False)
            _media(source, fps, True, False)
            clock = ProjectClock(rate, 48_000)
            operation = _picture_operation(clock)
            receipt = render_repair_fragment(RepairFragmentRequest(
                operation, content_hash(operation), parent, source,
                output, clock, _tools()))
            self.assertEqual(receipt["method"],
                             "extend-and-reclaim-silence")
            self.assertEqual(receipt["output"]["videoFrames"], 30)
            expected = clock.sample_at_frame(80) - clock.sample_at_frame(50)
            self.assertEqual(
                receipt["output"]["audioSamplesPerChannel"], expected)
            self.assertIn(
                receipt["frameBoundaryResidualSamples"], {-1, 0, 1})

    def test_real_speed_retime_matches_canonical_receipt(self) -> None:
        rate = PositiveRational(30, 1)
        with tempfile.TemporaryDirectory(prefix="p2-speed-") as directory:
            root = os.path.realpath(directory)
            parent = os.path.join(root, "parent.mov")
            source = os.path.join(root, "source-vfr.mov")
            output = os.path.join(root, "repair.mov")
            _media(parent, "30/1", False)
            _media(source, "30/1", True)
            clock = ProjectClock(rate, 48_000)
            operation = _operation(clock)
            operation["target"]["sourceSampleRange"] = {
                "startSample": 48_000,
                "endSampleExclusive": 52_800,
            }
            operation["sourceExtension"] = {
                "startSample": 48_000,
                "endSampleExclusive": 52_800,
            }
            operation["speed"] = {
                "numerator": "2",
                "denominator": "1",
            }
            receipt = render_repair_fragment(RepairFragmentRequest(
                operation, content_hash(operation), parent, source,
                output, clock, _tools()))
            self.assertEqual(
                receipt["retime"]["requestedSpeed"],
                {"numerator": "2", "denominator": "1"})
            self.assertEqual(
                receipt["retime"]["effectiveRatio"],
                {"numerator": "2", "denominator": "1"})
            self.assertEqual(
                receipt["retime"]["normalizedSourceSampleRange"],
                {"startSample": 48_000, "endSampleExclusive": 52_800})
            self.assertEqual(receipt["retime"]["outputSamples"], 2_400)

    def test_controller_binds_fragment_child_lock_and_supersession(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p2-controller-") as directory:
            root = os.path.realpath(directory)
            result, operation, clock = _controller_candidate(root)
            self.assertEqual(result["status"], "candidate-proved")
            self.assertEqual(
                result["childPictureLock"]["parentPictureLockHash"],
                "b" * 64)
            self.assertEqual(
                result["supersessionReceipt"]["repairOperationHash"],
                content_hash(operation))
            self.assertEqual(
                result["palmierDisposition"]["nativeStatus"], "skipped")
            self.assertTrue(
                result["invariantProof"]["totalOutputFramesPreserved"])
            self.assertTrue(
                result["invariantProof"]["terminalCompositeProved"])
            self.assertEqual(
                result["captionRevalidation"]["status"], "not-present")
            self.assertEqual(
                result["invariantProof"]["captionRevalidationHash"],
                result["captionRevalidation"]["revalidationHash"])
            self.assertEqual(
                result["compositeReceipt"]["terminalExpectedSamples"],
                clock.sample_at_frame(150))
